/* DEEPWATCH dashboard application — WebSocket client + UI orchestration. */

import { StripChart } from "/static/charts.js";
import { initSchematic } from "/static/schematic.js";
import { initScene } from "/static/scene3d.js";

const $ = (id) => document.getElementById(id);
const TIER_LABEL = { GREEN: "HEALTHY", YELLOW: "CAUTION", ORANGE: "DEGRADED", RED: "CRITICAL" };

// ---------------------------------------------------------------- state
const S = {
  cfg: { length_m: 10000, wave_speed_ms: 1000, speeds: [1, 2, 5, 10, 25, 50] },
  ts: [], pin: [], pout: [], bin: [], bout: [],
  last: null,            // last tick
  running: false,
  finished: false,
  speed: 5,
  eventsSeen: 0,
  datasetEntries: {},    // id -> {id, name, sheet, label}
  lastWorkbook: null,    // most recent multi-sheet workbook (filename)
  muted: localStorage.getItem("dw-muted") === "1",
};

// ---------------------------------------------------------------- UI modules
const chartIn = new StripChart($("chart-inlet"), $("tip-inlet"),
  { color: getComputedStyle(document.body).getPropertyValue("--inlet").trim() || "#3987e5", label: "inlet" });
const chartOut = new StripChart($("chart-outlet"), $("tip-outlet"),
  { color: getComputedStyle(document.body).getPropertyValue("--outlet").trim() || "#d95926", label: "outlet" });
const schematic = initSchematic($("schematic"), S.cfg.length_m);
const scene = initScene($("viewport"), S.cfg.length_m);

// ---------------------------------------------------------------- websocket
let ws, wsRetry = 0;
connect();

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { wsRetry = 0; };
  ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
  ws.onclose = () => {
    setTimeout(connect, Math.min(4000, 300 * 2 ** wsRetry++));
  };
}
setInterval(() => { if (ws?.readyState === 1) ws.send("ping"); }, 20000);

function handleMessage(msg) {
  if (msg.type === "init") {
    S.cfg = msg.config;
    S.speed = msg.speed;
    S.running = msg.running;
    S.finished = msg.finished;
    resetArrays();
    $("event-log").innerHTML = "";
    S.eventsSeen = 0;
    for (const t of msg.ticks) ingestTick(t, true);
    for (const e of msg.events) logEvent(e);
    if (msg.dataset) {
      const sel = $("dataset-select");
      if (sel.value !== msg.dataset.id) refreshDatasets(msg.dataset.id);
    }
    buildSpeedButtons();
    syncTransport();
    fullRefresh();
  } else if (msg.type === "batch") {
    for (const t of msg.ticks) ingestTick(t, false);
    scheduleRefresh();
  } else if (msg.type === "finished") {
    S.running = false; S.finished = true;
    syncTransport();
    toast("Stream complete — dataset fully processed");
  }
}

function resetArrays() {
  S.ts = []; S.pin = []; S.pout = []; S.bin = []; S.bout = [];
  S.last = null;
  chartIn.setSeries(S.ts, S.pin, S.bin); chartIn.clear();
  chartOut.setSeries(S.ts, S.pout, S.bout); chartOut.clear();
  scene.setLeak(null); scene.setIsolation(null);
  scene.setSegments(["GREEN", "GREEN", "GREEN", "GREEN", "GREEN"]);
  schematic.update({
    segments: Array.from({ length: 5 }, () => ({ tier: "GREEN", iso: false, leak: false })),
    leak: null, isolated: false, tIn: null, tOut: null,
  });
  document.body.classList.remove("alarm");
  $("report-btn").disabled = true;
}

function ingestTick(t, replay) {
  S.ts.push(t.t);
  S.pin.push(t.in.p); S.pout.push(t.out.p);
  S.bin.push(t.in.b); S.bout.push(t.out.b);
  S.last = t;
  if (t.ev?.length) {
    for (const e of t.ev) { logEvent(e); if (!replay) reactToEvent(e); }
  }
}

