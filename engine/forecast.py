"""Predictive time-to-critical forecasting (advisory).

Once a leak is CONFIRMED, each sensor's recent pressure-decay trend is
estimated with a short ROBUST regression — Theil–Sen (median of pairwise
slopes) over the trailing window — and projected forward to the existing
health thresholds:

    80% of baseline -> DEGRADED
    60% of baseline -> CRITICAL

Strictly causal: only samples observed up to the current timestamp enter
the window. Strictly honest: an ETA is produced ONLY when the trend is a
consistent decay (median slope negative and >= 70% of pairwise slopes
negative); flat, recovering, unstable or insufficient data reports
"forecast unavailable" instead of fabricating a number. A threshold the
pressure has ALREADY crossed is reported as "crossed" — that is a fact
about the current sample, not a forecast.

Trend-based estimate — advisory only. Forecasting never triggers
isolation or any state transition; the deterministic state machine
remains solely responsible for response.
"""

from __future__ import annotations

from typing import Optional, Union

THRESHOLDS = {"caution_80": 0.80, "critical_60": 0.60}
MIN_SAMPLES = 8
MAX_HORIZON_S = 3600.0
NEG_FRACTION_REQUIRED = 0.70   # pairwise-slope sign consistency for a real decay

Eta = Union[float, str, None]  # seconds | "crossed" | None (unavailable)


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


def forecast_sensor(samples, baseline: float) -> dict:
    """samples: iterable of (t, p), oldest first, all in the past.

    Returns:
      {"ratio":       current pressure / baseline,
       "slope_bar_s": robust decay rate (None when no consistent trend),
       "trend_ok":    bool,
       "reason":      None | short text for the unavailable case,
       "caution_80":  seconds | "crossed" | None,
       "critical_60": seconds | "crossed" | None}
    """
    pts = list(samples)
    out: dict = {"ratio": None, "slope_bar_s": None, "trend_ok": False,
                 "reason": None,
                 "caution_80": None, "critical_60": None}
    if baseline <= 0:
        out["reason"] = "no baseline"
        return out
    if len(pts) < MIN_SAMPLES:
        out["reason"] = "insufficient data"
        return out

    t_now, p_now = pts[-1]
    out["ratio"] = round(p_now / baseline, 4)

    # facts first: thresholds already crossed are reported regardless of trend
    for name, frac in THRESHOLDS.items():
        if p_now <= frac * baseline:
            out[name] = "crossed"

    # Theil–Sen: median of all pairwise slopes (robust to spikes/outliers)
    slopes = []
    for i in range(len(pts)):
        ti, pi = pts[i]
        for j in range(i + 1, len(pts)):
            tj, pj = pts[j]
            if tj > ti:
                slopes.append((pj - pi) / (tj - ti))
    if not slopes:
        out["reason"] = "insufficient data"
        return out
    med_slope = _median(slopes)
    neg_frac = sum(s < 0 for s in slopes) / len(slopes)

    if med_slope >= -1e-6 or neg_frac < NEG_FRACTION_REQUIRED:
        # flat, recovering, or inconsistent — never fabricate an ETA
        out["reason"] = ("trend recovering" if med_slope > 1e-6
                         else "trend flat or unstable")
        return out

    out["trend_ok"] = True
    out["slope_bar_s"] = round(med_slope, 4)
    for name, frac in THRESHOLDS.items():
        if out[name] == "crossed":
            continue
        eta = (p_now - frac * baseline) / (-med_slope)
        out[name] = round(eta, 1) if eta <= MAX_HORIZON_S else None
    return out
