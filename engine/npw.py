"""Negative Pressure Wave (NPW) localization math.

Implements the exact formulation given in the problem statement:

    X = (L - C * dt) / 2,   dt = t_out - t_in

with L = 10,000 m and C = 1,000 m/s fixed for all datasets. dt may be
positive (leak in the inlet half), ~zero (mid-point) or negative (leak in
the outlet half). If the computed X falls outside [0, L] the localization
is flagged INVALID (the two transients cannot belong to one leak event on
this pipeline) — it is never silently clipped.

No dataset-specific value appears anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PIPELINE_LENGTH_M = 10_000.0
WAVE_SPEED_MS = 1_000.0
NUM_SEGMENTS = 5

SEGMENT_LENGTH_M = PIPELINE_LENGTH_M / NUM_SEGMENTS  # 2 km logical segments


@dataclass(frozen=True)
class Localization:
    t_in: float                  # inlet arrival time, seconds
    t_out: float                 # outlet arrival time, seconds
    delta_t: float               # t_out - t_in, seconds (sign carries location)
    valid: bool                  # False when X falls outside [0, L]
    x_m: Optional[float]         # leak coordinate from inlet (None if invalid)
    x_from_outlet_m: Optional[float]  # dual-ended: distance from the outlet
    x_raw_m: float               # unclamped inlet coordinate, for diagnostics
    segment: Optional[int]       # 1..5 (None if invalid)
    segment_range: Optional[str] # human readable, e.g. "2 km - <4 km"
    consistency_ok: bool = True  # X_in + X_out == L within fp tolerance
    t_event: Optional[float] = None  # estimated leak-origin time (diagnostic)


def segment_for(x_m: float) -> Optional[int]:
    """Map a coordinate to the standardized 5-segment scheme.

    0 <= X < 2000 -> 1 ... 8000 <= X <= 10000 -> 5 (half-open lower
    bounds; Segment 5 includes the outlet endpoint). Out-of-range -> None.
    """
    if x_m < 0 or x_m > PIPELINE_LENGTH_M:
        return None
    if x_m == PIPELINE_LENGTH_M:
        return NUM_SEGMENTS
    return int(x_m // SEGMENT_LENGTH_M) + 1


def segment_range_label(segment: int) -> str:
    lo = (segment - 1) * SEGMENT_LENGTH_M / 1000.0
    hi = segment * SEGMENT_LENGTH_M / 1000.0
    if segment == NUM_SEGMENTS:
        return f"{lo:g} km – {hi:g} km (incl.)"
    return f"{lo:g} km – <{hi:g} km"


CONSISTENCY_TOL_M = 1e-6  # floating-point tolerance on X_in + X_out == L


def localize(t_in: float, t_out: float,
             length_m: float = PIPELINE_LENGTH_M,
             wave_speed_ms: float = WAVE_SPEED_MS,
             tolerance_m: float = 0.0) -> Localization:
    """Apply the NPW equation, dual-ended.

    X_from_inlet  = (L - C*dt) / 2
    X_from_outlet = (L + C*dt) / 2   (computed independently, then
                                      cross-checked: X_in + X_out == L)

    dt keeps its sign — positive (leak in the inlet half), ~zero
    (midpoint) and negative (outlet half) are all handled; abs(dt) is
    never taken. The estimated leak-origin time
    t_event = (t_in + t_out - L/C) / 2 is carried as an engineering
    diagnostic only and does not affect localization.

    `tolerance_m` allows a small numerical slack (e.g. half a sample of
    wave travel) before declaring the result physically invalid; a result
    inside the slack band is snapped to the nearest endpoint."""
    delta_t = t_out - t_in
    x_raw = (length_m - wave_speed_ms * delta_t) / 2.0
    x_out_raw = (length_m + wave_speed_ms * delta_t) / 2.0
    consistency_ok = abs(x_raw + x_out_raw - length_m) <= CONSISTENCY_TOL_M
    t_event = (t_in + t_out - length_m / wave_speed_ms) / 2.0
    if -tolerance_m <= x_raw <= length_m + tolerance_m:
        x = min(max(x_raw, 0.0), length_m)
        x_out = length_m - x  # displayed pair always sums to L after snapping
        seg = segment_for(x)
        return Localization(t_in=t_in, t_out=t_out, delta_t=delta_t,
                            valid=True, x_m=x, x_from_outlet_m=x_out,
                            x_raw_m=x_raw, segment=seg,
                            segment_range=segment_range_label(seg),
                            consistency_ok=consistency_ok, t_event=t_event)
    return Localization(t_in=t_in, t_out=t_out, delta_t=delta_t,
                        valid=False, x_m=None, x_from_outlet_m=None,
                        x_raw_m=x_raw, segment=None, segment_range=None,
                        consistency_ok=consistency_ok, t_event=t_event)


def localization_error_pct(x_calculated: float, x_reference: float,
                           length_m: float = PIPELINE_LENGTH_M) -> float:
    """Scoring formula from the PS: error normalised by total pipeline length."""
    return abs(x_calculated - x_reference) / length_m * 100.0
