/* DEEPWATCH dashboard application — WebSocket client + UI orchestration. */

import { StripChart } from "/static/charts.js";
import { initSchematic } from "/static/schematic.js";
import { initScene } from "/static/scene3d.js";

const $ = (id) => document.getElementById(id);
const TIER_LABEL = { GREEN: "HEALTHY", YELLOW: "CAUTION", ORANGE: "DEGRADED", RED: "CRITICAL" };

// ---------------------------------------------------------------- state
const S = {
  cfg: { mode: "competition", length_m: 10000, wave_speed_ms: 1000,
         segment_len_m: 2000, num_segments: 5, speeds: [1, 2, 5, 10, 25, 50] },
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
let schematic = initSchematic($("schematic"), S.cfg);
const scene = initScene($("viewport"), S.cfg);

function applyConfig(cfg) {
  const changed = cfg.length_m !== S.cfg.length_m
    || cfg.segment_len_m !== S.cfg.segment_len_m
    || cfg.num_segments !== S.cfg.num_segments;
  S.cfg = cfg;
  const kmL = cfg.length_m / 1000, kmS = cfg.segment_len_m / 1000;
  $("param-sub").textContent =
    `Subsea Pipeline Integrity Twin · L ${kmL.toLocaleString()} km · ` +
    `C ${cfg.wave_speed_ms.toLocaleString()} m/s · ` +
    `${cfg.num_segments} segments × ${+kmS.toFixed(2)} km`;
  $("schematic-title").textContent =
    `PIPELINE SCHEMATIC — ${cfg.num_segments} LOGICAL SEGMENTS`;
  const chip = $("mode-chip");
  if (cfg.mode === "engineering") {
    chip.textContent = `⚙ ENGINEERING — ${kmL.toLocaleString()} km`;
    chip.classList.add("engineering");
  } else {
    chip.textContent = "🔒 COMPETITION — locked";
    chip.classList.remove("engineering");
  }
  if (changed) {
    schematic = initSchematic($("schematic"), cfg);   // rebuild 2D
    scene.rebuild(cfg);                               // rebuild 3D line
  }
}

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
    applyConfig(msg.config);
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
  const n = S.cfg.num_segments || 5;
  scene.setSegments(Array.from({ length: n }, () => "GREEN"));
  schematic.update({
    segments: Array.from({ length: n }, () => ({ tier: "GREEN", iso: false, leak: false })),
    leak: null, isolated: false, tIn: null, tOut: null,
  });
  document.body.classList.remove("alarm");
  $("report-btn").disabled = true;
  $("report-btn").classList.remove("ready");
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
  // complete visual clear — replaying the same file must start from
  // exactly this state
  for (const side of ["in", "out"]) {
    for (const k of ["p", "ratio", "dp", "dev", "base", "sig", "thr"])
      $(`asq-${side}-${k}`).textContent = "—";
    const chip = $(`asq-${side}-tier`);
    chip.textContent = "—"; chip.className = "tier-chip";
    const st = $(`asq-${side}-state`);
    st.textContent = "—"; st.className = "asq-state learning";
  }
  for (const id of ["npw-tin", "npw-tout", "npw-dt", "npw-sev"]) $(id).textContent = "—";
  $("npw-sev").classList.remove("grad-alarm");
  $("npw-x-in").textContent = "— —";
  $("npw-x-out").textContent = "— —";
  $("npw-dual").classList.remove("located");
  $("npw-warn").hidden = true;
  $("npw-seg").textContent = "awaiting transient arrivals at both stations";
  $("npw-eq").textContent = "";
  $("npw-tevent").textContent = "—";
  $("npw-sum").textContent = "—";
  $("ai-status").textContent = "—";
  $("ai-status").className = "ai-status";
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

  // ADAPTIVE SIGNAL QUALITY — primary engineering readouts
  setAsq("in", t.in);
  setAsq("out", t.out);

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
  $("npw-sev").classList.toggle("grad-alarm", t.sev === "CRITICAL");
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
      "INVALID LOCALIZATION — timing inconsistent with configured pipeline " +
      `(|Δt| > L/C = ${(S.cfg.length_m / S.cfg.wave_speed_ms).toFixed(1)} s)`;
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

  // AI layer — advisory, text-first; raw percentile lives in Engineering Detail
  if (t.ml && t.ml.unavailable) {
    // failure-safe: core detection continues, AI simply reports absent
    const ai = $("ai-status");
    ai.textContent = "UNAVAILABLE";
    ai.className = "ai-status unavailable";
    $("ml-mode").textContent =
      "AI corroboration unavailable — deterministic detector active.";
    $("ml-bar").style.width = "0%";
    $("ml-val").textContent = "—";
  } else if (t.ml != null) {
    const alertAt = Math.min(95, (t.ml.ceiling ?? 100) * 0.98);
    const status = t.ml.pct >= alertAt ? "HIGH"
      : t.ml.pct >= alertAt * 0.85 ? "ELEVATED" : "NORMAL";
    const ai = $("ai-status");
    ai.textContent = status;
    ai.className = "ai-status " + status.toLowerCase();
    $("ml-mode").textContent =
      `frozen after baseline training (n=${t.ml.n_train}) · advisory`;
    $("ml-bar").style.width = Math.min(100, t.ml.pct) + "%";
    $("ml-val").textContent = "p" + t.ml.pct.toFixed(1) +
      (status === "HIGH" ? " · anomalous" : " · nominal");
  } else {
    $("ai-status").textContent = "calibrating";
    $("ai-status").className = "ai-status";
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
    segments: t.seg.map((s) => ({ tier: s.tier, iso: s.iso, leak: s.leak,
                                  lo: s.lo, hi: s.hi })),
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

const SIGNAL_STATE = {
  WARMUP: ["LEARNING BASELINE", "learning"],
  MONITORING: ["NORMAL", ""],
  CANDIDATE: ["TRANSIENT CANDIDATE", "candidate"],
  CONFIRMED: ["TRANSIENT CONFIRMED", "confirmed"],
};

function setAsq(side, s) {
  $(`asq-${side}-p`).textContent = s.p.toFixed(2);
  $(`asq-${side}-ratio`).textContent = (s.r * 100).toFixed(1) + "%";
  const chip = $(`asq-${side}-tier`);
  chip.textContent = TIER_LABEL[s.tier];
  chip.className = "tier-chip tier-" + s.tier;
  $(`asq-${side}-dp`).textContent = (s.dp >= 0 ? "+" : "−") + Math.abs(s.dp).toFixed(2);
  const dev = s.p - s.b;
  $(`asq-${side}-dev`).textContent = s.ph === "WARMUP" ? "—"
    : (dev >= 0 ? "+" : "−") + Math.abs(dev).toFixed(2) + " bar";
  $(`asq-${side}-base`).textContent = s.ph === "WARMUP"
    ? "learning…" : `${s.b.toFixed(2)} bar (n=${s.bn}${s.bst ? "" : ", prov."})`;
  $(`asq-${side}-sig`).textContent = s.sg.toFixed(3) + " bar";
  $(`asq-${side}-thr`).textContent = "−" + s.th.toFixed(2) + " bar/s";
  const [label, cls] = SIGNAL_STATE[s.ph] || ["—", "learning"];
  const st = $(`asq-${side}-state`);
  st.textContent = label;
  st.className = "asq-state" + (cls ? " " + cls : "");
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

function renderForecast(fc) {
  const body = $("forecast-body");
  if (!fc) {
    body.className = "forecast-idle";
    body.textContent = "no active leak — forecasting armed";
    return;
  }
  body.className = "";
  const block = (name, color, f) => {
    if (!f) return "";
    const cur = f.ratio != null ? (f.ratio * 100).toFixed(1) + "% baseline" : "—";
    const decay = f.slope_bar_s != null
      ? "−" + Math.abs(f.slope_bar_s).toFixed(2) + " bar/s" : "—";
    const fmt = (v, label) => {
      if (v === "crossed")
        return `<span class="fc-eta now">${label.toUpperCase()} — crossed</span>`;
      if (typeof v === "number")
        return `<span class="fc-eta ${v < 5 ? "now" : ""}">${label} ETA: ~${v.toFixed(1)} s</span>`;
      return null;
    };
    const parts = [fmt(f.caution_80, "Degraded"),
                   fmt(f.critical_60, "Critical")].filter(Boolean);
    const allCrossed = f.caution_80 === "crossed" && f.critical_60 === "crossed";
    if (!f.trend_ok && !allCrossed) {
      parts.push(`<span class="fc-una">Forecast unavailable — ${
        escapeHtml(f.reason || "no consistent decay trend")}</span>`);
    } else if (f.trend_ok && !parts.length) {
      parts.push(`<span class="fc-una">beyond forecast horizon</span>`);
    }
    return `<div class="fc-block">
      <div class="fc-head"><i class="sw" style="background:${color}"></i><b>${name}</b>
        <span>Current: <b class="mono">${cur}</b></span>
        <span>Decay: <b class="mono">${decay}</b></span></div>
      <div class="fc-etas">${parts.join(" &nbsp;·&nbsp; ")}</div></div>`;
  };
  body.innerHTML = block("INLET", "var(--inlet)", fc.inlet)
                 + block("OUTLET", "var(--outlet)", fc.outlet);
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
  else if (e.kind === "VIRTUAL_ISOLATION") {
    sound("isolation");
    toast("⛔ AUTOMATIC VIRTUAL ISOLATION EXECUTED — incident report (PDF) ready");
    $("report-btn").classList.add("ready");
  }
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
$("report-btn").onclick = () => window.open("/api/report.pdf", "_blank");

// ---------------------------------------------------------------- event history
$("history-btn").onclick = openHistory;
$("history-close").onclick = () => { $("history-modal").hidden = true; };
$("history-modal").onclick = (e) => { if (e.target === $("history-modal")) $("history-modal").hidden = true; };
$("history-clear").onclick = async () => {
  await fetch("/api/history/clear", { method: "POST" });
  openHistory();
};

async function openHistory() {
  $("history-modal").hidden = false;
  $("history-body").innerHTML =
    `<div style="color:var(--muted);padding:10px 4px">loading…</div>`;
  try {
    const r = await fetch("/api/history").then((r) => r.json());
    renderHistory(r.stats, r.records || []);
  } catch (err) {
    $("history-body").innerHTML =
      `<div class="bad" style="padding:10px 4px">failed to load history: ${escapeHtml(String(err))}</div>`;
  }
}

function renderHistory(stats, records) {
  const tile = (label, value, note = "") =>
    `<div class="hist-tile"><label>${label}</label><b>${value}</b>` +
    (note ? ` <small>${note}</small>` : "") + `</div>`;
  let tiles =
    tile("TOTAL RUNS", stats.total_runs) +
    tile("LEAKS DETECTED", stats.leaks_detected) +
    tile("NO-LEAK RUNS", stats.no_leak_runs) +
    tile("AVG DETECTION LATENCY", stats.avg_detection_latency_s != null
      ? stats.avg_detection_latency_s.toFixed(2) + " s" : "—") +
    tile("ISOLATIONS", stats.isolations);
  if (stats.truth_available) {
    tiles += tile("FALSE ALARMS", stats.false_alarms,
                  "dev answer key · " + stats.judged_runs + " judged");
  }

  const bIn = records.map((r) => r.baseline_in);
  const bOut = records.map((r) => r.baseline_out);
  const nIn = records.map((r) => r.noise_in);
  const nOut = records.map((r) => r.noise_out);
  const SEV = { null: 0, LOW: 1, MAJOR: 2, CRITICAL: 3 };
  const sev = records.map((r) => SEV[r.max_severity] ?? 0);

  const trends = `
    <div class="hist-trends">
      <div class="hist-trend"><h4>SENSOR BASELINE (bar) — <i class="sw" style="background:var(--inlet)"></i> inlet · <i class="sw" style="background:var(--outlet)"></i> outlet</h4>
        ${trendSvg([bIn, bOut], ["var(--inlet)", "var(--outlet)"])}</div>
      <div class="hist-trend"><h4>NOISE σ (bar) — inlet · outlet</h4>
        ${trendSvg([nIn, nOut], ["var(--inlet)", "var(--outlet)"], 3)}</div>
      <div class="hist-trend"><h4>EVENT SEVERITY</h4>
        ${trendSvg([sev], ["var(--serious)"], 0,
                   [[0, "none"], [1, "LOW"], [2, "MAJ"], [3, "CRIT"]])}</div>
      <div class="hist-trend"><h4>LEAK LOCATIONS (position / pipeline length)</h4>
        ${leakStripSvg(records)}</div>
    </div>`;

  const rows = records.slice(-20).reverse().map((r) => {
    const when = (r.timestamp || "").replace("T", " ");
    return `<tr><td>${escapeHtml(String(r.dataset))}</td>` +
      `<td>${when}</td>` +
      `<td>${r.leak_detected ? '<span class="yes">yes</span>' : '<span class="no">no</span>'}</td>` +
      `<td>${r.x_in_m != null ? Math.round(r.x_in_m).toLocaleString() : "—"}</td>` +
      `<td>${r.segment != null ? "S" + r.segment : "—"}</td>` +
      `<td>${r.max_severity ?? "—"}</td>` +
      `<td>${r.detection_latency_s != null ? r.detection_latency_s.toFixed(2) + " s" : "—"}</td>` +
      `<td>${escapeHtml(r.ai_corroboration ?? "—")}</td>` +
      `<td>${r.isolated ? '<span class="yes">yes</span>' : '<span class="no">no</span>'}</td></tr>`;
  }).join("");
  const table = records.length
    ? `<table><thead><tr><th>Dataset</th><th>When</th><th>Leak?</th>
        <th>X (m)</th><th>Seg</th><th>Severity</th><th>Latency</th>
        <th>AI</th><th>Isolated</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div style="color:var(--muted);padding:8px 4px">no completed runs recorded yet — stream a dataset to the end.</div>`;

  $("history-body").innerHTML =
    `<div class="hist-tiles">${tiles}</div>` + trends + table;
}

function trendSvg(seriesList, colors, nd = 1, yTicks = null) {
  const all = seriesList.flat().filter((v) => v != null && isFinite(v));
  if (!all.length) return `<div class="fc-una" style="padding:6px 0">no data yet</div>`;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (yTicks) { lo = Math.min(lo, yTicks[0][0]); hi = Math.max(hi, yTicks[yTicks.length - 1][0]); }
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const span = hi - lo; lo -= span * 0.08; hi += span * 0.08;
  const W = 300, H = 86, L = 36, R = 10, T = 8, B = 16;
  const n = Math.max(...seriesList.map((s) => s.length));
  const X = (i) => n < 2 ? (L + (W - L - R) / 2) : L + (i / (n - 1)) * (W - L - R);
  const Y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
  let g = "";
  const ticks = yTicks || [[lo + span * 0.08, null], [(lo + hi) / 2, null], [hi - span * 0.08, null]];
  for (const [v, lbl] of ticks) {
    g += `<line x1="${L}" y1="${Y(v)}" x2="${W - R}" y2="${Y(v)}" stroke="#1c2739"/>` +
      `<text x="${L - 4}" y="${Y(v) + 3}" text-anchor="end" font-size="8" fill="#7e8ea6">${
        lbl ?? v.toFixed(nd)}</text>`;
  }
  let lines = "";
  seriesList.forEach((s, si) => {
    let d = "", pen = false;
    s.forEach((v, i) => {
      if (v == null || !isFinite(v)) { pen = false; return; }
      d += (pen ? " L" : " M") + X(i).toFixed(1) + " " + Y(v).toFixed(1);
      pen = true;
      lines += `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="2" fill="${colors[si]}"/>`;
    });
    lines += `<path d="${d}" fill="none" stroke="${colors[si]}" stroke-width="1.6"/>`;
  });
  g += `<text x="${W - R}" y="${H - 3}" text-anchor="end" font-size="8" fill="#7e8ea6">run #</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" font-family="system-ui">${g}${lines}</svg>`;
}

function leakStripSvg(records) {
  const pts = records.filter((r) => r.x_in_m != null && r.length_m > 0);
  if (!pts.length) return `<div class="fc-una" style="padding:6px 0">no localized leaks yet</div>`;
  const W = 300, H = 52, L = 14, R = 14, y = 26;
  let g = `<line x1="${L}" y1="${y}" x2="${W - R}" y2="${y}" stroke="#2c3b57" stroke-width="3" stroke-linecap="round"/>`;
  for (const f of [0, 0.25, 0.5, 0.75, 1]) {
    const x = L + f * (W - L - R);
    g += `<line x1="${x}" y1="${y - 5}" x2="${x}" y2="${y + 5}" stroke="#2c3b57"/>` +
      `<text x="${x}" y="${y + 16}" text-anchor="middle" font-size="8" fill="#7e8ea6">${
        f === 0 ? "inlet" : f === 1 ? "outlet" : (f * 100) + "%"}</text>`;
  }
  for (const r of pts) {
    const x = L + (r.x_in_m / r.length_m) * (W - L - R);
    g += `<circle cx="${x.toFixed(1)}" cy="${y}" r="3.4" fill="var(--crit)" opacity="0.8"/>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" font-family="system-ui">${g}</svg>`;
}

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

// ---------------------------------------------------------------- operating mode
$("mode-chip").onclick = () => {
  const eng = S.cfg.mode === "engineering";
  $("mode-eng").checked = eng;
  $("mode-comp").checked = !eng;
  if (eng) {
    $("mode-length").value = S.cfg.length_m / 1000;
    $("mode-wave").value = S.cfg.wave_speed_ms;
    $("mode-segment").value = S.cfg.segment_len_m / 1000;
  }
  syncModeInputs();
  $("mode-modal").hidden = false;
};
$("mode-close").onclick = () => { $("mode-modal").hidden = true; };
$("mode-modal").onclick = (e) => { if (e.target === $("mode-modal")) $("mode-modal").hidden = true; };
$("mode-comp").onchange = syncModeInputs;
$("mode-eng").onchange = syncModeInputs;
for (const id of ["mode-length", "mode-wave", "mode-segment"])
  $(id).oninput = updateModePreview;

function syncModeInputs() {
  const eng = $("mode-eng").checked;
  for (const id of ["mode-length", "mode-wave", "mode-segment"])
    $(id).disabled = !eng;
  updateModePreview();
}

function updateModePreview() {
  if (!$("mode-eng").checked) { $("mode-preview").textContent = ""; return; }
  const L = parseFloat($("mode-length").value) || 0;
  const seg = parseFloat($("mode-segment").value) || 0;
  const C = parseFloat($("mode-wave").value) || 0;
  if (L > 0 && seg > 0 && C > 0) {
    const n = Math.max(1, Math.ceil(L / seg - 1e-9));
    const rem = L - (n - 1) * seg;
    $("mode-preview").textContent =
      `→ ${n} dynamic segments · physical |Δt| limit = L/C = ${(L * 1000 / C).toFixed(1)} s` +
      (Math.abs(rem - seg) > 1e-9 ? ` · final segment ${+rem.toFixed(2)} km (remainder)` : "");
  } else {
    $("mode-preview").textContent = "";
  }
}

$("mode-apply").onclick = async () => {
  const mode = $("mode-eng").checked ? "engineering" : "competition";
  const body = { mode };
  if (mode === "engineering") {
    body.length_km = parseFloat($("mode-length").value);
    body.wave_speed_ms = parseFloat($("mode-wave").value);
    body.segment_km = parseFloat($("mode-segment").value);
  }
  const r = await fetch("/api/mode", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then((r) => r.json());
  if (r.error) { toast("✗ " + r.error); return; }
  $("mode-modal").hidden = true;
  toast(mode === "competition"
    ? "🔒 Competition parameters — locked · L 10,000 m · C 1,000 m/s · 5 × 2,000 m"
    : `⚙ Engineering mode — L ${body.length_km} km · C ${body.wave_speed_ms} m/s → ${r.num_segments} segments`,
    { ms: 5000 });
};

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

// ------------------------------------------------- deep-sea cursor parallax
// Purely decorative: transforms only the fixed ambience layers and (very
// slightly) the twin canvas. GPU transforms, rAF with easing, self-stops at
// rest; disabled for reduced-motion, coarse pointers and low-power devices.
(function initParallax() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (matchMedia("(pointer: coarse)").matches) return;
  if ((navigator.hardwareConcurrency || 8) <= 4) return;
  const layers = [
    [document.querySelector(".sea-grad"), 5],
    [document.querySelector(".sea-haze"), 11],
    [document.querySelector(".sea-rays"), 17],
    [document.querySelector(".sea-particles"), 24],
  ].filter(([el]) => el);
  if (!layers.length) return;
  let tx = 0, ty = 0, cx = 0, cy = 0, raf = null;
  addEventListener("pointermove", (e) => {
    tx = e.clientX / innerWidth - 0.5;
    ty = e.clientY / innerHeight - 0.5;
    if (!raf && !document.hidden) raf = requestAnimationFrame(step);
  }, { passive: true });
  function step() {
    cx += (tx - cx) * 0.055;
    cy += (ty - cy) * 0.055;
    for (const [el, amp] of layers) {
      el.style.transform =
        `translate3d(${(-cx * amp).toFixed(2)}px, ${(-cy * amp).toFixed(2)}px, 0)`;
    }
    const cv = document.querySelector("#viewport canvas");
    if (cv) {
      cv.style.transform =
        `translate3d(${(cx * 5).toFixed(2)}px, ${(cy * 3.5).toFixed(2)}px, 0) scale(1.015)`;
    }
    raf = (Math.abs(tx - cx) + Math.abs(ty - cy)) > 0.0008
      ? requestAnimationFrame(step) : null;
  }
})();

refreshDatasets();
