# DEEPWATCH — Technical Design Report

**Real-Time Subsea Pipeline Integrity Management: Edge Analytics and 3D Transient-Flow Digital Twin for Leak Detection and Localization**

Brain Bolt — The Engineers Sprint · IMECE India 2026 · Problem statement by TWI India Pvt Ltd

---

## 1. System architecture and data flow

DEEPWATCH is organised as three strictly separated layers so that the analytics
engine is provably dataset-agnostic — the identical engine object processes the
Development Dataset, our synthetic validation scenarios and the Blind Evaluation
Datasets with zero modification.

```
 CSV / XLSX          ┌────────────────────┐      ┌─────────────────────┐
 telemetry file ───▶ │  Stream Simulator   │ ───▶ │   Analytics Engine   │
 (organizer data)    │  replays row-by-row │      │  (pure Python, edge  │
                     │  at 100 ms cadence, │      │  model: one sample   │
                     │  1×–50× wall speed  │      │  at a time, no file  │
                     └────────────────────┘      │  lookahead)          │
                                                  └──────────┬──────────┘
                                                             │ events + state
                                                  ┌──────────▼──────────┐
                                                  │ FastAPI + WebSocket  │
                                                  │ broadcast bus        │
                                                  └──────────┬──────────┘
                                                             │ JSON ticks
                     ┌───────────────────────────────────────▼──────────┐
                     │  Digital-Twin Dashboard (browser)                 │
                     │  3D scene (three.js) · 2D schematic · strip       │
                     │  charts · NPW panel · event log · forecasts ·     │
                     │  incident report generator                        │
                     └──────────────────────────────────────────────────┘
```

* **Edge model.** `AnalyticsEngine.update(t, p_in, p_out)` receives one sample
  at a time and never sees the file as a whole — the same call signature would
  sit directly on an edge gateway consuming MQTT frames. (The replayer is a
  drop-in stand-in for a broker subscription; the WebSocket bus plays the role
  of the SCADA/HMI uplink.)
* **Tolerant, validated ingestion.** The loader discovers time/inlet/outlet
  columns case-insensitively (no exact header spellings and no filename
  conventions required), accepts CSV or XLSX, handles time in ms, seconds
  or wall-clock timestamps, repairs out-of-order/duplicate/malformed rows
  (reported as warnings), and quarantines the Status Flag column so it can
  never reach the engine — carried for display only and never required.
  Every load surfaces a validation summary in the UI: sample count,
  measured sampling interval, the detected channel headers, and "Status
  Flag ignored" when present. Reset rebuilds the engine completely
  (baseline, detectors, frozen AI model, state machine, localization,
  isolation, events), so replaying a file is deterministic and each new
  file is learned from scratch. A Batch Evaluation developer mode processes
  several files independently (fresh engine per file) and tabulates
  detection, timing, localization, critical and isolation outcomes.
* **Multi-sheet evaluation workbooks.** An uploaded XLSX is inspected
  sheet-by-sheet: non-data sheets (Read_Me) are ignored, every worksheet
  with identifiable time + inlet/outlet pressure channels becomes its own
  dropdown entry, and nothing is processed until the user selects one —
  sheets are never concatenated or silently chosen. Each selection builds
  a brand-new engine (baseline, noise history, thresholds,
  IsolationForest, state machine, localization, severity, isolation,
  events all fresh), and the displayed duration follows that sheet's own
  Relative Time axis. Sheet and file names are labels only — never
  detection inputs. A *Run all blind sheets* developer mode evaluates
  every valid worksheet independently and tabulates the outcomes.
* **Blind-dataset workflow.** A blind file is either dropped into `data/` or
  uploaded live through the dashboard's *⬆ Blind dataset* control; one click
  streams it through the identical engine.

## 2. Anomaly detection methodology (Vector A)

Detection uses **pressure telemetry only**. The supplied Status Flag is never
read by any detection code path (grep `engine/` for `flag` — it does not
appear).

Per sensor, in order:

1. **Sampling interval measured, not assumed.** The nominal interval is the
   robust median of the actual timestamp gaps; all rate quantities are
   expressed in **bar/s** using real spacing, so 50 ms or irregular
   sampling changes nothing.
