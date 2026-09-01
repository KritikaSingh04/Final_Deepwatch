"""Validation against the Development Dataset reference values.

Jury reference (from the PS): t_in = 2.40 s, t_out = 7.60 s, dt = 5.20 s,
X = 2,400 m (Segment 2), expected state RED - Critical with automatic
virtual isolation. Detection-time tolerance: +/-100 ms; full localization
marks within 200 m. These reference values appear ONLY here, as test
assertions — never inside the engine.
"""

from engine.engine import ANOMALY_SUSPECTED, ISOLATED
from simulator.generate import dev_replica
from simulator.harness import run_stream


def _run():
    times, p_in, p_out, _flags = dev_replica()
    return run_stream(times, p_in, p_out)


def test_arrival_times_within_tolerance():
    engine = _run()
    assert engine.inlet.arrival_time is not None
    assert engine.outlet.arrival_time is not None
    assert abs(engine.inlet.arrival_time - 2.40) <= 0.100
    assert abs(engine.outlet.arrival_time - 7.60) <= 0.100


def test_localization_full_marks():
    engine = _run()
    loc = engine.localization
    assert loc is not None and loc.valid
    assert abs(loc.delta_t - 5.20) <= 0.200
    assert abs(loc.x_m - 2400.0) <= 200.0
    assert loc.segment == 2


def test_state_machine_progression():
    """Single-sensor event must NOT claim a leak; isolation must wait for
    the critical (<60%) condition, not merely localization."""
    times, p_in, p_out, _ = dev_replica()

    # stop just before the outlet transient: only the inlet has confirmed
    cut = [i for i, t in enumerate(times) if t < 7.5]
    engine = run_stream([times[i] for i in cut], [p_in[i] for i in cut],
                        [p_out[i] for i in cut])
    assert engine.state == ANOMALY_SUSPECTED
    kinds = [e["kind"] for e in engine.events]
    assert "LEAK_CONFIRMED" not in kinds
    assert "VIRTUAL_ISOLATION" not in kinds

    # full record: leak confirmed on correlation, isolation after critical
    engine = _run()
    assert engine.state == ISOLATED
    assert engine.isolated_segment == 2
    assert engine.severity == "CRITICAL"
    kinds = [e["kind"] for e in engine.events]
    for k in ["ANOMALY_SUSPECTED", "LEAK_CONFIRMED", "LEAK_LOCALIZED",
              "CRITICAL_CONDITION", "VIRTUAL_ISOLATION"]:
        assert k in kinds, f"missing {k} in {kinds}"
    # isolation strictly after localization (critical came later)
    t_localized = next(e["t"] for e in engine.events if e["kind"] == "LEAK_LOCALIZED")
    t_isolated = next(e["t"] for e in engine.events if e["kind"] == "VIRTUAL_ISOLATION")
    assert t_isolated > t_localized
    assert engine.stages["respond"] is not None
    assert engine.stages["respond"] >= engine.stages["detect"]


def test_baseline_learned_not_hardcoded():
    engine = _run()
    # learned from the data (median of the stable window), not 60/55 constants
    assert 59.5 < engine.inlet.baseline < 60.5
    assert 54.6 < engine.outlet.baseline < 55.6
    assert engine.inlet.baseline_n >= 10
    assert engine.inlet.baseline_stable
    assert engine.outlet.baseline_stable


def test_no_alarm_before_the_event():
    times, p_in, p_out, _ = dev_replica()
    engine = run_stream(
        [t for t in times if t < 2.4],
        [p for t, p in zip(times, p_in) if t < 2.4],
        [p for t, p in zip(times, p_out) if t < 2.4],
    )
    assert engine.state == "NORMAL"
    assert engine.events == []
