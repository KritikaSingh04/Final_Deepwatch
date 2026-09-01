"""AI layer is strictly advisory and failure-safe.

Requirements under test:
* enabling/disabling the AI must not change t_in/t_out, NPW outputs,
  the event sequence, or isolation — on the dev dataset and on blind
  workbook sheets (including the BLIND_07 no-leak control);
* with too few stable samples to train, the AI reports "unavailable"
  while core detection runs unaffected;
* an AI-layer crash mid-run is swallowed, flagged unavailable, and the
  deterministic pipeline completes normally.
"""

import pytest

from engine.engine import AnalyticsEngine, EngineConfig, ISOLATED
from simulator.generate import ScenarioSpec, generate, dev_replica, make_mock_workbook
from simulator.harness import run_stream
from streaming.loader import load as load_telemetry


def _fingerprint(engine):
    loc = engine.localization
    return {
        "state": engine.state,
        "t_in": engine.inlet.arrival_time,
        "t_out": engine.outlet.arrival_time,
        "x_m": loc.x_m if loc and loc.valid else None,
        "x_out_m": loc.x_from_outlet_m if loc and loc.valid else None,
        "delta_t": loc.delta_t if loc else None,
        "segment": loc.segment if loc and loc.valid else None,
        "isolation_time": engine.isolation_time,
        "events": [(e["t"], e["kind"]) for e in engine.events],
    }


def test_ai_on_off_parity_dev_dataset():
    times, p_in, p_out, _ = dev_replica()
    with_ai = run_stream(times, p_in, p_out, EngineConfig(enable_ml=True))
    without = run_stream(times, p_in, p_out, EngineConfig(enable_ml=False))
    assert _fingerprint(with_ai) == _fingerprint(without)
    # and the official answers hold either way
    fp = _fingerprint(with_ai)
    assert abs(fp["t_in"] - 2.40) <= 0.1 and abs(fp["t_out"] - 7.60) <= 0.1
    assert abs(fp["x_m"] - 2400.0) <= 200.0


def test_ai_on_off_parity_blind_sheets(tmp_path):
    path = tmp_path / "wb.xlsx"
    make_mock_workbook(str(path))
    for sheet in ("BLIND_02", "BLIND_05", "BLIND_07"):
        tel = load_telemetry(str(path), sheet=sheet)
        a = run_stream(tel.times_s, tel.p_in, tel.p_out,
                       EngineConfig(enable_ml=True))
        b = run_stream(tel.times_s, tel.p_in, tel.p_out,
                       EngineConfig(enable_ml=False))
        assert _fingerprint(a) == _fingerprint(b), sheet
    # BLIND_07 stays NO LEAK regardless of the AI layer
    tel = load_telemetry(str(path), sheet="BLIND_07")
    quiet = run_stream(tel.times_s, tel.p_in, tel.p_out,
                       EngineConfig(enable_ml=True))
    assert quiet.state in ("NORMAL", "ANOMALY_SUSPECTED")
    assert quiet.isolation_time is None


def test_ai_unavailable_when_training_data_insufficient():
    """Leak arrives right after warmup — fewer than MIN_TRAIN stable
    windows exist. The AI must flag unavailable; detection, localization
    and isolation must proceed exactly as normal."""
    # inlet front at t = 1.7 s: only ~9 stable feature windows exist
    # before the candidate opens — below the trainer's minimum of 15
    spec = ScenarioSpec(name="early", leak_x_m=1700.0, leak_t_s=0.0,
                        front_drop_frac=0.12, final_frac=0.45,
                        noise_in=0.02, noise_out=0.02, duration_s=30, seed=8)
    times, p_in, p_out = generate(spec)
    engine = AnalyticsEngine()
    last_ml = None
    for t, pi, po in zip(times, p_in, p_out):
        last_ml = engine.update(t, pi, po)["ml"]
    assert last_ml == {"unavailable": True}
    assert engine.state == ISOLATED
    assert engine.localization.valid
    assert abs(engine.localization.x_m - 1700.0) <= 200.0


def test_ai_crash_is_contained():
    """An exception inside the AI layer must never break a tick or alter
    the deterministic results."""
    times, p_in, p_out, _ = dev_replica()
    engine = AnalyticsEngine()

    class Bomb:
        def update(self, *a, **k):
            raise RuntimeError("synthetic AI failure")
    engine.ml = Bomb()

    last = None
    for t, pi, po in zip(times, p_in, p_out):
        last = engine.update(t, pi, po)          # must not raise
    assert last["ml"] == {"unavailable": True}
    assert engine.ml is None and engine.ml_unavailable

    reference = run_stream(times, p_in, p_out, EngineConfig(enable_ml=False))
    assert _fingerprint(engine) == _fingerprint(reference)


def test_ai_features_are_scale_free():
    """Feature extraction is normalised by baseline: same shape at a
    different absolute pressure gives (near-)identical features."""
    from engine.mlscore import OnlineAnomalyScorer
    lo = OnlineAnomalyScorer._features([60.0, 60.01, 59.99, 60.02,
                                        60.0, 59.98, 60.01, 60.0], 60.0)
    hi = OnlineAnomalyScorer._features([v * 10 for v in
                                        [60.0, 60.01, 59.99, 60.02,
                                         60.0, 59.98, 60.01, 60.0]], 600.0)
    assert len(lo) == 4                      # slope, variance, drop, accel
    for a, b in zip(lo, hi):
        assert abs(a - b) < 1e-12
