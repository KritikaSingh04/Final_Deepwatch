"""Shared offline evaluation of one telemetry file through the PRODUCTION
inference path (tolerant loader + AnalyticsEngine, sample by sample).

Used by the dashboard's Batch Evaluation developer mode and by the
scripts/blind_eval.py CLI. Contains no ground truth, no expected leak
locations, and no filename-specific behaviour.
"""

from __future__ import annotations

import os

from engine.engine import AnalyticsEngine
from streaming.loader import load as load_telemetry


def evaluate_path(path: str, sheet: str | None = None) -> dict:
    """One file or one worksheet through a brand-new AnalyticsEngine.
    Sheet/file names are used for labelling only — never as detection
    inputs; the identical unmodified algorithm processes every sheet."""
    tel = load_telemetry(path, sheet=sheet)  # Status Flag quarantined here
    engine = AnalyticsEngine()
    for t, pi, po in zip(tel.times_s, tel.p_in, tel.p_out):
        engine.update(t, pi, po)

    loc = engine.localization if (engine.localization
                                  and engine.localization.valid) else None
    arrivals = [a for a in (engine.inlet.arrival_time,
                            engine.outlet.arrival_time) if a is not None]
    detect_t = engine.stages["detect"]
    latency = (round(detect_t - min(arrivals), 3)
               if detect_t is not None and arrivals else None)
    return {
        "file": os.path.basename(path),
        "sheet": tel.sheet,
        "dataset": tel.label,
        "samples": len(tel),
        "duration_s": round(tel.times_s[-1] - tel.times_s[0], 2) if len(tel) else 0.0,
        "status_flag_in_file": tel.columns["status_flag_present"],
        "leak_detected": engine.state in ("LEAK_CONFIRMED", "LOCALIZED",
                                          "CRITICAL", "ISOLATED"),
        "t_in": engine.inlet.arrival_time,
        "t_out": engine.outlet.arrival_time,
        "delta_t": round(loc.delta_t, 3) if loc else None,
        "x_m": round(loc.x_m, 1) if loc else None,
        "x_out_m": round(loc.x_from_outlet_m, 1) if loc else None,
        "segment": loc.segment if loc else None,
        "loc_invalid": engine.localization_invalid,
        "detect_time": detect_t,
        "detection_latency_s": latency,
        "critical_reached": engine.critical_time is not None,
        "critical_time": engine.critical_time,
        "isolated": engine.state == "ISOLATED",
        "isolation_time": engine.isolation_time,
        "final_state": engine.state,
        "severity": engine.severity,
    }
