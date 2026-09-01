"""Event history: local record of completed runs.

Strictly WRITE-AFTER / READ-ONLY with respect to analytics: a record is
built from a finished engine's outputs and appended to a local JSONL
file; nothing in the engine, detectors or loaders ever reads this file,
so historical data cannot influence current blind-dataset detection.
No ground truth is stored — false-alarm statistics are computed only in
developer mode against a separately supplied answer-key file.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
import uuid
from typing import Optional

from engine.engine import AnalyticsEngine, ALARM_STATES, ISOLATED

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(ROOT, "history")
HISTORY_PATH = os.path.join(HISTORY_DIR, "events.jsonl")


def ai_state(engine: AnalyticsEngine) -> str:
    """Final AI corroboration status, derived read-only from the scorer."""
    if engine.ml_unavailable:
        return "UNAVAILABLE"
    ml = engine.ml
    if ml is None or not getattr(ml, "trained", False):
        return "NOT TRAINED"
    pct = getattr(ml, "_smooth", None)
    if pct is None:
        return "NORMAL"
    n = len(getattr(ml, "_train_scores", []) or [])
    ceiling = 100.0 * n / (n + 1) if n else 100.0
    alert_at = min(95.0, ceiling * 0.98)
    if pct >= alert_at:
        return "HIGH"
    if pct >= alert_at * 0.85:
        return "ELEVATED"
    return "NORMAL"


def detection_latency(engine: AnalyticsEngine) -> Optional[float]:
    arrivals = [a for a in (engine.inlet.arrival_time,
                            engine.outlet.arrival_time) if a is not None]
    detect_t = engine.stages.get("detect")
    if detect_t is None or not arrivals:
        return None
    return round(detect_t - min(arrivals), 3)


def build_record(engine: AnalyticsEngine, dataset: Optional[dict],
                 mode: str) -> dict:
    """Pure function of a finished engine + dataset meta. Reads only."""
    now = datetime.datetime.now()
    loc = engine.localization if (engine.localization
                                  and engine.localization.valid) else None
    c = engine.config
    alarm_t = next((e["t"] for e in engine.events
                    if e["kind"] == "LEAK_CONFIRMED"), None)
    return {
        "event_id": "EV-" + now.strftime("%Y%m%d-%H%M%S") + "-"
                    + uuid.uuid4().hex[:6],
        "timestamp": now.isoformat(timespec="seconds"),
        "dataset": (dataset or {}).get("label") or (dataset or {}).get("name") or "—",
        "mode": mode,
        "length_m": c.length_m,
        "wave_speed_ms": c.wave_speed_ms,
        "segment_len_m": c.segment_len_m,
        "leak_detected": engine.state in ALARM_STATES,
        "final_state": engine.state,
        "t_in": engine.inlet.arrival_time,
        "t_out": engine.outlet.arrival_time,
        "delta_t": round(loc.delta_t, 3) if loc else None,
        "x_in_m": round(loc.x_m, 1) if loc else None,
        "x_out_m": round(loc.x_from_outlet_m, 1) if loc else None,
        "segment": loc.segment if loc else None,
        "loc_invalid": engine.localization_invalid,
        "max_severity": engine.severity,
        "baseline_in": round(engine.inlet.baseline, 3)
                       if engine.inlet.baseline is not None else None,
        "baseline_out": round(engine.outlet.baseline, 3)
                        if engine.outlet.baseline is not None else None,
        "noise_in": round(engine.inlet.sigma, 4),
        "noise_out": round(engine.outlet.sigma, 4),
        "detection_latency_s": detection_latency(engine),
        "ai_corroboration": ai_state(engine),
        "alarm_time": alarm_t,
        "isolated": engine.state == ISOLATED,
        "isolation_time": engine.isolation_time,
        "samples": engine.sample_count,
    }


def append(record: dict) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def read_all() -> list[dict]:
    if not os.path.isfile(HISTORY_PATH):
        return []
    out = []
    with open(HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def clear() -> None:
    if os.path.isfile(HISTORY_PATH):
        os.remove(HISTORY_PATH)


def _truth_map() -> Optional[dict]:
    """Developer mode only: an answer-key file lying beside the data.
    Never read anywhere else; absent at competition time."""
    keys = glob.glob(os.path.join(ROOT, "data", "*answer_key*.json"))
    if not keys:
        return None
    merged: dict = {}
    for path in sorted(keys):
        try:
            with open(path) as f:
                merged.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    return merged or None


def stats(records: list[dict]) -> dict:
    leaks = sum(1 for r in records if r.get("leak_detected"))
    latencies = [r["detection_latency_s"] for r in records
                 if r.get("detection_latency_s") is not None]
    out = {
        "total_runs": len(records),
        "leaks_detected": leaks,
        "no_leak_runs": len(records) - leaks,
        "avg_detection_latency_s": (round(sum(latencies) / len(latencies), 3)
                                    if latencies else None),
        "isolations": sum(1 for r in records if r.get("isolated")),
        "truth_available": False,
        "false_alarms": None,
        "missed_leaks": None,
    }
    truth = _truth_map()
    if truth:
        fa = miss = judged = 0
        for r in records:
            # match on the dataset's base file name (labels may carry sheets)
            name = str(r.get("dataset", "")).split(" › ")[0].split(" · ")[-1]
            key = truth.get(name)
            if key is None:
                continue
            judged += 1
            if not key.get("leak", False) and r.get("leak_detected"):
                fa += 1
            if key.get("leak", False) and not r.get("leak_detected"):
                miss += 1
        if judged:
            out.update({"truth_available": True, "false_alarms": fa,
                        "missed_leaks": miss, "judged_runs": judged})
    return out
