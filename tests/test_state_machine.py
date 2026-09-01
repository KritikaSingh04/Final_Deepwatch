"""State-machine and robustness behaviours required by the design spec:
single-sensor gating, correlation checks, isolation gating, baseline
stability, Status-Flag independence, and timestamp-derived sampling."""

import csv
import random

from engine.engine import (AnalyticsEngine, ANOMALY_SUSPECTED, LOCALIZED,
                           ISOLATED)
from simulator.generate import ScenarioSpec, generate, dev_replica
from simulator.harness import run_stream
from streaming.loader import load as load_telemetry


def _flat(base, n, dt=0.1, noise=0.02, seed=1):
    rng = random.Random(seed)
    return [round(base + rng.gauss(0, noise), 3) for _ in range(n)]


def test_single_sensor_event_never_confirms_leak():
    """A deep drop seen by ONE station only stays ANOMALY_SUSPECTED."""
    n = 300
    times = [round(i * 0.1, 3) for i in range(n)]
    p_in = _flat(60.0, n)
    p_out = _flat(55.0, n, seed=2)
    for i, t in enumerate(times):          # inlet crashes at t=5s, outlet flat
        if t >= 5.0:
            p_in[i] = round(40.0 + random.Random(i).gauss(0, 0.02), 3)
    engine = run_stream(times, p_in, p_out)
    assert engine.state == ANOMALY_SUSPECTED
    kinds = [e["kind"] for e in engine.events]
    assert "LEAK_CONFIRMED" not in kinds
    assert "VIRTUAL_ISOLATION" not in kinds


def test_uncorrelated_transients_flag_invalid_localization():
    """Two arrivals whose dt implies X outside [0, L] must be flagged
    invalid — not clipped — and must not confirm a leak."""
    n = 400
    times = [round(i * 0.1, 3) for i in range(n)]
    p_in = _flat(60.0, n)
    p_out = _flat(55.0, n, seed=3)
    for i, t in enumerate(times):
        if t >= 3.0:                        # inlet event at 3 s
            p_in[i] = round(48.0 + random.Random(i).gauss(0, 0.02), 3)
        if t >= 25.0:                       # outlet event 22 s later (impossible)
            p_out[i] = round(44.0 + random.Random(1000 + i).gauss(0, 0.02), 3)
    engine = run_stream(times, p_in, p_out)
    assert engine.localization_invalid
    assert engine.localization is None
    assert engine.state == ANOMALY_SUSPECTED
    kinds = [e["kind"] for e in engine.events]
    assert "LOCALIZATION_INVALID" in kinds
    assert "LEAK_CONFIRMED" not in kinds
    assert not engine.isolation_time


def test_isolation_waits_for_critical_condition():
    """A localized leak that plateaus above 60% must NOT isolate."""
    spec = ScenarioSpec(name="shallow", leak_x_m=3300, leak_t_s=4.0,
                        front_drop_frac=0.12, final_frac=0.75,  # floor ~75%
                        noise_in=0.03, noise_out=0.03, duration_s=40, seed=9)
    times, p_in, p_out = generate(spec)
    engine = run_stream(times, p_in, p_out)
    assert engine.state == LOCALIZED          # confirmed + localized ...
    assert engine.isolation_time is None      # ... but never isolated
    assert engine.localization.valid
    assert abs(engine.localization.x_m - 3300) <= 200


def test_deep_leak_reaches_isolation():
    spec = ScenarioSpec(name="deep", leak_x_m=6800, leak_t_s=3.0,
                        front_drop_frac=0.12, final_frac=0.45,
                        noise_in=0.05, noise_out=0.05, duration_s=35, seed=4)
    times, p_in, p_out = generate(spec)
    engine = run_stream(times, p_in, p_out)
    assert engine.state == ISOLATED
    kinds = [e["kind"] for e in engine.events]
    assert kinds.index("CRITICAL_CONDITION") < kinds.index("VIRTUAL_ISOLATION")


def test_unstable_startup_extends_baseline_learning():
    """A ramp during the first seconds must not poison the baseline: the
    detector waits for a stable window (or flags it provisional)."""
    n = 400
    times = [round(i * 0.1, 3) for i in range(n)]
    rng = random.Random(5)
    p_in, p_out = [], []
    for t in times:
        ramp = min(t, 3.0) / 3.0            # 57 -> 60 over the first 3 s
        p_in.append(round(57.0 + 3.0 * ramp + rng.gauss(0, 0.02), 3))
        p_out.append(round(55.0 + rng.gauss(0, 0.02), 3))
    engine = run_stream(times, p_in, p_out)
    assert engine.state == "NORMAL"
    assert engine.events == []
    assert 59.5 < engine.inlet.baseline < 60.5   # learned post-ramp level


def test_status_flag_ignored_and_optional(tmp_path):
    """Engine results must be bit-identical with and without the Status
    Flag column — production inference never reads it."""
    times, p_in, p_out, flags = dev_replica()
    rows = list(zip(times, p_in, p_out, flags))

    with_flag = tmp_path / "with_flag.csv"
    with open(with_flag, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Relative Time (ms)", "Inlet Pressure (Bar)",
                    "Outlet Pressure (Bar)", "Status Flag"])
        for t, pi, po, fl in rows:
            w.writerow([int(t * 1000), pi, po, fl])

    without_flag = tmp_path / "without_flag.csv"
    with open(without_flag, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Relative Time (ms)", "Inlet Pressure (Bar)",
                    "Outlet Pressure (Bar)"])
        for t, pi, po, _ in rows:
            w.writerow([int(t * 1000), pi, po])

    results = []
    for path in (with_flag, without_flag):
        tel = load_telemetry(str(path))
        engine = run_stream(tel.times_s, tel.p_in, tel.p_out)
        results.append((engine.state, engine.inlet.arrival_time,
                        engine.outlet.arrival_time,
                        engine.localization.x_m, engine.isolation_time,
                        [e["kind"] for e in engine.events]))
    assert results[0] == results[1]
    # the flag is carried for display only
    assert load_telemetry(str(with_flag)).ref_flags is not None
    assert load_telemetry(str(without_flag)).ref_flags is None


def test_sampling_interval_derived_from_timestamps():
    """Same physical leak, 50 ms sampling: dt must be measured, arrivals
    and localization must still land on the references."""
    spec = ScenarioSpec(name="fast_sampling", leak_x_m=2400, leak_t_s=0.0,
                        dt_s=0.05, front_drop_frac=0.10, final_frac=0.5,
                        noise_in=0.02, noise_out=0.02, duration_s=25, seed=6)
    times, p_in, p_out = generate(spec)
    engine = run_stream(times, p_in, p_out)
    assert abs(engine.inlet.dt_nominal - 0.05) < 0.005
    assert engine.state == ISOLATED
    assert abs(engine.localization.x_m - 2400) <= 200
