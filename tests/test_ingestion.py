"""Ingestion robustness: schema tolerance, filename independence,
validation reporting, reset determinism and per-file fresh learning."""

import csv
import random

import pytest

from simulator.generate import ScenarioSpec, generate, dev_replica
from simulator.harness import run_stream
from streaming.loader import load as load_telemetry, LoaderError


def _write(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_arbitrary_filename_and_headers(tmp_path):
    """Any correctly formatted file works — no BLIND_xx naming, no exact
    dev-schema header spellings required."""
    times, p_in, p_out, _ = dev_replica()
    path = tmp_path / "final_evaluation_run_7_v2.csv"   # arbitrary name
    _write(path, ["Time (ms)", "INLET Pressure [bar]", "Outlet  pressure (BAR)"],
           [[int(t * 1000), pi, po] for t, pi, po in zip(times, p_in, p_out)])
    tel = load_telemetry(str(path))
    v = tel.validation
    assert v["samples"] == len(times)
    assert v["sample_dt_ms"] == 100.0
    assert v["status_flag_present"] is False
    engine = run_stream(tel.times_s, tel.p_in, tel.p_out)
    assert engine.state == "ISOLATED"
    assert abs(engine.localization.x_m - 2400.0) <= 200.0


def test_messy_file_cleaned_with_warnings(tmp_path):
    """Unsorted rows, malformed rows and duplicate timestamps are repaired
    and reported — then detection still works."""
    times, p_in, p_out, _ = dev_replica()
    rows = [[int(t * 1000), pi, po] for t, pi, po in zip(times, p_in, p_out)]
    rows.insert(30, ["garbage", "n/a", ""])            # malformed row
    rows.insert(10, rows[50][:])                       # duplicate timestamp
    rng = random.Random(3)
    shuffled = rows[:]
    rng.shuffle(shuffled)                              # fully out of order
    path = tmp_path / "messy.csv"
    _write(path, ["Relative Time (ms)", "Inlet Pressure (Bar)",
                  "Outlet Pressure (Bar)"], shuffled)
    tel = load_telemetry(str(path))
    warns = " · ".join(tel.validation["warnings"])
    assert "malformed" in warns
    assert "sorted" in warns
    assert "duplicate" in warns
    assert tel.times_s == sorted(tel.times_s)
    engine = run_stream(tel.times_s, tel.p_in, tel.p_out)
    assert engine.state == "ISOLATED"
    assert abs(engine.localization.x_m - 2400.0) <= 200.0


def test_loader_errors_are_actionable(tmp_path):
    no_inlet = tmp_path / "no_inlet.csv"
    _write(no_inlet, ["Relative Time (ms)", "Pressure A", "Outlet Pressure"],
           [[i * 100, 60, 55] for i in range(50)])
    with pytest.raises(LoaderError, match="inlet"):
        load_telemetry(str(no_inlet))

    tiny = tmp_path / "tiny.csv"
    _write(tiny, ["Relative Time (ms)", "Inlet Pressure", "Outlet Pressure"],
           [[i * 100, 60, 55] for i in range(5)])
    with pytest.raises(LoaderError, match="samples"):
        load_telemetry(str(tiny))


def test_replay_same_file_is_deterministic():
    """Reset semantics: a fresh engine over the same samples must produce
    identical results (arrivals, X, isolation time, full event sequence)."""
    times, p_in, p_out, _ = dev_replica()

    def run():
        e = run_stream(times, p_in, p_out)
        return (e.state, e.inlet.arrival_time, e.outlet.arrival_time,
                e.localization.x_m, e.isolation_time,
                [(ev["t"], ev["kind"]) for ev in e.events])

    assert run() == run()


def test_different_file_learns_from_scratch():
    """A new dataset with different baselines must be learned fresh —
    nothing carries over between engines."""
    spec_a = ScenarioSpec(name="a", leak_x_m=2400, leak_t_s=3.0,
                          base_in=60.0, base_out=55.0, final_frac=0.5, seed=1)
    spec_b = ScenarioSpec(name="b", leak_x_m=7600, leak_t_s=5.0,
                          base_in=88.0, base_out=80.0, final_frac=0.5, seed=2)
    e_a = run_stream(*generate(spec_a))
    e_b = run_stream(*generate(spec_b))
    assert abs(e_a.inlet.baseline - 60.0) < 1.0
    assert abs(e_b.inlet.baseline - 88.0) < 1.0
    assert abs(e_b.outlet.baseline - 80.0) < 1.0
    assert abs(e_a.localization.x_m - 2400) <= 200
    assert abs(e_b.localization.x_m - 7600) <= 200


def test_batch_evaluator_production_path(tmp_path):
    """server.batch.evaluate_path: independent engines per file, correct
    fields, no filename assumptions, no ground truth involved."""
    from server.batch import evaluate_path
    specs = [
        ScenarioSpec(name="anything_1", leak_x_m=1600, leak_t_s=4.0,
                     final_frac=0.5, seed=11),
        ScenarioSpec(name="whatever_2", leak=False, duration_s=45,
                     noise_in=0.1, noise_out=0.1, seed=12),
    ]
    from simulator.generate import write_csv
    paths = []
    for s in specs:
        t, pi, po = generate(s)
        p = tmp_path / f"{s.name}.csv"
        write_csv(str(p), t, pi, po)
        paths.append(str(p))

    leak_row = evaluate_path(paths[0])
    assert leak_row["leak_detected"] and leak_row["isolated"]
    assert leak_row["critical_reached"]
    assert abs(leak_row["x_m"] - 1600) <= 200
    assert leak_row["segment"] == 1
    assert leak_row["detection_latency_s"] is not None

    quiet_row = evaluate_path(paths[1])
    assert not quiet_row["leak_detected"]
    assert not quiet_row["isolated"]
    assert not quiet_row["critical_reached"]
    assert quiet_row["final_state"] in ("NORMAL", "ANOMALY_SUSPECTED")