// ---------------------------------------------------------------- rendering
let refreshQueued = false;
function scheduleRefresh() {
  if (refreshQueued) return;
  refreshQueued = true;
  requestAnimationFrame(() => { refreshQueued = false; fullRefresh(); });
}

setInterval(() => { chartIn.dirty = true; chartOut.dirty = true; }, 400);
(function paint() { chartIn.render(); chartOut.render(); requestAnimationFrame(paint); })();

function resetPanels() {
  // complete visual clear: baseline info, NPW results, AI layer, forecast,
  // KPIs — replaying the same file must start from exactly this state
  for (const id of ["kpi-inlet-p", "kpi-outlet-p"]) $(id).textContent = "—";
  for (const id of ["kpi-inlet-ratio", "kpi-outlet-ratio"]) $(id).textContent = "—";
  for (const id of ["kpi-inlet-tier", "kpi-outlet-tier"]) {
    $(id).textContent = "—"; $(id).className = "tier-chip";
  }
  for (const id of ["npw-tin", "npw-tout", "npw-dt", "npw-sev"]) $(id).textContent = "—";
  $("npw-x-in").textContent = "— —";
  $("npw-x-out").textContent = "— —";
  $("npw-dual").classList.remove("located");
  $("npw-warn").hidden = true;
  $("npw-seg").textContent = "awaiting transient arrivals at both stations";
  $("npw-eq").textContent = "";
  $("npw-tevent").textContent = "—";
  $("npw-sum").textContent = "—";
  for (const id of ["sig-in", "sig-out", "thr-in", "thr-out", "base-in", "base-out"])
    $(id).textContent = "—";
  $("ml-mode").textContent = "AI layer: training on stable baseline window…";
  $("ml-bar").style.width = "0%";
  $("ml-val").textContent = "—";
  $("forecast-body").className = "forecast-idle";
  $("forecast-body").textContent = "no active leak — forecasting armed";
  $("inlet-chart-side").textContent = "";
  $("outlet-chart-side").textContent = "";
  $("ref-flag-note").textContent = "";
  $("twin-hint").textContent = "drag to orbit · scroll to zoom";
  $("log-count").textContent = "";
  $("sim-clock").textContent = "00:00.0";
}

