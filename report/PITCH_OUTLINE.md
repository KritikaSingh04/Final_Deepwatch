# Pitch Video Outline — 3:00 max (penalty above 3:00: 0.25 marks / 10 s)

Target runtime **2:45**. One continuous screen recording of the dashboard with
picture-in-picture presenter; rehearse against a timer.

| Clock | Beat | On screen | Script cue |
|---|---|---|---|
| 0:00–0:15 | Hook | Dashboard idle, NORMAL | "A pinhole breach 10 km out and 2 km down. DEEPWATCH detects it, locates it to the metre, and isolates it — in seconds, automatically." |
| 0:15–0:40 | Architecture | Architecture slide (from report §1) | "Three layers: a stream simulator replays organizer telemetry at 100 ms cadence; a pure edge analytics engine sees one sample at a time — never the file; a WebSocket bus feeds the digital twin. The engine is identical for the development and blind datasets — nothing is hard-coded." |
| 0:40–1:20 | Live detection | Stream dev dataset at 10×; inlet front hits | "Baselines learned from the data itself; every threshold is a multiple of the measured noise floor. Rate + CUSUM detectors agree, a sustained-deviation check confirms — t_in 2.40 s. The status flag column? Quarantined at the loader. Never used." |
| 1:20–1:50 | Localization + response | Outlet front, NPW panel fills, valves close in 3D | "Outlet front at 7.60 s. Δt 5.2 s into X = (L − CΔt)/2: 2,400 metres — Segment 2. Health tiers go orange, then critical — and the engine executes virtual isolation itself. No clicks." |
| 1:50–2:15 | Generalization proof | Upload a *just-generated* blind file; run sweep table | "Proof it generalizes: our simulator invents scenarios on the spot. 33 unseen leaks: 33 detected, zero metres mean error. Eight no-leak controls, zero false alarms — that's BLIND_07 covered." |
| 2:15–2:35 | Differentiators | AI score, decay forecast, incident report | "An IsolationForest second opinion trained per-dataset, time-to-critical countdowns, and a one-click incident report — timeline, calculation, sign-off — straight from the recorded run." |
| 2:35–2:45 | Close | 3D twin wide shot, ISOLATED state | "Detect, analyze, localize, visualize, respond — an engine for unknown scenarios, not one dataset. DEEPWATCH." |

Recording notes
- Use replay speed 10× for the detection beat, pause stream during the NPW
  close-up so numbers are static on screen.
- Keep alarm audio ON — it lands well on video.
- Capture the sweep table (`python -m scripts.run_sweep`) in a terminal with
  enlarged font.
