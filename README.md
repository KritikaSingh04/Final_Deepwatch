# DEEPWATCH — Subsea Pipeline Integrity Twin

Real-time leak detection, NPW localization, 3D digital twin and automated
virtual isolation for the TWI India / IMECE 2026 Brain Bolt problem statement.

## Quick start

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn server.app:app --port 8010
# open http://localhost:8010
```

In the dashboard: pick `dev_dataset.csv` → **▶ Stream** (use 5–10× speed).
Watch the sequence: DETECT → ANALYZE → LOCALIZE → VISUALIZE → RESPOND.

**Blind evaluation:** upload the organizer file with **⬆ Blind dataset**
(CSV or XLSX — any filename, any reasonable header spelling; Status Flag is
ignored if present and never required), or drop it into `data/`. On load a
validation summary confirms samples, sampling interval and detected
channels. Nothing else changes — the engine is identical for every dataset,
and **Reset** rebuilds it from scratch (baseline, detectors, AI model, state
machine, localization, isolation, event log), so replaying the same file
reproduces the same result.

**Multi-sheet evaluation workbook:** uploading an XLSX whose worksheets are
independent scenarios (e.g. Read_Me + BLIND_01…BLIND_07) never concatenates
or silently picks a sheet — the app reports "N evaluation scenarios
detected", ignores non-data sheets, and lists every valid worksheet in the
dataset dropdown. Selecting a worksheet builds a brand-new engine for that
scenario alone, and its clock/duration follow that sheet's own Relative
Time axis (≈ T+12.0 s per official sheet). In the ⚙ Batch eval modal,
**▶ Run all blind sheets** evaluates every valid worksheet independently
(fresh engine per sheet) and tabulates leak detection, t_in/t_out/Δt, X
from inlet and outlet, segment, severity and isolation.

**⚙ Batch eval** (developer mode): select several CSV/XLSX files at once —
each is processed independently through the production inference path and a
results table shows leak detected, t_in, t_out, Δt, X, segment, detection
latency, critical reached and isolation executed. Internal testing only; the
streaming demo is unaffected.

## Operating modes

- **🔒 Competition Mode (default)** — locked official parameters
  (L = 10,000 m · C = 1,000 m/s · 5 segments × 2,000 m), used for all
  official blind datasets. Batch/blind evaluation always runs with these.
- **⚙ Engineering / Scale Mode** — via the header mode chip: any pipeline
  length (km), wave speed (m/s) and segment size (km). Segments are
  generated dynamically (ceil(L/segment); the final segment absorbs any
  remainder) and the identical unmodified analytics apply. Physical timing
  validation |Δt| ≤ L/C follows the active configuration; violations show
  "INVALID LOCALIZATION — timing inconsistent with configured pipeline".
  Try `sample_scale_100km_leak63km.csv` in 100 km / 20 km mode.

The main view prioritizes detection → localization → signal quality →
response; the raw pressure charts, AI percentile diagnostics and raw
calculations live in the collapsible "Telemetry / Engineering Detail"
section.

## Event state machine

```
NORMAL → ANOMALY_SUSPECTED (first station transient)
       → LEAK_CONFIRMED    (correlated second transient, valid NPW Δt)
       → LOCALIZED         (X inside [0, 10000] m; out-of-range Δt is
                            flagged INVALID, never clipped)
       → CRITICAL          (sustained <60% of baseline)
       → VIRTUAL ISOLATION (automatic response to the critical condition)
```

A single-sensor event never claims "leak confirmed"; localization alone
never triggers isolation.

## Validation & blind-dataset test mode

```bash
./.venv/bin/python -m pytest tests/           # 37 tests incl. dev-dataset references
./.venv/bin/python -m scripts.run_sweep       # 33 unseen leaks + 8 no-leak controls
./.venv/bin/python -m simulator.generate      # regenerate demo datasets

# developer test mode: batch-evaluate every BLIND_*.csv through the
# production inference path (answer key optional, scoring only):
./.venv/bin/python -m scripts.blind_eval
./.venv/bin/python -m scripts.blind_eval --truth answer_key.json --out results.csv
```

## Layout

| Path | What |
|---|---|
| `engine/` | Edge analytics: detectors, NPW math, health tiers, state machine, AI scorer, forecaster |
| `streaming/` | Tolerant CSV/XLSX loader (Status Flag quarantined — display-only) |
| `server/` | FastAPI + WebSocket replay bus, incident-report generator |
| `web/` | Dashboard: 3D twin (three.js, vendored), 2D schematic, strip charts |
| `simulator/` | Dev-dataset replica + parametric blind-scenario generator |
| `tests/`, `scripts/` | Test suite and generalization sweep |
| `report/` | Technical Design Report + pitch outline |

No hard-coded leak values: dev-dataset reference numbers (2.40 s / 7.60 s /
2,400 m) exist only in `tests/` as assertions.