function fullRefresh() {
  const t = S.last;
  chartIn.dirty = chartOut.dirty = true;
  if (!t) { updateAnnunciator("NORMAL"); updateStepper(null); resetPanels(); return; }

  // clocks
  $("sim-clock").textContent = fmtClock(t.t);

  // KPI tiles
  setKpi("inlet", t.in);
  setKpi("outlet", t.out);

  // chart side notes + markers (baseline learned from stable telemetry)
  const bInfo = (s) => s.ph === "WARMUP"
    ? "learning baseline from telemetry…"
    : `baseline ${s.b.toFixed(2)} (n=${s.bn}${s.bst ? "" : ", provisional"})` +
      ` · σ ${s.sg.toFixed(3)} · ${s.ph}`;
  $("inlet-chart-side").textContent = bInfo(t.in);
  $("outlet-chart-side").textContent = bInfo(t.out);
  chartIn.setMarkers(t.in.arr != null ? [{ t: t.in.arr, label: "t_in" }] : []);
  chartOut.setMarkers(t.out.arr != null ? [{ t: t.out.arr, label: "t_out" }] : []);

  // NPW panel
  $("npw-tin").textContent = t.in.arr != null ? t.in.arr.toFixed(2) + " s" : "—";
  $("npw-tout").textContent = t.out.arr != null ? t.out.arr.toFixed(2) + " s" : "—";
  $("npw-dt").textContent = t.leak?.delta_t != null ? fmtSigned(t.leak.delta_t) + " s" : "—";
  $("npw-sev").textContent = t.sev ?? "—";
  if (t.leak && t.leak.valid) {
    const L = S.cfg.length_m, C = S.cfg.wave_speed_ms;
    $("npw-x-in").textContent = Math.round(t.leak.x_m).toLocaleString() + " m";
    $("npw-x-out").textContent = Math.round(t.leak.x_out_m).toLocaleString() + " m";
    $("npw-dual").classList.add("located");
    $("npw-seg").innerHTML =
      `Segment ${t.leak.segment} <span class="mono">| ${t.leak.segment_range}</span>` +
      `<span class="tier-chip tier-RED">LEAK</span>`;
    $("npw-warn").hidden = t.leak.consistency_ok !== false;
    $("npw-eq").textContent =
      `X_in = (${L.toLocaleString()} − ${C.toLocaleString()} × ${fmtSigned(t.leak.delta_t)}) / 2 = ` +
      `${Math.round(t.leak.x_m).toLocaleString()} m · ` +
      `X_out = (${L.toLocaleString()} + ${C.toLocaleString()} × ${fmtSigned(t.leak.delta_t)}) / 2 = ` +
      `${Math.round(t.leak.x_out_m).toLocaleString()} m`;
    $("npw-tevent").textContent =
      t.leak.t_event != null ? t.leak.t_event.toFixed(2) + " s" : "—";
    $("npw-sum").textContent =
      `${Math.round(t.leak.x_m + t.leak.x_out_m).toLocaleString()} m = L ` +
      (t.leak.consistency_ok === false ? "✗" : "✓");
  } else if (t.leak && t.leak.valid === false) {
    $("npw-x-in").textContent = "INVALID";
    $("npw-x-out").textContent = "INVALID";
    $("npw-dual").classList.remove("located");
    $("npw-warn").hidden = true;
    $("npw-seg").textContent =
      "Δt outside physical bounds — transients not correlated, no localization";
    $("npw-eq").textContent = "";
    $("npw-tevent").textContent = "—";
    $("npw-sum").textContent = "—";
  } else {
    $("npw-x-in").textContent = "— —";
    $("npw-x-out").textContent = "— —";
    $("npw-dual").classList.remove("located");
    $("npw-warn").hidden = true;
    $("npw-seg").textContent = "awaiting transient arrivals at both stations";
    $("npw-eq").textContent = "";
    $("npw-tevent").textContent = "—";
    $("npw-sum").textContent = "—";
  }

  // edge analytics (thresholds in bar/s from actual timestamp spacing)
  $("sig-in").textContent = t.in.sg.toFixed(3) + " bar";
  $("sig-out").textContent = t.out.sg.toFixed(3) + " bar";
  $("thr-in").textContent = "−" + t.in.th.toFixed(2) + " bar/s";
  $("thr-out").textContent = "−" + t.out.th.toFixed(2) + " bar/s";
  $("base-in").textContent = t.in.ph === "WARMUP" ? "learning…"
    : `${t.in.b.toFixed(2)} bar (n=${t.in.bn})`;
  $("base-out").textContent = t.out.ph === "WARMUP" ? "learning…"
    : `${t.out.b.toFixed(2)} bar (n=${t.out.bn})`;
  if (t.ml != null) {
    $("ml-mode").textContent =
      `AI layer: frozen after baseline training (n=${t.ml.n_train}) · advisory`;
    $("ml-bar").style.width = Math.min(100, t.ml.pct) + "%";
    // alert judgement scales to this dataset's calibrated ceiling N/(N+1)
    const alertAt = Math.min(95, (t.ml.ceiling ?? 100) * 0.98);
    $("ml-val").textContent = "p" + t.ml.pct.toFixed(1) +
      (t.ml.pct >= alertAt ? " · anomalous" : " · nominal");
  } else {
    $("ml-mode").textContent = "AI layer: training on stable baseline window…";
    $("ml-bar").style.width = "0%";
    $("ml-val").textContent = "—";
  }

  // forecast
  renderForecast(t.fc, t.t);

  // schematic + 3D — segments carry GLOBAL line health (only the two
  // boundary sensors measure pressure; nothing per-segment is implied)
  const validLeak = t.leak && t.leak.valid ? t.leak : null;
  schematic.update({
    segments: t.seg.map((s) => ({ tier: s.tier, iso: s.iso, leak: s.leak })),
    leak: validLeak, isolated: t.iso,
    tIn: t.in.arr, tOut: t.out.arr,
  });
  scene.setSegments(t.seg.map((s) => s.tier));
  scene.setLeak(validLeak ? validLeak.x_m : null, validLeak);
  scene.setIsolation(t.iso ? (validLeak?.segment ?? null) : null);
  $("twin-hint").textContent =
    `LINE HEALTH: ${t.gt} (worst of PT-001/PT-002) · drag to orbit`;

  // reference flag (dev dataset only) — displayed, never used
  $("ref-flag-note").textContent = t.ref_flag
    ? `dataset Status Flag (reference only — NOT used by detection): ${t.ref_flag}`
    : "";

  updateAnnunciator(t.st);
  updateStepper(t.stg);

  document.body.classList.toggle("alarm", ALARM_STATES.includes(t.st));
  $("report-btn").disabled = S.ts.length === 0;
}

