"""Event history + PDF incident report: correctness and ZERO effect on
analytics outputs (both are strictly read-only over a finished engine)."""

import json

import pytest

from engine.engine import EngineConfig
from server import history as history_mod
from server.pdf_report import build_pdf_report
from simulator.generate import ScenarioSpec, generate, dev_replica
from simulator.harness import run_stream


def _fingerprint(e):
    loc = e.localization
    return {
        "state": e.state,
        "t_in": e.inlet.arrival_time,
        "t_out": e.outlet.arrival_time,
        "x_m": loc.x_m if loc and loc.valid else None,
        "segment": loc.segment if loc and loc.valid else None,
        "isolation_time": e.isolation_time,
        "events": [(ev["t"], ev["kind"]) for ev in e.events],
    }


REQUIRED_FIELDS = [
    "event_id", "timestamp", "dataset", "length_m", "leak_detected",
    "t_in", "t_out", "delta_t", "x_in_m", "x_out_m", "segment",
    "max_severity", "baseline_in", "baseline_out", "noise_in", "noise_out",
    "detection_latency_s", "ai_corroboration", "isolated",
]


def _dev_engine():
    times, p_in, p_out, _ = dev_replica()
    return run_stream(times, p_in, p_out)


def test_record_contains_all_specified_fields():
    engine = _dev_engine()
    rec = history_mod.build_record(engine, {"label": "dev_dataset.csv"},
                                   "competition")
    for f in REQUIRED_FIELDS:
        assert f in rec, f"missing field {f}"
    assert rec["leak_detected"] is True and rec["isolated"] is True
    assert abs(rec["t_in"] - 2.40) <= 0.1
    assert abs(rec["x_in_m"] - 2400.0) <= 200.0
    assert rec["x_out_m"] == 10_000.0 - rec["x_in_m"]
    assert rec["segment"] == 2
    assert rec["max_severity"] == "CRITICAL"
    assert rec["detection_latency_s"] is not None
    assert rec["ai_corroboration"] in ("NORMAL", "ELEVATED", "HIGH",
                                       "UNAVAILABLE", "NOT TRAINED")
    assert rec["event_id"].startswith("EV-")


def test_append_read_stats_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(history_mod, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(history_mod, "HISTORY_PATH",
                        str(tmp_path / "events.jsonl"))
    engine = _dev_engine()
    rec = history_mod.build_record(engine, {"label": "dev_dataset.csv"},
                                   "competition")
    quiet_spec = ScenarioSpec(name="q", leak=False, duration_s=40,
                              noise_in=0.05, noise_out=0.05, seed=3)
    quiet = run_stream(*generate(quiet_spec))
    rec2 = history_mod.build_record(quiet, {"label": "quiet.csv"},
                                    "competition")
    history_mod.append(rec)
    history_mod.append(rec2)

    records = history_mod.read_all()
    assert [r["event_id"] for r in records] == [rec["event_id"], rec2["event_id"]]
    s = history_mod.stats(records)
    assert s["total_runs"] == 2
    assert s["leaks_detected"] == 1
    assert s["no_leak_runs"] == 1
    assert s["isolations"] == 1
    assert s["avg_detection_latency_s"] == rec["detection_latency_s"]

    history_mod.clear()
    assert history_mod.read_all() == []


def test_pdf_generated_for_leak_and_quiet_runs():
    engine = _dev_engine()
    pdf = build_pdf_report(engine, {"label": "dev_dataset.csv"}, "competition")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 8000
    assert pdf.count(b"/Type /Page") >= 1

    quiet = run_stream(*generate(ScenarioSpec(
        name="q", leak=False, duration_s=40, noise_in=0.05, noise_out=0.05,
        seed=4)))
    pdf2 = build_pdf_report(quiet, {"label": "quiet.csv"}, "competition")
    assert pdf2.startswith(b"%PDF")


def test_history_and_pdf_have_zero_effect_on_analytics(tmp_path, monkeypatch):
    """Building/writing the record and rendering the PDF must not change a
    single analytics output — they only read the finished engine."""
    monkeypatch.setattr(history_mod, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(history_mod, "HISTORY_PATH",
                        str(tmp_path / "events.jsonl"))
    times, p_in, p_out, _ = dev_replica()
    engine = run_stream(times, p_in, p_out)
    before = _fingerprint(engine)

    rec = history_mod.build_record(engine, {"label": "dev_dataset.csv"},
                                   "competition")
    history_mod.append(rec)
    build_pdf_report(engine, {"label": "dev_dataset.csv"}, "competition",
                     rec["event_id"])
    assert _fingerprint(engine) == before

    # a run performed AFTER history exists is identical to the reference —
    # nothing in the engine reads the history file
    engine2 = run_stream(times, p_in, p_out)
    assert _fingerprint(engine2) == before


def test_no_ground_truth_in_record_or_pdf():
    """Records and PDFs must never carry answer-key information."""
    engine = _dev_engine()
    rec = history_mod.build_record(engine, {"label": "dev_dataset.csv"},
                                   "competition")
    blob = json.dumps(rec).lower()
    assert "truth" not in blob and "answer" not in blob and "jury" not in blob
    pdf = build_pdf_report(engine, {"label": "dev_dataset.csv"}, "competition")
    for token in (b"answer_key", b"ground truth", b"jury"):
        assert token not in pdf.lower()
