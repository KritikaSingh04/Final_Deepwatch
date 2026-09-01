"""Developer test mode: batch-evaluate blind datasets.

Processes every file matching BLIND_*.csv (case-insensitive; .xlsx too)
through the PRODUCTION inference path — the same loader (Status Flag
quarantined) and the same AnalyticsEngine, sample by sample — and prints
per file:

    leak detected yes/no, t_in, t_out, delta_t, calculated X, segment,
    time to detection, isolation occurred, false-alarm status.

Ground truth NEVER enters inference. If an answer key exists it may be
supplied separately via --truth answer_key.json:

    {"BLIND_01.csv": {"leak": true,  "x_m": 3200.0},
     "BLIND_07.csv": {"leak": false}}

and is used only afterwards, for scoring columns (localization error,
false-alarm / missed-leak verdicts).

Usage:
    python -m scripts.blind_eval                       # data/BLIND_*.csv
    python -m scripts.blind_eval --dir /path --glob "*.csv"
    python -m scripts.blind_eval --truth answer_key.json --out results.csv
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import sys

from engine.npw import localization_error_pct
from server.batch import evaluate_path as evaluate_file


def apply_truth(row: dict, truth: dict | None) -> dict:
    """Post-hoc scoring only — inference is already finished."""
    row["verdict"] = "n/a (no answer key)"
    row["error_m"] = row["error_pct"] = None
    if truth is None:
        return row
    key = truth.get(row["file"])
    if key is None:
        row["verdict"] = "n/a (file not in key)"
        return row
    if not key.get("leak", False):
        row["verdict"] = ("FALSE ALARM" if row["leak_detected"] or row["isolated"]
                          else "OK (no-leak, silent)")
        return row
    if not row["leak_detected"]:
        row["verdict"] = "MISSED LEAK"
        return row
    row["verdict"] = "OK (leak detected)"
    x_ref = key.get("x_m")
    if x_ref is not None and row["x_m"] is not None:
        row["error_m"] = round(abs(row["x_m"] - x_ref), 1)
        row["error_pct"] = round(localization_error_pct(row["x_m"], x_ref), 3)
        row["verdict"] += (" · full marks" if row["error_pct"] <= 2.0
                           else " · acceptable" if row["error_pct"] <= 5.0
                           else " · NEEDS JUSTIFICATION")
    return row


def fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="data")
    ap.add_argument("--glob", default="BLIND_*.*")
    ap.add_argument("--truth", default=None,
                    help="answer-key JSON (scoring only, never inference)")
    ap.add_argument("--out", default=None, help="also write results CSV here")
    args = ap.parse_args()

    names = sorted(f for f in os.listdir(args.dir)
                   if fnmatch.fnmatch(f.lower(), args.glob.lower())
                   and f.lower().endswith((".csv", ".xlsx", ".xls")))
    if not names:
        print(f"no files matching {args.glob!r} in {args.dir}/ — "
              f"drop the blind datasets there and rerun", file=sys.stderr)
        sys.exit(1)

    truth = None
    if args.truth:
        with open(args.truth) as f:
            truth = json.load(f)

    rows = []
    for name in names:
        path = os.path.join(args.dir, name)
        try:
            row = apply_truth(evaluate_file(path), truth)
        except Exception as exc:
            row = {"file": name, "verdict": f"ERROR: {exc}"}
        rows.append(row)

    cols = [("file", 26), ("leak_detected", 8), ("t_in", 8), ("t_out", 8),
            ("delta_t", 8), ("x_m", 9), ("segment", 4),
            ("detection_latency_s", 8), ("isolated", 9),
            ("isolation_time", 8), ("final_state", 18)]
    header = (f"{'file':<26}{'leak?':<8}{'t_in':>8}{'t_out':>8}{'Δt':>8}"
              f"{'X (m)':>9}{'seg':>4}{'det.lat':>8}{'isolated':>9}"
              f"{'iso t':>8}  final state")
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        print(f"{r.get('file',''):<26}{fmt(r.get('leak_detected')):<8}"
              f"{fmt(r.get('t_in')):>8}{fmt(r.get('t_out')):>8}"
              f"{fmt(r.get('delta_t')):>8}"
              f"{fmt(r.get('x_m'), 0):>9}{fmt(r.get('segment')):>4}"
              f"{fmt(r.get('detection_latency_s')):>8}"
              f"{fmt(r.get('isolated')):>9}{fmt(r.get('isolation_time')):>8}"
              f"  {r.get('final_state','—')}")
        extra = []
        if r.get("loc_invalid"):
            extra.append("localization INVALID (Δt outside bounds)")
        if r.get("error_pct") is not None:
            extra.append(f"error {r['error_m']} m ({r['error_pct']}% of L)")
        if r.get("verdict"):
            extra.append(r["verdict"])
        if extra:
            print(" " * 26 + "· " + " · ".join(extra))

    if args.out:
        keys = sorted({k for r in rows for k in r})
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"\nresults written to {args.out}")


if __name__ == "__main__":
    main()