function setKpi(name, s) {
  $(`kpi-${name}-p`).textContent = s.p.toFixed(2);
  $(`kpi-${name}-ratio`).textContent = (s.r * 100).toFixed(1) + "% of baseline";
  const chip = $(`kpi-${name}-tier`);
  chip.textContent = TIER_LABEL[s.tier];
  chip.className = "tier-chip tier-" + s.tier;
}

const ALARM_STATES = ["LEAK_CONFIRMED", "LOCALIZED", "CRITICAL", "ISOLATED"];

function updateAnnunciator(state) {
  const el = $("annunciator"), txt = $("annunciator-text");
  el.className = "annunciator";
  if (state === "LEAK_CONFIRMED") { el.classList.add("state-leak"); txt.textContent = "⚠ LEAK CONFIRMED"; }
  else if (state === "LOCALIZED") { el.classList.add("state-leak"); txt.textContent = "⚠ LEAK CONFIRMED — LOCALIZED"; }
  else if (state === "CRITICAL") { el.classList.add("state-leak"); txt.textContent = "🟥 CRITICAL — RED HEALTH"; }
  else if (state === "ISOLATED") { el.classList.add("state-isolated"); txt.textContent = "⛔ SEGMENT ISOLATED — ALARM ACTIVE"; }
  else if (state === "ANOMALY_SUSPECTED") { el.classList.add("state-watch"); txt.textContent = "ANOMALY SUSPECTED"; }
  else { el.classList.add("state-normal"); txt.textContent = "SYSTEM NORMAL"; }
}

function updateStepper(stg) {
  const order = ["detect", "analyze", "localize", "visualize", "respond"];
  const done = order.map((k) => !!(stg && stg[k] != null));
  const firstPending = done.indexOf(false);
  order.forEach((name, i) => {
    const el = document.querySelector(`.step[data-step="${name}"]`);
    el.classList.toggle("done", done[i]);
    el.classList.toggle("step-alarm", name === "respond" && done[i]);
    el.classList.toggle("active", S.running && i === firstPending);
    el.querySelector(".step-t").textContent =
      done[i] ? `t+${stg[name].toFixed(1)}s` : "";
  });
}

function renderForecast(fc, now) {
  const body = $("forecast-body");
  if (!fc) {
    body.className = "forecast-idle";
    body.textContent = S.last?.st === "ISOLATED"
      ? "segment isolated — decay containment in effect"
      : "no active leak — forecasting armed";
    return;
  }
  body.className = "";
  const rows = [];
  for (const [sensor, color] of [["inlet", "var(--inlet)"], ["outlet", "var(--outlet)"]]) {
    for (const [key, label, frac] of [["caution_80", "→ DEGRADED (<80%)", 0.8],
                                      ["critical_60", "→ CRITICAL (<60%)", 0.6]]) {
      const v = fc[sensor]?.[key];
      let eta, cls = "";
      if (v === 0) { eta = "crossed"; cls = "now"; }
      else if (v == null) { eta = "—"; }
      else { eta = "T−" + v.toFixed(1) + " s"; cls = v < 5 ? "now" : ""; }
      rows.push(`<div class="fc-row"><i class="sw" style="background:${color}"></i>` +
        `<span class="fc-what">${sensor.toUpperCase()} ${label}</span>` +
        `<span class="fc-eta ${cls}">${eta}</span></div>`);
    }
  }
  body.innerHTML = rows.join("");
}

