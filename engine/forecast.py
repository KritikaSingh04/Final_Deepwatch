"""Predictive time-to-critical forecasting.

Once a leak is confirmed, the recent pressure trend at each sensor is fit
with a least-squares line and projected forward to estimate when the
pressure will cross the Caution (80%) and Critical (60%) health
thresholds. Purely trend-based — no dataset-specific assumptions.
"""

from __future__ import annotations

from typing import Optional

THRESHOLDS = {"caution_80": 0.80, "critical_60": 0.60}
MIN_SAMPLES = 8
MAX_HORIZON_S = 3600.0


def eta_to_thresholds(samples, baseline: float) -> dict:
    """samples: iterable of (t, p). Returns {name: seconds_from_now|0|None}.

    0 means the threshold is already crossed; None means no crossing is
    projected (trend flat or rising, or not enough data).
    """
    pts = list(samples)
    out: dict[str, Optional[float]] = {k: None for k in THRESHOLDS}
    if len(pts) < MIN_SAMPLES or baseline <= 0:
        return out

    ts = [p[0] for p in pts]
    ps = [p[1] for p in pts]
    n = len(pts)
    tbar = sum(ts) / n
    pbar = sum(ps) / n
    den = sum((t - tbar) ** 2 for t in ts)
    if den == 0:
        return out
    slope = sum((t - tbar) * (p - pbar) for t, p in pts) / den  # bar/s
    t_now, p_now = ts[-1], ps[-1]

    for name, frac in THRESHOLDS.items():
        target = frac * baseline
        if p_now <= target:
            out[name] = 0.0
        elif slope < -1e-6:
            eta = (p_now - target) / (-slope)
            out[name] = round(eta, 1) if eta <= MAX_HORIZON_S else None
    return out
