"""Dual-ended localization (mentor enhancement):

    X_from_inlet  = (L - C*dt) / 2
    X_from_outlet = (L + C*dt) / 2  =  L - X_from_inlet
    t_event       = (t_in + t_out - L/C) / 2

Required scenarios: X = 0, 2,600, 5,000, 7,200 and 10,000 m — for every
one, X_from_inlet + X_from_outlet must equal L. dt keeps its sign
(positive = inlet half, ~zero = midpoint, negative = outlet half).
"""

import pytest

from engine.npw import PIPELINE_LENGTH_M, WAVE_SPEED_MS, localize
from simulator.generate import ScenarioSpec, generate
from simulator.harness import run_stream

L = PIPELINE_LENGTH_M
C = WAVE_SPEED_MS
T_EVENT = 2.0  # ground-truth origin time used to construct the arrivals

CASES = [
    # (X_ref, expected_segment)
    (0.0, 1),
    (2600.0, 2),
    (5000.0, 3),      # midpoint: dt ~ 0
    (7200.0, 4),      # outlet half: negative dt
    (10000.0, 5),     # outlet endpoint
]


@pytest.mark.parametrize("x_ref,segment", CASES)
def test_dual_ended_localization(x_ref, segment):
    t_in = T_EVENT + x_ref / C
    t_out = T_EVENT + (L - x_ref) / C
    loc = localize(t_in, t_out)

    assert loc.valid
    assert loc.consistency_ok
    assert abs(loc.x_m - x_ref) < 1e-9
    assert abs(loc.x_from_outlet_m - (L - x_ref)) < 1e-9
    # the mentor's core check: both ends always sum to the pipeline length
    assert abs(loc.x_m + loc.x_from_outlet_m - L) < 1e-9
    assert loc.segment == segment
    # engineering diagnostic recovers the constructed origin time
    assert abs(loc.t_event - T_EVENT) < 1e-9
    # sign of dt carries the location — never folded with abs()
    expected_dt = (L - 2 * x_ref) / C
    assert abs(loc.delta_t - expected_dt) < 1e-9


def test_mentor_worked_example():
    """From the request: 2,600 m from inlet / 7,400 m from outlet."""
    loc = localize(t_in=7.70, t_out=12.50)   # dt = +4.80 s
    assert abs(loc.delta_t - 4.80) < 1e-9
    assert abs(loc.x_m - 2600.0) < 1e-9
    assert abs(loc.x_from_outlet_m - 7400.0) < 1e-9
    assert loc.segment == 2
    # t_event = (7.70 + 12.50 - 10.0) / 2 = 5.10 s
    assert abs(loc.t_event - 5.10) < 1e-9


def test_endpoint_snap_keeps_pair_summing_to_L():
    loc = localize(0.0, 10.05, tolerance_m=50.0)  # snaps to the inlet end
    assert loc.valid and loc.x_m == 0.0
    assert loc.x_from_outlet_m == L
    assert abs(loc.x_m + loc.x_from_outlet_m - L) < 1e-9


def test_engine_payload_carries_both_distances():
    spec = ScenarioSpec(name="dual", leak_x_m=2600.0, leak_t_s=4.0,
                        front_drop_frac=0.10, final_frac=0.5,
                        noise_in=0.02, noise_out=0.02,
                        duration_s=30.0, seed=21)
    engine = run_stream(*generate(spec))
    loc = engine.localization
    assert loc is not None and loc.valid
    assert abs(loc.x_m + loc.x_from_outlet_m - L) < 1e-9
    assert abs(loc.x_m - 2600.0) <= 200.0
    assert abs(loc.x_from_outlet_m - 7400.0) <= 200.0
    assert loc.consistency_ok
    # the localization event announces both ends
    msg = next(e["message"] for e in engine.events
               if e["kind"] == "LEAK_LOCALIZED")
    assert "from inlet" in msg and "from outlet" in msg
    kinds = [e["kind"] for e in engine.events]
    assert "LOCALIZATION_WARNING" not in kinds