// ---------------------------------------------------------------- events
function logEvent(e) {
  S.eventsSeen++;
  const log = $("event-log");
  const row = document.createElement("div");
  row.className = "log-row ev-" + e.kind;
  row.innerHTML = `<span class="log-t">${e.t.toFixed(2)}s</span>` +
    `<span class="log-msg">${escapeHtml(e.message)}</span>`;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  $("log-count").textContent = S.eventsSeen + " events";
  $("report-btn").disabled = false;
}

function reactToEvent(e) {
  if (e.kind === "LEAK_CONFIRMED") { sound("leak"); toast("⚠ LEAK CONFIRMED — correlated transients at both stations"); }
  else if (e.kind === "VIRTUAL_ISOLATION") { sound("isolation"); toast("⛔ AUTOMATIC VIRTUAL ISOLATION EXECUTED"); }
  else if (e.kind === "CRITICAL_CONDITION") { toast("🟥 CRITICAL — sustained pressure below 60% of baseline"); }
  else if (e.kind === "LEAK_LOCALIZED") { toast("Leak localized: " + Math.round(e.x_m).toLocaleString() + " m from inlet (Segment " + e.segment + ")"); }
  else if (e.kind === "LOCALIZATION_INVALID") { toast("⚠ Transients not correlated — localization invalid"); }
}

// ---------------------------------------------------------------- transport
async function refreshDatasets(selectId) {
  const r = await fetch("/api/datasets").then((r) => r.json());
  const sel = $("dataset-select");
  S.datasetEntries = {};
  const chosen = selectId ?? r.loaded?.id;
  sel.innerHTML = `<option value="">— select dataset / scenario —</option>` +
    r.datasets.map((d) => {
      S.datasetEntries[d.id] = d;
      const on = d.id === chosen ? " selected" : "";
      return `<option value="${escapeHtml(d.id)}"${on}>${escapeHtml(d.label)}</option>`;
    }).join("");
}

function currentWorkbook() {
  // workbook for "Run all blind sheets": the last uploaded multi-sheet
  // workbook, else the workbook of the selected sheet entry, else any
  const entries = Object.values(S.datasetEntries).filter((d) => d.sheet);
  if (S.lastWorkbook && entries.some((d) => d.name === S.lastWorkbook)) {
    return S.lastWorkbook;
  }
  const sel = S.datasetEntries[$("dataset-select").value];
  if (sel?.sheet) return sel.name;
  return entries.length ? entries[0].name : null;
}

function buildSpeedButtons() {
  const g = $("speed-group");
  g.innerHTML = "";
  for (const sp of S.cfg.speeds) {
    const b = document.createElement("button");
    b.textContent = sp + "×";
    b.classList.toggle("on", sp === S.speed);
    b.onclick = () => { S.speed = sp; control({ speed: sp }); buildSpeedButtons(); };
    g.appendChild(b);
  }
}

function syncTransport() {
  const play = $("play-btn");
  play.textContent = S.running ? "❚❚ Pause" : (S.finished ? "✓ Complete" : "▶ Stream");
  play.classList.toggle("running", S.running);
  play.disabled = S.finished;
}

