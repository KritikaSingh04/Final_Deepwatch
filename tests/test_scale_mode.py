"""Engineering / Scale mode: parameterized L, C and dynamic segments.

Competition Mode (defaults) must keep reproducing the official answers —
that is covered by the dev-dataset and workbook suites; here we verify the
same unmodified analytics at 20 / 50 / 100 km, dynamic segment mapping
(including a remainder segment), positive & negative delta_t at scale, and
the invalid-timing condition against the configured pipeline.
"""

import pytest

from engine.engine import AnalyticsEngine, EngineConfig, ISOLATED
from engine.npw import (PIPELINE_LENGTH_M, WAVE_SPEED_MS, SEGMENT_LENGTH_M,
                        localize, num_segments_for, segment_bounds,
                        segment_for)
from simulator.generate import ScenarioSpec, generate
from simulator.harness import run_stream


def test_competition_defaults_locked():
    cfg = EngineConfig()
    assert cfg.length_m == PIPELINE_LENGTH_M == 10_000.0
    assert cfg.wave_speed_ms == WAVE_SPEED_MS == 1_000.0
    assert cfg.segment_len_m == SEGMENT_LENGTH_M == 2_000.0
    assert num_segments_for() == 5
    # official reference still reproduced by the default-parameter path
    loc = localize(2.40, 7.60)
    assert loc.valid and abs(loc.x_m - 2400.0) < 1e-9 and loc.segment == 2


def test_dynamic_segments_examples_from_spec():
    # 10 km pipeline, 2 km segments -> S1 0–2 … S5 8–10
    assert segment_bounds(10_000, 2_000) == [
        (0, 2000), (2000, 4000), (4000, 6000), (6000, 8000), (8000, 10_000)]
    # 100 km pipeline, 20 km segments -> S1 0–20 … S5 80–100
    assert segment_bounds(100_000, 20_000) == [
        (0, 20_000), (20_000, 40_000), (40_000, 60_000),
        (60_000, 80_000), (80_000, 100_000)]
    assert segment_for(85_000, 100_000, 20_000) == 5
    assert segment_for(0, 100_000, 20_000) == 1
    assert segment_for(100_000, 100_000, 20_000) == 5


def test_final_segment_absorbs_remainder():
    # 10 km pipeline with 3 km segments -> 4 segments, last one 9–10 km
    assert num_segments_for(10_000, 3_000) == 4
    bounds = segment_bounds(10_000, 3_000)
    assert bounds[-1] == (9_000, 10_000)
    assert segment_for(9_500, 10_000, 3_000) == 4
    assert segment_for(8_999, 10_000, 3_000) == 3
    assert segment_for(10_000, 10_000, 3_000) == 4


@pytest.mark.parametrize("length_km,frac", [
    (20, 0.20),    # leak in inlet half  -> positive delta_t
    (50, 0.50),    # midpoint            -> delta_t ~ 0
    (100, 0.80),   # leak in outlet half -> negative delta_t
])
def test_engineering_mode_end_to_end(length_km, frac):
    L = length_km * 1000.0
    seg = L / 5.0
    x_ref = frac * L
    spec = ScenarioSpec(
        name=f"scale_{length_km}km", length_m=L, leak_x_m=x_ref,
        leak_t_s=2.0, duration_s=2.0 + L / 1000.0 + 40.0,
        front_drop_frac=0.12, final_frac=0.45, decay_tau_s=3.0,
        noise_in=0.05, noise_out=0.05, seed=int(L) % 89 + 3)
    times, p_in, p_out = generate(spec)
    engine = run_stream(times, p_in, p_out,
                        EngineConfig(length_m=L, segment_len_m=seg))
    loc = engine.localization
    assert loc is not None and loc.valid, f"no localization at {length_km} km"
    # one 100 ms sample of front latency => at most C*dt/2 = 50 m of error
    assert abs(loc.x_m - x_ref) <= 200.0
    assert abs(loc.x_m + loc.x_from_outlet_m - L) < 1e-6
    expected_dt = (L - 2 * x_ref) / 1000.0
    assert abs(loc.delta_t - expected_dt) <= 0.2
    expected_seg = segment_for(x_ref, L, seg)
    assert loc.segment == expected_seg
    assert engine.state == ISOLATED


def test_invalid_timing_scales_with_configured_pipeline():
    # |dt| = 30 s exceeds L/C = 20 s on a 20 km line -> INVALID, not clamped
    bad = localize(0.0, 30.0, length_m=20_000, wave_speed_ms=1000,
                   segment_len_m=4_000)
    assert not bad.valid and bad.x_m is None
    # ... but the same dt is perfectly fine on a 100 km line
    ok = localize(0.0, 30.0, length_m=100_000, wave_speed_ms=1000,
                  segment_len_m=20_000)
    assert ok.valid and abs(ok.x_m - 35_000) < 1e-9 and ok.segment == 2


def test_engine_flags_invalid_timing_in_engineering_mode():
    """Two real-looking fronts whose spacing is impossible for a 20 km
    line must yield LOCALIZATION_INVALID, no leak confirmation."""
    import random
    rng = random.Random(9)
    L = 20_000.0
    times, p_in, p_out = [], [], []
    for i in range(700):
        t = round(i * 0.1, 3)
        times.append(t)
        p_in.append(round(60 + rng.gauss(0, 0.02) - (14 if t >= 3.0 else 0), 3))
        p_out.append(round(55 + rng.gauss(0, 0.02) - (13 if t >= 40.0 else 0), 3))
    engine = run_stream(times, p_in, p_out,
                        EngineConfig(length_m=L, segment_len_m=4_000))
    assert engine.localization_invalid
    kinds = [e["kind"] for e in engine.events]
    assert "LOCALIZATION_INVALID" in kinds
    assert "LEAK_CONFIRMED" not in kinds
