"""Negative Pressure Wave (NPW) localization math — parameterized.

    delta_t       = t_out - t_in            (sign carries location)
    X_from_inlet  = (L - C * delta_t) / 2
    X_from_outlet = L - X_from_inlet        (cross-checked independently)

COMPETITION MODE (default, locked): L = 10,000 m, C = 1,000 m/s,
segment size 2,000 m → 5 logical segments. These module constants are the
official values used for all blind datasets.

ENGINEERING / SCALE MODE: any L, C and desired segment size may be passed
explicitly — segment boundaries are generated dynamically
(ceil(L / segment_len) segments; if L is not evenly divisible the final
segment carries the remainder).

Physical timing validation: |delta_t| <= L / C (equivalently X inside
[0, L]). A violation is flagged INVALID — never silently clamped.
No dataset-specific value appears anywhere in this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# --- competition parameters (locked; used for official blind datasets) ---
PIPELINE_LENGTH_M = 10_000.0
WAVE_SPEED_MS = 1_000.0
SEGMENT_LENGTH_M = 2_000.0
NUM_SEGMENTS = 5


@dataclass(frozen=True)
class Localization:
    t_in: float                  # inlet arrival time, seconds
    t_out: float                 # outlet arrival time, seconds
    delta_t: float               # t_out - t_in, seconds (sign carries location)
    valid: bool                  # False when X falls outside [0, L]
    x_m: Optional[float]         # leak coordinate from inlet (None if invalid)
    x_from_outlet_m: Optional[float]  # dual-ended: distance from the outlet
    x_raw_m: float               # unclamped inlet coordinate, for diagnostics
    segment: Optional[int]       # 1..N (None if invalid)
    segment_range: Optional[str] # human readable, e.g. "2 km - <4 km"
    consistency_ok: bool = True  # X_in + X_out == L within fp tolerance
    t_event: Optional[float] = None  # estimated leak-origin time (diagnostic)


def num_segments_for(length_m: float = PIPELINE_LENGTH_M,
                     segment_len_m: float = SEGMENT_LENGTH_M) -> int:
    """Dynamic segment count: ceil(L / segment_len), minimum 1."""
    if segment_len_m <= 0 or length_m <= 0:
        return 1
    return max(1, math.ceil(round(length_m / segment_len_m, 9)))


def segment_bounds(length_m: float = PIPELINE_LENGTH_M,
                   segment_len_m: float = SEGMENT_LENGTH_M) -> list[tuple[float, float]]:
    """[(lo, hi), ...] per segment; the final segment absorbs any remainder
    (its hi is exactly L)."""
    n = num_segments_for(length_m, segment_len_m)
    bounds = []
    for i in range(n):
        lo = i * segment_len_m
        hi = length_m if i == n - 1 else min((i + 1) * segment_len_m, length_m)
        bounds.append((lo, hi))
    return bounds


def segment_for(x_m: float,
                length_m: float = PIPELINE_LENGTH_M,
                segment_len_m: float = SEGMENT_LENGTH_M) -> Optional[int]:
    """Map a coordinate to the dynamic segment scheme (half-open lower
    bounds; the final segment includes the outlet endpoint at L).
    Out-of-range -> None."""
    if x_m < 0 or x_m > length_m:
        return None
    n = num_segments_for(length_m, segment_len_m)
    if x_m >= length_m:
        return n
    # 1e-6 m epsilon: a coordinate that is analytically ON a boundary but
    # lands a few ulps below it still classifies into the upper segment
    return min(int((x_m + 1e-6) // segment_len_m), n - 1) + 1


def segment_range_label(segment: int,
                        length_m: float = PIPELINE_LENGTH_M,
                        segment_len_m: float = SEGMENT_LENGTH_M) -> str:
    lo, hi = segment_bounds(length_m, segment_len_m)[segment - 1]
    n = num_segments_for(length_m, segment_len_m)
    lo_km, hi_km = lo / 1000.0, hi / 1000.0
    if segment == n:
        return f"{lo_km:g} km – {hi_km:g} km (incl.)"
    return f"{lo_km:g} km – <{hi_km:g} km"


CONSISTENCY_TOL_M = 1e-6  # floating-point tolerance on X_in + X_out == L


def localize(t_in: float, t_out: float,
             length_m: float = PIPELINE_LENGTH_M,
             wave_speed_ms: float = WAVE_SPEED_MS,
             segment_len_m: float = SEGMENT_LENGTH_M,
             tolerance_m: float = 0.0) -> Localization:
    """Apply the NPW equation, dual-ended, for the ACTIVE configuration.

    Physical timing validation |dt| <= L/C is enforced via the X bounds:
    a violation is flagged invalid (timing inconsistent with the
    configured pipeline) — never clamped. `tolerance_m` allows a small
    numerical slack (e.g. half a sample of wave travel) before declaring
    invalid; a result inside the slack band is snapped to the nearest
    endpoint."""
    delta_t = t_out - t_in
    x_raw = (length_m - wave_speed_ms * delta_t) / 2.0
    x_out_raw = (length_m + wave_speed_ms * delta_t) / 2.0
    consistency_ok = abs(x_raw + x_out_raw - length_m) <= CONSISTENCY_TOL_M
    t_event = (t_in + t_out - length_m / wave_speed_ms) / 2.0
    if -tolerance_m <= x_raw <= length_m + tolerance_m:
        x = min(max(x_raw, 0.0), length_m)
        x_out = length_m - x  # displayed pair always sums to L after snapping
        seg = segment_for(x, length_m, segment_len_m)
        return Localization(t_in=t_in, t_out=t_out, delta_t=delta_t,
                            valid=True, x_m=x, x_from_outlet_m=x_out,
                            x_raw_m=x_raw, segment=seg,
                            segment_range=segment_range_label(
                                seg, length_m, segment_len_m),
                            consistency_ok=consistency_ok, t_event=t_event)
    return Localization(t_in=t_in, t_out=t_out, delta_t=delta_t,
                        valid=False, x_m=None, x_from_outlet_m=None,
                        x_raw_m=x_raw, segment=None, segment_range=None,
                        consistency_ok=consistency_ok, t_event=t_event)


def localization_error_pct(x_calculated: float, x_reference: float,
                           length_m: float = PIPELINE_LENGTH_M) -> float:
    """Scoring formula from the PS: error normalised by total pipeline length."""
    return abs(x_calculated - x_reference) / length_m * 100.0