async function control(body) {
  const r = await fetch("/api/control", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then((r) => r.json());
  S.running = r.running; S.finished = r.finished;
  syncTransport();
}

function datasetToast(ds) {
  // validation summary per the ingestion spec
  const v = ds.validation || {};
  const dur = v.duration_s != null ? ` · Duration: T+${v.duration_s.toFixed(1)} s` : "";
  const lines = [
    `<b>✓ Dataset loaded</b> — ${escapeHtml(ds.label || ds.name)}`,
    `${(v.samples ?? ds.samples).toLocaleString()} samples · ` +
    `Sampling interval: ${v.sample_dt_ms ?? Math.round(ds.sample_dt * 1000)} ms${dur}`,
    `Inlet/outlet pressure channels detected` +
    (v.channels ? ` (“${escapeHtml(v.channels.inlet)}”, “${escapeHtml(v.channels.outlet)}”)` : ""),
  ];
  if (v.status_flag_present) lines.push("Status Flag ignored (display-only, never used for detection)");
  for (const w of v.warnings || []) lines.push("⚠ " + escapeHtml(w));
  toast(lines.join("<br>"), { html: true, ms: 6500 });
}

$("play-btn").onclick = () => control({ action: S.running ? "pause" : "start" });
$("reset-btn").onclick = () => control({ action: "reset" });
$("dataset-select").onchange = async (e) => {
  if (!e.target.value) return;
  const entry = S.datasetEntries[e.target.value] || { name: e.target.value, sheet: null };
  const r = await fetch("/api/load", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: entry.name, sheet: entry.sheet }) }).then((r) => r.json());
  if (r.error) toast("✗ " + r.error);
  else datasetToast(r.dataset);
};
$("upload-btn").onclick = () => $("upload-input").click();
$("upload-input").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  toast("Uploading " + f.name + "…");
  const r = await fetch("/api/upload", { method: "POST", body: fd }).then((r) => r.json());
  if (r.error) {
    toast("✗ " + r.error);
  } else if (r.multi_sheet) {
    // several scenarios: populate the dropdown, nothing starts until the
    // user picks a worksheet
    S.lastWorkbook = r.workbook;
    await refreshDatasets();
    toast(`<b>${escapeHtml(r.message)}</b><br>Select a scenario to begin<br>` +
      `<span style="color:var(--muted)">${r.sheets.map(escapeHtml).join(" · ")}</span>`,
      { html: true, ms: 8000 });
  } else {
    datasetToast(r.dataset);
    refreshDatasets(r.dataset.id);
  }
  e.target.value = "";
};
$("report-btn").onclick = () => window.open("/api/report", "_blank");

// ---- batch evaluation (developer mode, offline, independent engines) ----
$("batch-btn").onclick = () => {
  const wb = currentWorkbook();
  $("batch-sheets-btn").disabled = !wb;
  $("batch-workbook-note").textContent = wb
    ? `workbook: ${wb}`
    : "no multi-sheet workbook available — upload one via ⬆ Blind dataset";
  if (!$("batch-body").innerHTML) {
    $("batch-body").innerHTML =
      `<div style="color:var(--muted);padding:8px 4px">Choose files, or run every
       valid worksheet of the evaluation workbook.</div>`;
  }
  $("batch-modal").hidden = false;
};
$("batch-close").onclick = () => { $("batch-modal").hidden = true; };
$("batch-modal").onclick = (e) => { if (e.target === $("batch-modal")) $("batch-modal").hidden = true; };
$("batch-files-btn").onclick = () => $("batch-input").click();
$("batch-input").onchange = async (e) => {
  const files = [...e.target.files];
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  $("batch-modal").hidden = false;
  $("batch-body").innerHTML =
    `<div style="color:var(--muted);padding:14px 4px">processing ${files.length} file(s) through the production inference path…</div>`;
  try {
    const r = await fetch("/api/batch_eval", { method: "POST", body: fd }).then((r) => r.json());
    renderBatchResults(r.results || []);
  } catch (err) {
    $("batch-body").innerHTML = `<div class="bad" style="padding:14px 4px">batch evaluation failed: ${escapeHtml(String(err))}</div>`;
  }
  e.target.value = "";
};
$("batch-sheets-btn").onclick = async () => {
  const wb = currentWorkbook();
  if (!wb) return;
  $("batch-body").innerHTML =
    `<div style="color:var(--muted);padding:14px 4px">running every valid worksheet of ${escapeHtml(wb)} — fresh engine per sheet…</div>`;
  try {
    const r = await fetch("/api/batch_sheets", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: wb }) }).then((r) => r.json());
    if (r.error) {
      $("batch-body").innerHTML = `<div class="bad" style="padding:14px 4px">✗ ${escapeHtml(r.error)}</div>`;
    } else {
      renderBatchResults(r.results || []);
    }
  } catch (err) {
    $("batch-body").innerHTML = `<div class="bad" style="padding:14px 4px">batch evaluation failed: ${escapeHtml(String(err))}</div>`;
  }
};

