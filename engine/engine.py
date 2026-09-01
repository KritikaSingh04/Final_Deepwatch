"""Analytics engine: orchestrates the two sensor detectors, NPW
localization, the event state machine, health states and the automated
virtual-isolation response.

The engine is fed one telemetry sample at a time (edge-processing model):
it never sees the file as a whole, so the identical object works on live
streams, the development dataset and blind datasets. It never reads the
Status Flag column — the loader quarantines it before data reaches here.

Event state machine (per the challenge logic):

    NORMAL
      -> ANOMALY_SUSPECTED   first sensor transient confirmed
      -> LEAK_CONFIRMED      correlated second transient (valid NPW dt)
      -> LOCALIZED           NPW coordinate inside [0, L]
      -> CRITICAL            sustained RED health (<60% of baseline)
      -> ISOLATED            automatic virtual isolation response

* A single-sensor event NEVER claims "leak confirmed" — it opens an
  anomaly-suspected early warning only.
* Localization alone NEVER triggers isolation; the virtual isolation
  executes when the critical condition is satisfied.
* A leak signature additionally requires a sharp NPW front on at least
  one sensor or a deep (<80%) sustained drop, so a coordinated gentle
  decline on both sensors (operational ramp) stays an anomaly watch —
  this is the no-leak/false-alarm control protection.
* If the two arrivals imply X outside [0, L], the localization is flagged
  INVALID (uncorrelated transients) instead of being clipped.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .detector import SensorDetector, DetectorConfig, CONFIRMED
from .forecast import eta_to_thresholds
from .health import classify, worst, GREEN, YELLOW, ORANGE, RED
from .mlscore import OnlineAnomalyScorer
from .npw import (PIPELINE_LENGTH_M, WAVE_SPEED_MS, NUM_SEGMENTS,
                  Localization, localize)

# engine states, in escalation order
NORMAL = "NORMAL"
ANOMALY_SUSPECTED = "ANOMALY_SUSPECTED"
LEAK_CONFIRMED = "LEAK_CONFIRMED"
LOCALIZED = "LOCALIZED"
CRITICAL = "CRITICAL"
ISOLATED = "ISOLATED"

STATE_ORDER = [NORMAL, ANOMALY_SUSPECTED, LEAK_CONFIRMED, LOCALIZED,
               CRITICAL, ISOLATED]
ALARM_STATES = (LEAK_CONFIRMED, LOCALIZED, CRITICAL, ISOLATED)

SEVERITY_BY_TIER = {GREEN: None, YELLOW: "LOW", ORANGE: "MAJOR", RED: "CRITICAL"}
_SEV_RANK = {None: 0, "LOW": 1, "MAJOR": 2, "CRITICAL": 3}


@dataclass
class EngineConfig:
    length_m: float = PIPELINE_LENGTH_M
    wave_speed_ms: float = WAVE_SPEED_MS
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    ratio_window: int = 5            # samples for the sustained-ratio median
    deep_drop: float = 0.80          # deep sustained drop => leak signature
    critical_ratio: float = 0.60     # sustained RED => critical condition
    forecast_window: int = 30        # samples used for time-to-critical fit
    enable_ml: bool = True


class AnalyticsEngine:
    def __init__(self, config: Optional[EngineConfig] = None):
        self.config = config or EngineConfig()
        c = self.config
        self.inlet = SensorDetector("inlet", c.detector)
        self.outlet = SensorDetector("outlet", c.detector)
        self.state = NORMAL
        self.severity: Optional[str] = None
        self.localization: Optional[Localization] = None
        self.localization_invalid = False
        self.isolated_segment: Optional[int] = None
        self.isolation_time: Optional[float] = None
        self.critical_time: Optional[float] = None
        self.events: list[dict] = []
        self.stages: dict[str, Optional[float]] = {
            "detect": None, "analyze": None, "localize": None,
            "visualize": None, "respond": None,
        }
        self.ml = OnlineAnomalyScorer() if c.enable_ml else None
        self._seen_arrival = {"inlet": False, "outlet": False}
        self._ratios = {"inlet": deque(maxlen=c.ratio_window),
                        "outlet": deque(maxlen=c.ratio_window)}
        self._forecast_buf = {"inlet": deque(maxlen=c.forecast_window),
                              "outlet": deque(maxlen=c.forecast_window)}
        self.history: list[tuple] = []  # (t, p_in, p_out, base_in, base_out)
        self.sample_count = 0

    # ------------------------------------------------------------------
    def update(self, t: float, p_in: float, p_out: float) -> dict:
        c = self.config
        self.sample_count += 1
        new_events: list[dict] = []

        s_in = self.inlet.update(t, p_in)
        s_out = self.outlet.update(t, p_out)
        self.history.append((t, p_in, p_out, s_in.baseline, s_out.baseline))
        self._ratios["inlet"].append(s_in.ratio)
        self._ratios["outlet"].append(s_out.ratio)
        self._forecast_buf["inlet"].append((t, p_in))
        self._forecast_buf["outlet"].append((t, p_out))

        med_in = _median(self._ratios["inlet"])
        med_out = _median(self._ratios["outlet"])
        health_in = classify(med_in)
        health_out = classify(med_out)
        global_tier = worst(health_in.tier, health_out.tier)

        # --- transient arrival events -------------------------------------
        for name, status in (("inlet", s_in), ("outlet", s_out)):
            if status.phase == CONFIRMED and not self._seen_arrival[name]:
                self._seen_arrival[name] = True
                new_events.append(self._event(
                    t, "TRANSIENT_DETECTED",
                    f"Pressure transient confirmed at {name.upper()} — "
                    f"arrival t = {status.arrival_time:.2f} s "
                    f"({status.trigger_kind} detector)",
                    sensor=name, arrival=status.arrival_time,
                    trigger=status.trigger_kind))
                if self.stages["detect"] is None:
                    self.stages["detect"] = t

        any_confirmed = self._seen_arrival["inlet"] or self._seen_arrival["outlet"]
        both_confirmed = self._seen_arrival["inlet"] and self._seen_arrival["outlet"]

        # --- NORMAL -> ANOMALY_SUSPECTED ----------------------------------
        if self.state == NORMAL and any_confirmed:
            self.state = ANOMALY_SUSPECTED
            new_events.append(self._event(
                t, "ANOMALY_SUSPECTED",
                "Anomaly suspected — single-station transient, awaiting "
                "correlated arrival at the second station"))

        # --- correlation + NPW localization -------------------------------
        if both_confirmed and self.localization is None \
                and not self.localization_invalid:
            dt_nom = max(self.inlet.dt_nominal, self.outlet.dt_nominal)
            loc = localize(self.inlet.arrival_time, self.outlet.arrival_time,
                           c.length_m, c.wave_speed_ms,
                           tolerance_m=c.wave_speed_ms * dt_nom / 2)
            if self.stages["analyze"] is None:
                self.stages["analyze"] = t
            if loc.valid:
                self.localization = loc
            else:
                self.localization_invalid = True
                new_events.append(self._event(
                    t, "LOCALIZATION_INVALID",
                    f"Transients NOT correlated: Δt = {loc.delta_t:+.2f} s "
                    f"implies X = {loc.x_raw_m:,.0f} m — outside [0, "
                    f"{c.length_m:,.0f}] m. Treating as independent "
                    f"anomalies; no leak confirmation.",
                    delta_t=loc.delta_t, x_raw_m=loc.x_raw_m))

        # --- ANOMALY_SUSPECTED -> LEAK_CONFIRMED -> LOCALIZED -------------
        # leak signature: sharp NPW front on >= 1 sensor, or deep drop
        sharp_front = (self.inlet.trigger_kind == "rate"
                       or self.outlet.trigger_kind == "rate")
        deep = min(med_in, med_out) < c.deep_drop
        if (self.state == ANOMALY_SUSPECTED and self.localization is not None
                and (sharp_front or deep)):
            self.state = LEAK_CONFIRMED
            new_events.append(self._event(
                t, "LEAK_CONFIRMED",
                "LEAK CONFIRMED — correlated pressure transients at both "
                "stations with loss-of-containment signature", alarm=True))
            loc = self.localization
            self.state = LOCALIZED
            self.stages["localize"] = t
            self.stages["visualize"] = t
            new_events.append(self._event(
                t, "LEAK_LOCALIZED",
                f"NPW localization: Δt = {loc.delta_t:+.2f} s → "
                f"{loc.x_m:,.0f} m from inlet / "
                f"{loc.x_from_outlet_m:,.0f} m from outlet "
                f"(Segment {loc.segment}, {loc.segment_range})",
                t_in=loc.t_in, t_out=loc.t_out, delta_t=loc.delta_t,
                x_m=loc.x_m, x_from_outlet_m=loc.x_from_outlet_m,
                segment=loc.segment))
            if not loc.consistency_ok:
                new_events.append(self._event(
                    t, "LOCALIZATION_WARNING",
                    "Localization consistency warning: X_from_inlet + "
                    "X_from_outlet does not equal L within tolerance — "
                    "verify arrival timing"))

        # --- severity tracking --------------------------------------------
        sev = SEVERITY_BY_TIER[global_tier]
        if self.state != NORMAL and sev is not None \
                and _SEV_RANK[sev] > _SEV_RANK[self.severity]:
            self.severity = sev
            new_events.append(self._event(
                t, "SEVERITY", f"Event severity escalated to {sev}",
                severity=sev))

        # --- LOCALIZED -> CRITICAL -> ISOLATED ----------------------------
        # isolation only after the critical condition (sustained RED),
        # never merely because the leak is localized
        if self.state in (LEAK_CONFIRMED, LOCALIZED) \
                and min(med_in, med_out) < c.critical_ratio:
            self.state = CRITICAL
            self.critical_time = t
            new_events.append(self._event(
                t, "CRITICAL_CONDITION",
                "CRITICAL condition satisfied — sustained pressure below "
                "60% of baseline (RED – Critical)", alarm=True))
            self.state = ISOLATED
            self.isolation_time = t
            self.isolated_segment = (self.localization.segment
                                     if self.localization else None)
            self.stages["respond"] = t
            seg_txt = (f"Segment {self.isolated_segment}"
                       if self.isolated_segment else "affected zone")
            new_events.append(self._event(
                t, "VIRTUAL_ISOLATION",
                f"AUTOMATIC VIRTUAL ISOLATION EXECUTED — {seg_txt} valves "
                f"closed, emergency alarm raised, control room notified",
                alarm=True, segment=self.isolated_segment))

        # --- advisory layers ----------------------------------------------
        ml = None
        if self.ml is not None:
            quiet = (s_in.phase in ("WARMUP", "MONITORING")
                     and s_out.phase in ("WARMUP", "MONITORING")
                     and not any_confirmed)
            ml = self.ml.update(t, p_in, p_out,
                                s_in.baseline, s_out.baseline,
                                training_allowed=quiet)

        forecast = None
        if self.state in ALARM_STATES:
            forecast = {
                "inlet": eta_to_thresholds(self._forecast_buf["inlet"],
                                           s_in.baseline),
                "outlet": eta_to_thresholds(self._forecast_buf["outlet"],
                                            s_out.baseline),
            }

        self.events.extend(new_events)
        return {
            "t": t,
            "inlet": _sensor_payload(s_in, health_in),
            "outlet": _sensor_payload(s_out, health_out),
            "state": self.state,
            "severity": self.severity,
            "global_tier": global_tier,
            "ml": ml,
            "leak": self._leak_payload(),
            "segments": self._segment_states(global_tier),
            "isolated": self.state == ISOLATED,
            "isolated_segment": self.isolated_segment,
            "stages": dict(self.stages),
            "forecast": forecast,
            "new_events": new_events,
        }

    # ------------------------------------------------------------------
    def _segment_states(self, global_tier: str) -> list[dict]:
        """Segment display states.

        Only the two boundary sensors physically measure pressure, so all
        segments carry the GLOBAL line health (worst sensor tier) rather
        than pretending per-segment measurements exist. The calculated
        leak segment and the isolated segment are flagged on top.
        """
        leak_seg = self.localization.segment if self.localization else None
        return [{
            "segment": i,
            "tier": global_tier,
            "leak": leak_seg == i and self.state in ALARM_STATES,
            "isolated": self.state == ISOLATED and self.isolated_segment == i,
        } for i in range(1, NUM_SEGMENTS + 1)]

    def _leak_payload(self) -> Optional[dict]:
        if self.localization_invalid:
            # expose the invalid attempt so the UI can say so explicitly
            return {"valid": False,
                    "t_in": _r(self.inlet.arrival_time),
                    "t_out": _r(self.outlet.arrival_time),
                    "delta_t": _r(self.outlet.arrival_time
                                  - self.inlet.arrival_time)
                    if None not in (self.inlet.arrival_time,
                                    self.outlet.arrival_time) else None}
        loc = self.localization
        if loc is None or self.state not in ALARM_STATES:
            return None
        return {
            "valid": True,
            "t_in": round(loc.t_in, 3),
            "t_out": round(loc.t_out, 3),
            "delta_t": round(loc.delta_t, 3),
            "x_m": round(loc.x_m, 1),
            "x_out_m": round(loc.x_from_outlet_m, 1),
            "segment": loc.segment,
            "segment_range": loc.segment_range,
            "consistency_ok": loc.consistency_ok,
            "t_event": round(loc.t_event, 3) if loc.t_event is not None else None,
        }

    def _event(self, t: float, kind: str, message: str, **data) -> dict:
        return {"t": round(t, 3), "kind": kind, "message": message, **data}


def _r(v, nd=3):
    return round(v, nd) if v is not None else None


def _sensor_payload(status, health) -> dict:
    return {
        "p": round(status.pressure, 3),
        "baseline": round(status.baseline, 3),
        "ratio": round(status.ratio, 4),
        "sigma": round(status.sigma, 4),
        "rate_sigma": round(status.rate_sigma, 4),
        "cusum": round(status.cusum, 2),
        "rate_threshold": round(status.rate_threshold, 3),  # bar/s
        "baseline_n": status.baseline_n,
        "baseline_stable": status.baseline_stable,
        "dt_nominal": round(status.dt_nominal, 4),
        "phase": status.phase,
        "arrival": status.arrival_time,
        "trigger": status.trigger_kind,
        "tier": health.tier,
        "tier_label": health.label,
    }


def _median(values) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 1.0
    mid = n // 2
    if n % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])
