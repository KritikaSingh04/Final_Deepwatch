"""Per-sensor transient detector.

Deterministic primary detector combining, per the design spec:

* rate of pressure change (bar/s, using ACTUAL timestamp spacing),
* deviation from a robust baseline,
* persistence over a confirmation window,
* noise-adaptive thresholds (multiples of measured MAD-sigma).

Nothing is dataset-specific; no absolute pressure threshold is used.

Baseline estimation
-------------------
The baseline is learned independently per sensor from an initial STABLE
window: the detector waits until the most recent `warmup_seconds` of
telemetry passes a stability check (bounded trend and bounded outliers
relative to its own MAD-sigma) before locking the baseline (median) and
noise floor. If stability is not reached within `warmup_max_seconds` the
best available window is accepted and flagged provisional. While
conditions remain normal, a slow EWMA tracks gradual operating drift; the
baseline FREEZES the instant a transient candidate opens and stays frozen
once an arrival is confirmed (until engine reset).

Detection
---------
Two paths can raise a transient candidate:
  1. rate detector  — dP/dt (bar/s, from real timestamp gaps) beyond
     k_rate x the measured rate-noise catches the sharp NPW front;
  2. CUSUM detector — one-sided cumulative sum of the normalised negative
     residual catches gentler fronts under heavy noise, back-dating the
     arrival to the change point where the statistic last left zero.
A sustained-deviation check over the following confirmation window
(time-based, >= 3 samples) must then pass or the candidate is revoked —
this rejects spikes and short nuisance disturbances.

Arrival refinement: the reported arrival is the first sample carrying a
significant fraction of the confirmed front amplitude and clearing the
noise floor — the physical NPW front, not any precursor sag.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


def _median(values) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _mad_sigma(values, floor: float) -> float:
    """Robust sigma estimate: 1.4826 x median absolute deviation."""
    if len(values) < 5:
        return floor
    med = _median(values)
    mad = _median([abs(v - med) for v in values])
    return max(1.4826 * mad, floor)


def _slope(points) -> float:
    """Least-squares slope of (t, p) points, units per second."""
    n = len(points)
    if n < 2:
        return 0.0
    tbar = sum(t for t, _ in points) / n
    pbar = sum(p for _, p in points) / n
    den = sum((t - tbar) ** 2 for t, _ in points)
    if den == 0:
        return 0.0
    return sum((t - tbar) * (p - pbar) for t, p in points) / den


@dataclass
class DetectorConfig:
    warmup_seconds: float = 1.5      # minimum stable-window span
    warmup_max_seconds: float = 6.0  # give up waiting for stability after this
    min_warmup_samples: int = 10
    stability_slope_k: float = 3.0   # |trend over window| <= k * sigma
    stability_range_k: float = 6.0   # max |residual| <= k * sigma
    noise_window: int = 60           # samples kept for noise estimation
    baseline_alpha: float = 0.02     # slow EWMA tracking during normal ops
    sigma_floor: float = 0.01        # bar; guards zero-noise division
    k_rate: float = 6.0              # rate threshold in rate-noise sigmas
    rate_floor_bar: float = 0.15     # absolute floor per nominal sample (-> bar/s)
    cusum_slack: float = 0.5         # slack (sigmas) absorbed before accumulating
    cusum_threshold: float = 10.0    # accumulated sigmas required to trigger
    confirm_window_s: float = 0.5    # sustained-deviation confirmation span
    min_confirm_samples: int = 3
    k_confirm: float = 4.0           # required mean deviation in noise sigmas
    confirm_frac: float = 0.003      # ... or as a fraction of baseline
    front_fraction: float = 0.30     # arrival refinement: share of front amplitude
    k_arrival: float = 5.0           # arrival must also clear this many sigmas
    recent_window: int = 400         # raw samples kept for arrival refinement


# phases
WARMUP, MONITORING, CANDIDATE, CONFIRMED = "WARMUP", "MONITORING", "CANDIDATE", "CONFIRMED"


@dataclass
class SensorStatus:
    phase: str
    pressure: float
    baseline: float
    ratio: float
    sigma: float
    rate_sigma: float            # bar/s
    rate_threshold: float        # bar/s
    cusum: float
    baseline_n: int              # samples the baseline was learned from
    baseline_stable: bool
    dt_nominal: float            # measured sampling interval, seconds
    arrival_time: Optional[float]
    trigger_kind: Optional[str]  # 'rate' | 'cusum'


@dataclass
class SensorDetector:
    name: str
    config: DetectorConfig = field(default_factory=DetectorConfig)

    def __post_init__(self):
        c = self.config
        self.phase = WARMUP
        self.baseline: Optional[float] = None
        self.baseline_n = 0
        self.baseline_stable = False
        self.sigma = c.sigma_floor
        self.rate_sigma = c.sigma_floor
        self.dt_nominal = 0.1  # provisional until measured from timestamps
        self._warmup: list[tuple[float, float]] = []
        self._gaps: deque[float] = deque(maxlen=40)
        self._residuals: deque[float] = deque(maxlen=c.noise_window)
        self._rates: deque[float] = deque(maxlen=c.noise_window)
        self._recent: deque[tuple[float, float]] = deque(maxlen=c.recent_window)
        self._prev: Optional[tuple[float, float]] = None  # (t, p)
        self._cusum = 0.0
        self._cusum_start: Optional[float] = None
        # candidate bookkeeping
        self._cand_time: Optional[float] = None   # arrival estimate
        self._cand_open: Optional[float] = None   # trigger time
        self._cand_kind: Optional[str] = None
        self._cand_count = 0
        # result
        self.arrival_time: Optional[float] = None
        self.trigger_kind: Optional[str] = None

    # ------------------------------------------------------------------
    def update(self, t: float, p: float) -> SensorStatus:
        if self._prev is not None:
            gap = t - self._prev[0]
            if gap > 0:
                self._gaps.append(gap)
                self.dt_nominal = _median(self._gaps)

        self._recent.append((t, p))
        if self.phase == WARMUP:
            self._handle_warmup(t, p)
        elif self.phase == MONITORING:
            self._handle_monitoring(t, p)
        elif self.phase == CANDIDATE:
            self._handle_candidate(t, p)
        # CONFIRMED: nothing further to detect; baseline stays frozen

        self._prev = (t, p)
        baseline = self.baseline if self.baseline is not None else p
        ratio = p / baseline if baseline > 0 else 1.0
        return SensorStatus(
            phase=self.phase,
            pressure=p,
            baseline=baseline,
            ratio=ratio,
            sigma=self.sigma,
            rate_sigma=self.rate_sigma,
            rate_threshold=self._rate_threshold(),
            cusum=self._cusum,
            baseline_n=self.baseline_n,
            baseline_stable=self.baseline_stable,
            dt_nominal=self.dt_nominal,
            arrival_time=self.arrival_time,
            trigger_kind=self.trigger_kind,
        )

    # ------------------------------------------------------------------
    def _rate_threshold(self) -> float:
        c = self.config
        floor = c.rate_floor_bar / max(self.dt_nominal, 1e-3)
        return max(c.k_rate * self.rate_sigma, floor)

    def _handle_warmup(self, t: float, p: float) -> None:
        c = self.config
        self._warmup.append((t, p))
        t0 = self._warmup[0][0]
        span = t - t0
        if len(self._warmup) < c.min_warmup_samples or span < c.warmup_seconds:
            return
        # evaluate the most recent warmup_seconds span for stability
        window = [(tw, pw) for tw, pw in self._warmup if tw >= t - c.warmup_seconds]
        if len(window) < c.min_warmup_samples:
            window = self._warmup[-c.min_warmup_samples:]
        med = _median([pw for _, pw in window])
        resid = [pw - med for _, pw in window]
        sigma = _mad_sigma(resid, c.sigma_floor)
        trend = abs(_slope(window)) * (window[-1][0] - window[0][0])
        stable = (trend <= c.stability_slope_k * sigma
                  and max(abs(r) for r in resid) <= c.stability_range_k * sigma)
        if stable or span >= c.warmup_max_seconds:
            self._lock_baseline(window, med, sigma, stable)

    def _lock_baseline(self, window, med, sigma, stable) -> None:
        c = self.config
        self.baseline = med
        self.sigma = sigma
        self.baseline_n = len(window)
        self.baseline_stable = stable
        rates = []
        for i in range(1, len(window)):
            dt = window[i][0] - window[i - 1][0]
            if dt > 0:
                rates.append((window[i][1] - window[i - 1][1]) / dt)
        self.rate_sigma = _mad_sigma(rates, c.sigma_floor)
        self._residuals.extend(pw - med for _, pw in window)
        self._rates.extend(rates)
        self.phase = MONITORING

    def _handle_monitoring(self, t: float, p: float) -> None:
        c = self.config
        resid = p - self.baseline
        dt = t - self._prev[0] if self._prev else self.dt_nominal
        rate = (p - self._prev[1]) / dt if (self._prev and dt > 0) else 0.0

        # --- rate detector: sharp negative front (bar/s) ---
        if rate < -self._rate_threshold():
            self._open_candidate(arrival=t, open_t=t, kind="rate")
            return

        # --- CUSUM detector: sustained gentle decline ---
        z = (-resid) / self.sigma  # positive when pressure below baseline
        new_cusum = max(0.0, self._cusum + z - c.cusum_slack)
        if new_cusum > 0.0 and self._cusum == 0.0:
            self._cusum_start = t
        if new_cusum == 0.0:
            self._cusum_start = None
        self._cusum = new_cusum
        if self._cusum > c.cusum_threshold:
            arrival = self._cusum_start if self._cusum_start is not None else t
            self._open_candidate(arrival=arrival, open_t=t, kind="cusum")
            return

        # --- normal sample: update noise stats and slow baseline track ---
        self._residuals.append(resid)
        self._rates.append(rate)
        self.sigma = _mad_sigma(self._residuals, c.sigma_floor)
        self.rate_sigma = _mad_sigma(self._rates, c.sigma_floor)
        if abs(resid) <= 3.0 * self.sigma:
            self.baseline += c.baseline_alpha * resid

    def _open_candidate(self, arrival: float, open_t: float, kind: str) -> None:
        # baseline freezes here: no EWMA updates while a candidate is open
        self.phase = CANDIDATE
        self._cand_time = arrival
        self._cand_open = open_t
        self._cand_kind = kind
        self._cand_count = 0

    def _handle_candidate(self, t: float, p: float) -> None:
        c = self.config
        self._cand_count += 1
        if (t - self._cand_open) < c.confirm_window_s \
                or self._cand_count < c.min_confirm_samples:
            return
        window = [(tw, pw) for tw, pw in self._recent if tw >= self._cand_open]
        devs = [self.baseline - pw for _, pw in window]
        mean_dev = sum(devs) / len(devs)
        required = max(c.k_confirm * self.sigma, c.confirm_frac * self.baseline)
        if mean_dev > required and devs[-1] > 0:
            self.phase = CONFIRMED
            self.trigger_kind = self._cand_kind
            self.arrival_time = self._refine_arrival(front_amplitude=mean_dev)
        else:
            # revoke: spike / short nuisance disturbance — resume monitoring
            self.phase = MONITORING
            self._cand_time = None
            self._cand_open = None
            self._cand_kind = None
            self._cand_count = 0
            self._cusum = 0.0
            self._cusum_start = None

    def _refine_arrival(self, front_amplitude: float) -> float:
        """First sample carrying a significant fraction of the front.

        Threshold adapts to both the confirmed front amplitude and the
        measured noise floor, so it is scale-free across datasets."""
        c = self.config
        threshold = max(c.k_arrival * self.sigma,
                        c.front_fraction * front_amplitude)
        for tw, pw in self._recent:
            if tw < self._cand_time:
                continue
            if (self.baseline - pw) > threshold:
                return tw
        return self._cand_time
