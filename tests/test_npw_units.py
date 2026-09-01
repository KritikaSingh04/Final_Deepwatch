"""Unit tests for the NPW math, segment mapping and health tiers."""

from engine.npw import localize, segment_for, localization_error_pct
from engine.health import classify


def test_npw_formula_matches_ps():
    # X = (L - C*dt)/2 with dt = t_out - t_in
    loc = localize(2.40, 7.60)
    assert loc.valid
    assert abs(loc.delta_t - 5.20) < 1e-9
    assert abs(loc.x_m - 2400.0) < 1e-9
    assert loc.segment == 2


def test_npw_negative_dt_outlet_half():
    loc = localize(7.60, 2.40)  # leak nearer the outlet
    assert loc.valid
    assert abs(loc.x_m - 7600.0) < 1e-9
    assert loc.segment == 4


def test_npw_midpoint_zero_dt():
    loc = localize(5.0, 5.0)
    assert loc.valid
    assert abs(loc.x_m - 5000.0) < 1e-9
    assert loc.segment == 3


def test_npw_out_of_bounds_is_flagged_not_clipped():
    too_late = localize(0.0, 12.0)      # dt = +12 s -> X = -1000 m
    assert not too_late.valid
    assert too_late.x_m is None and too_late.segment is None
    assert abs(too_late.x_raw_m - (-1000.0)) < 1e-9

    too_early = localize(12.0, 0.0)     # dt = -12 s -> X = 11000 m
    assert not too_early.valid
    assert too_early.x_m is None

    # endpoints are valid
    assert localize(0.0, 10.0).valid and localize(0.0, 10.0).x_m == 0.0
    assert localize(10.0, 0.0).valid and localize(10.0, 0.0).x_m == 10000.0

    # a small tolerance snaps near-endpoint results instead of rejecting
    snapped = localize(0.0, 10.05, tolerance_m=50.0)
    assert snapped.valid and snapped.x_m == 0.0


def test_segment_mapping_per_spec():
    assert segment_for(0.0) == 1
    assert segment_for(1999.9) == 1
    assert segment_for(2000.0) == 2       # 2000 <= X < 4000 -> Segment 2
    assert segment_for(3999.9) == 2
    assert segment_for(4000.0) == 3
    assert segment_for(6000.0) == 4
    assert segment_for(8000.0) == 5
    assert segment_for(10000.0) == 5      # 8000 <= X <= 10000 -> Segment 5
    assert segment_for(-0.1) is None
    assert segment_for(10000.1) is None


def test_error_pct_uses_total_length():
    assert abs(localization_error_pct(2600.0, 2400.0) - 2.0) < 1e-9


def test_health_tier_boundaries():
    assert classify(0.99).tier == "GREEN"
    assert classify(0.95).tier == "GREEN"     # >= 95%
    assert classify(0.9499).tier == "YELLOW"
    assert classify(0.80).tier == "YELLOW"    # >= 80%
    assert classify(0.7999).tier == "ORANGE"
    assert classify(0.60).tier == "ORANGE"    # >= 60%
    assert classify(0.5999).tier == "RED"