function renderBatchResults(rows) {
  const num = (v, nd = 2) =>
    v == null ? "—" : (typeof v === "number" ? v.toFixed(nd) : v);
  const yn = (v) => v ? `<span class="yes">yes</span>` : `<span class="no">no</span>`;
  const header = ["Dataset", "Leak detected?", "t_in (s)", "t_out (s)", "Δt (s)",
                  "X from inlet (m)", "X from outlet (m)", "Segment",
                  "Det. latency (s)", "Critical", "Final severity",
                  "Isolation executed"];
  const body = rows.map((r) => {
    const label = r.dataset || r.file || "—";
    if (r.error) {
      return `<tr class="err"><td>${escapeHtml(label)}</td>` +
             `<td colspan="11">✗ ${escapeHtml(r.error)}</td></tr>`;
    }
    const xin = r.x_m != null ? Math.round(r.x_m).toLocaleString()
      : (r.loc_invalid ? "INVALID" : "—");
    const xout = r.x_out_m != null ? Math.round(r.x_out_m).toLocaleString() : "—";
    return `<tr><td>${escapeHtml(label)}</td><td>${yn(r.leak_detected)}</td>` +
      `<td>${num(r.t_in)}</td><td>${num(r.t_out)}</td><td>${num(r.delta_t)}</td>` +
      `<td>${xin}</td><td>${xout}</td><td>${r.segment != null ? "S" + r.segment : "—"}</td>` +
      `<td>${num(r.detection_latency_s)}</td>` +
      `<td>${yn(r.critical_reached)}</td>` +
      `<td>${r.severity ?? "—"}</td><td>${yn(r.isolated)}</td></tr>`;
  }).join("");
  $("batch-body").innerHTML =
    `<table><thead><tr>${header.map((h) => `<th>${h}</th>`).join("")}</tr></thead>` +
    `<tbody>${body}</tbody></table>`;
}

// ---------------------------------------------------------------- sound
$("mute-btn").textContent = S.muted ? "🔇" : "🔊";
$("mute-btn").onclick = () => {
  S.muted = !S.muted;
  localStorage.setItem("dw-muted", S.muted ? "1" : "0");
  $("mute-btn").textContent = S.muted ? "🔇" : "🔊";
};

let audioCtx;
function sound(kind) {
  if (S.muted) return;
  try {
    audioCtx = audioCtx || new AudioContext();
    const seq = kind === "isolation"
      ? [[880, 0, 0.18], [660, 0.22, 0.18], [880, 0.44, 0.18], [660, 0.66, 0.3]]
      : [[740, 0, 0.14], [740, 0.2, 0.14], [740, 0.4, 0.22]];
    for (const [f, at, dur] of seq) {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = "square"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, audioCtx.currentTime + at);
      g.gain.exponentialRampToValueAtTime(0.12, audioCtx.currentTime + at + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + at + dur);
      o.connect(g).connect(audioCtx.destination);
      o.start(audioCtx.currentTime + at);
      o.stop(audioCtx.currentTime + at + dur + 0.05);
    }
  } catch { /* audio unavailable */ }
}

// ---------------------------------------------------------------- helpers
function fmtClock(t) {
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${String(m).padStart(2, "0")}:${s < 10 ? "0" : ""}${s.toFixed(1)}`;
}
function fmtSigned(v) { return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2); }
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
let toastTimer;
function toast(msg, opts = {}) {
  const el = $("toast");
  if (opts.html) el.innerHTML = msg; else el.textContent = msg;
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = "none"; }, opts.ms ?? 3600);
}

refreshDatasets();