2. **Baseline learning from a verified-stable window.** The detector waits
   until the most recent ≥1.5 s window passes a stability check (trend
   ≤3σ over the window, outliers ≤6σ, σ from MAD) before locking the
   baseline (median) — if stability is not reached within 6 s the best
   window is accepted and flagged *provisional*. A slow EWMA
   (α = 0.02/sample) then tracks gradual operating variation; the baseline
   **freezes** the instant a transient candidate opens and stays frozen
   after confirmation until reset, so the leak cannot contaminate its own
   reference. The dashboard displays the learned value, its sample count
   and the noise sigma per sensor ("baseline learned from stable
   telemetry").
3. **Adaptive noise floor.** Rolling MAD of the residuals and of the
   sample rates, converted to robust sigma (1.4826·MAD). **Every
   threshold in the system is a multiple of measured noise — no absolute
   pressure threshold is used anywhere.**
4. **Two detector paths raise a transient candidate:**
   * *Rate detector* — dP/dt beyond max(6·σ_rate, floor) bar/s catches the
     sharp NPW front and pins its timestamp.
   * *CUSUM detector* — one-sided cumulative sum of the normalised negative
     residual (slack 0.5σ, trip at 10σ accumulated) catches gentler fronts
     under heavy noise; its arrival estimate is back-dated to the change
     point where the statistic last left zero.
5. **Persistence confirmation.** Over the following ≥0.5 s (≥3 samples)
   the mean deviation must exceed max(4σ, 0.3% of baseline), otherwise the
   candidate is **revoked** (spike / short nuisance disturbance) and
   monitoring resumes.
6. **Arrival-time refinement.** The reported arrival is the first sample
   carrying a significant fraction (30%) of the confirmed front amplitude
   and clearing 5σ. This matches the physical NPW front rather than any
   small precursor sag, and reproduces the jury convention on the
   Development Dataset exactly (t_in = 2.40 s, t_out = 7.60 s) without any
   tuned constant referring to those values.

t_in and t_out are detected fully independently, so t_in < t_out,
t_out < t_in and t_in ≈ t_out are all handled, at any baseline pressures.

**Event state machine** (single-sensor events never claim a leak;
isolation never fires merely because the leak is localized):

| State | Condition | Response |
|---|---|---|
| `NORMAL` | — | — |
| `ANOMALY_SUSPECTED` | first station's transient confirmed | early-warning log entry — **no leak alarm** |
| `LEAK_CONFIRMED` | **correlated** second transient: both stations confirmed, Δt physically valid, and a leak signature (sharp front on ≥1 sensor or sustained <80% drop) | leak alarm raised (early warning) |
| `LOCALIZED` | NPW X inside [0, L] | leak coordinate + segment published |
| `CRITICAL` | sustained pressure <60% of baseline (RED tier) | critical condition satisfied |
| `ISOLATED` | entered on CRITICAL | **automatic virtual isolation** |

If the two arrivals imply X outside [0, 10 000] m, the localization is
flagged **INVALID** (uncorrelated transients) and displayed as such — the
value is never silently clipped, and no leak is confirmed from it. A
coordinated gentle decline on both sensors (operational ramp) has no leak
signature and stays an anomaly watch — never a leak alarm. Severity
(LOW / MAJOR / CRITICAL) maps from the worst health tier reached.

## 3. NPW calculation and localization logic (Vector C)

Exactly as specified:

> **X = (L − C·Δt) / 2**,  Δt = t_out − t_in,  L = 10,000 m, C = 1,000 m/s

Δt may be positive (inlet half), ~zero (midpoint) or negative (outlet
half); its sign is location information and is never folded with abs().
Localization is **dual-ended**: X_from_outlet = (L + C·Δt)/2 is computed
independently and cross-checked against X_from_inlet + X_from_outlet = L
(floating-point tolerance; a failure raises a localization-consistency
warning). Both distances are displayed with equal prominence in the NPW
panel and on the leak cards in the 3D and 2D twins. The estimated
leak-origin time t_event = (t_in + t_out − L/C)/2 is carried as an
engineering diagnostic in an expandable panel section — it does not affect
primary localization. X is mapped to the standardized segments with
half-open lower bounds (Segment 5 additionally includes the 10,000 m
endpoint). If only one station ever confirms (a conceivable blind edge
case), the system reports a detected but unlocalized anomaly with the
affected pipeline half flagged — it never invents a coordinate.

Development Dataset verification (automated test, values used **only** as
test assertions): t_in = 2.40 s, t_out = 7.60 s, Δt = +5.20 s →
**X = 2,400 m, Segment 2** — 0 m error.

## 4. Digital twin and health-state logic (Vector B)

The dashboard is a purpose-built dark control-room UI (FastAPI-served, zero
external services, runs fully offline):

* **3D digital twin** (three.js): seabed, the five logical pipeline segments
  with flanges and supports, inlet manifold and outlet terminal platforms,
  km markers, ambient particulates. Segment meshes are live-coloured by health
  tier; a confirmed leak spawns a pulsing marker with a rising bubble plume at
  the computed X; isolation animates red gate valves closing at the affected
  segment's boundaries.
* **2D schematic** (SVG): the acceptable-minimum representation required by
  the PS, always visible below the 3D view — five segments, km scale, sensor
  stations with t_in/t_out badges, leak pin with coordinate callout, isolation
  valves and "SEGMENT ISOLATED" state.
* **Live strip charts** for both sensors with learned-baseline line, 95/80/60%
  health guide lines, adaptive trip level, arrival markers and hover
  crosshair/tooltip.
* **Health-state logic** is exactly the mandated table, applied to the
  sustained (5-sample median) pressure/baseline ratio: ≥95% GREEN Healthy ·
  80–95% YELLOW Caution · 60–80% ORANGE Degraded · <60% RED Critical.
  Because only the two boundary stations physically measure pressure, the
  pipeline is coloured by **global line health** (worst of PT-001/PT-002)
  — the twin never implies independent per-segment measurements. The
  calculated leak segment and the isolated segment are flagged explicitly
  on top, and each sensor's own tier is shown on its KPI tile. Every tier
  is always shown with its text label — colour never carries the meaning
  alone.
* The **detect → analyze → localize → visualize → respond** sequence is an
  explicit lit stepper across the top of the console, timestamped per stage.

## 5. Virtual mitigation logic

Isolation is gated on the **critical condition**, per the challenge logic —
never on localization alone. The leak alarm at `LEAK_CONFIRMED` acts as the
early warning; when sustained pressure falls below 60% of baseline (RED –
Critical) the engine — not the operator — emits `CRITICAL_CONDITION`
followed by `VIRTUAL_ISOLATION`: valves close in the twin at the affected
segment boundaries, the annunciator latches **⛔ SEGMENT ISOLATED — ALARM
ACTIVE**, an audible alarm fires, the event is logged with its timestamp, and
the incident report becomes available. No manual intervention exists in this
path (the only human control is replay transport). On the Development Dataset
the sequence runs: leak confirmed + localized at t ≈ 7.9 s → critical
condition and automatic isolation at t ≈ 10.3 s.

## 6. Validation and localization accuracy

Automated test suite (`pytest`, 37 tests — including single-sensor gating,
uncorrelated-transient invalidation, isolation gating, unstable-startup
baseline handling, Status-Flag independence and 50 ms-sampling checks)
plus a generalization sweep
(`python -m scripts.run_sweep`) over scenarios generated by a parametric
simulator (arbitrary leak position, event time, front sharpness, drop depth,
noise σ, baseline drift, spikes, no-leak controls):

| Check | Result |
|---|---|
| Development Dataset t_in / t_out | 2.40 s / 7.60 s (reference: 2.40 / 7.60, tol ±100 ms) |
| Development Dataset X | 2,400 m, Segment 2 — 0.0% error |
| Automatic isolation on dev dataset | critical condition + isolation at t ≈ 10.3 s, Segment 2 (leak alarm from t ≈ 7.9 s) |
| Sweep: 33 unseen leak scenarios (11 positions 600–9,400 m × 3 noise levels, randomised baselines/depths/sharpness) | 33/33 detected & isolated; localization error 0 m in all 33 (≤2% full-marks band: 33/33) |
| Sweep: 8 no-leak controls (noise to σ=0.25 bar, sinusoidal variation, slow ramps, sensor spikes) | 0 leak alarms, 0 isolations (3 advisory watches only) |
| Detection-time accuracy in sweep | within one 100 ms sample of ground truth on both stations |

The zero-error localization is a structural property, not luck: both stations
see the front rise with the same shape, so the first-significant-sample
convention slips by the same single sample on each side and Δt is preserved
exactly.

## 7. Noise and robustness analysis

* All thresholds scale with the measured noise floor (MAD-based, outlier-robust),
  so the same code detects a 5-bar front over 0.02-bar noise and over
  0.25-bar noise; the dashboard's *Edge Analytics* panel shows σ and the
  resulting trip levels adapting live per dataset.
* Single-sample spikes up to several bar are revoked by the sustained-deviation
  check; sinusoidal operating variation and slow ramps are absorbed by the
  EWMA baseline and CUSUM slack; deep coordinated ramps surface as advisory
  watches, never alarms.
* The AI second-opinion layer (below) is trained per-dataset on that dataset's
  own stable baseline window and then frozen, so it cannot overfit the
  development example or drift during an event.
* Failure containment: detector state machines are per-sensor; a confirmed
  transient freezes that sensor's baseline but the other sensor keeps
  monitoring independently.

## 8. Beyond-requirement capabilities

1. **Adaptive noise filtering & self-tuning thresholds** — live σ/trip-level
   readouts per sensor (drives the robustness results above).
2. **AI second-opinion anomaly scorer** — an IsolationForest (with a
   dependency-free robust-z fallback) trained ONCE on the current dataset's
   stable baseline window over scale-free features (slope, variability,
   deviation), then **frozen** — no retraining, no cross-dataset learning.
   Displayed as a **calibrated anomaly percentile** against the frozen
   training distribution (plotting position rank/(N+1), so the readout can
   never claim an arbitrary "100/100"; its ceiling is N/(N+1)). Advisory by
   design — the deterministic pressure-transient detector remains the
   primary safety signal, as the PS requires.
3. **Predictive decay forecasting** — once a leak is confirmed, least-squares
   trend projection publishes live countdowns to the 80% and 60% thresholds
   per sensor ("T−4.2 s to CRITICAL").
4. **One-click automated incident report** — a print-ready report generated
   from the recorded run: event timeline, NPW calculation with substituted
   values, pressure chart, final segment health map, sign-off block.
5. **Blind-scenario simulator + self-validation harness** — the parametric
   generator and sweep runner above; also used to demo live that the engine
   handles scenarios invented on the spot (including a no-leak control) —
   our direct evidence of generalization.
6. **Blind-dataset developer test mode** — `python -m scripts.blind_eval`
   batch-processes every `BLIND_*.csv` through the production inference
   path and reports, per file: leak detected yes/no, t_in, t_out, Δt,
   calculated X and segment, detection latency, isolation occurrence and
   false-alarm status. An answer key (if available) is supplied separately
   via `--truth` and is used only for post-hoc scoring — ground truth
   never enters inference.

## 9. Limitations and commercial scalability

* **Two-station NPW** cannot distinguish a mid-point leak (Δt ≈ 0) from a
  perfectly coordinated both-end operational drop; commercial deployments add
  intermediate stations (each pair localises independently) or fuse flow
  balance (API RP 1130 CPM) — the engine's per-sensor detector array extends
  to N stations without redesign.
* **Wave speed is specified constant** (1,000 m/s). In reality C varies with
  fluid, temperature and pipe compliance; a field system would calibrate C
  from known transients (e.g. scheduled valve moves) and propagate its
  uncertainty into the X estimate (±1% in C ↦ ±~50 m here).
* **Sampling** at 100 ms bounds timing precision; industrial NPW units sample
  at 10–100× that rate, shrinking the localization quantum proportionally.
* Single-file server + browser dashboard scales to a fleet by swapping the
  replayer for real MQTT ingestion and multiplying engine instances per
  pipeline — the engine is stateless between samples beyond its own small
  buffers, so thousands of segments per host are practical.

---

*Team-supplied software: Python 3.12, NumPy/Pandas/scikit-learn, FastAPI +
WebSocket, three.js (vendored, offline). Run: `uvicorn server.app:app` and
open http://localhost:8000.*
