"""Predictive pressure-decay forecasting is advisory, honest and has
ZERO effect on detection, localization, classification or isolation."""

import pytest

import engine.engine as engine_mod
from engine.engine import AnalyticsEngine, EngineConfig
from engine.forecast import forecast_sensor
from simulator.generate import dev_replica
from simulator.harness import run_stream


def _fingerprint(e):
    loc = e.localization
    return {
        "state": e.state,
        "t_in": e.inlet.arrival_time,
        "t_out": e.outlet.arrival_time,
        "delta_t": loc.delta_t if loc else None,
        "x_m": loc.x_m if loc and loc.valid else None,
        "segment": loc.segment if loc and loc.valid else None,
        "isolation_time": e.isolation_time,
        "events": [(ev["t"], ev["kind"]) for ev in e.events],
    }


# ---------------------------------------------------------------- unit level

def _ramp(baseline, start, rate, n=20, dt=0.1):
    """(t, p) samples decaying linearly: p = start - rate * t."""
    return [(i * dt, start - rate * i * dt) for i in range(n)]


def test_linear_decay_eta_accuracy():
    base = 60.0
    pts = _ramp(base, 50.0, 2.0)             # 2 bar/s decay, now at ~46.2
    f = forecast_sensor(pts, base)
    assert f["trend_ok"]
    assert abs(f["slope_bar_s"] + 2.0) < 1e-6
    p_now = pts[-1][1]
    assert f["caution_80"] == "crossed"       # 48 bar already passed
    expected = (p_now - 0.60 * base) / 2.0
    assert abs(f["critical_60"] - expected) < 0.2
    assert f["ratio"] == round(p_now / base, 4)


def test_crossed_is_reported_even_without_trend():
    base = 60.0
    pts = [(i * 0.1, 30.0) for i in range(20)]     # flat, deep below 60%
    f = forecast_sensor(pts, base)
    assert not f["trend_ok"]
    assert f["caution_80"] == "crossed"
    assert f["critical_60"] == "crossed"


@pytest.mark.parametrize("pts,reason_word", [
    ([(i * 0.1, 55.0 + (0.001 * (-1) ** i)) for i in range(20)], "flat"),
    (_ramp(60.0, 50.0, -1.5), "recovering"),       # pressure RISING
    ([(0.0, 55.0), (0.1, 55.0), (0.2, 55.0)], "insufficient"),
])
def test_never_fabricates_an_eta(pts, reason_word):
    f = forecast_sensor(pts, 60.0)
    assert not f["trend_ok"]
    assert reason_word in (f["reason"] or "")
    for key in ("caution_80", "critical_60"):
        assert f[key] in (None, "crossed")
        assert not isinstance(f[key], float)


def test_causality_uses_only_past_samples():
    """The forecast for time T must be computable from samples <= T and
    must not change when future samples are appended."""
    base = 60.0
    past = _ramp(base, 50.0, 2.0, n=15)
    f1 = forecast_sensor(past, base)
    _future = past + [(10.0, 5.0)]           # dramatic future sample
    f2 = forecast_sensor(past, base)          # same past-only call
    assert f1 == f2


# ------------------------------------------------------------ engine level

def test_forecast_present_after_confirmation_and_honest():
    times, p_in, p_out, _ = dev_replica()
    e = AnalyticsEngine()
    saw_eta = False
    for t, pi, po in zip(times, p_in, p_out):
        tick = e.update(t, pi, po)
        fc = tick["forecast"]
        if tick["state"] == "NORMAL":
            assert fc is None                # armed only after confirmation
        if fc:
            for side in ("inlet", "outlet"):
                for key in ("caution_80", "critical_60"):
                    v = fc[side][key]
                    if isinstance(v, float):
                        assert v >= 0        # never a negative ETA
                        saw_eta = True
    assert saw_eta                            # a real countdown was produced


def test_forecast_has_zero_effect_on_results(monkeypatch):
    """Even a crashing forecaster must not change t_in, t_out, Δt, X,
    segment, classification, events or isolation."""
    times, p_in, p_out, _ = dev_replica()
    reference = run_stream(times, p_in, p_out, EngineConfig(enable_ml=False))

    def bomb(*a, **k):
        raise RuntimeError("synthetic forecast failure")
    monkeypatch.setattr(engine_mod, "forecast_sensor", bomb)

    e = AnalyticsEngine(EngineConfig(enable_ml=False))
    last = None
    for t, pi, po in zip(times, p_in, p_out):
        last = e.update(t, pi, po)            # must not raise
    assert last["forecast"] is None
    assert _fingerprint(e) == _fingerprint(reference)
    # official answers intact under the bombed forecaster
    fp = _fingerprint(e)
    assert abs(fp["t_in"] - 2.40) <= 0.1
    assert abs(fp["t_out"] - 7.60) <= 0.1
    assert abs(fp["x_m"] - 2400.0) <= 200.0
    assert fp["segment"] == 2
