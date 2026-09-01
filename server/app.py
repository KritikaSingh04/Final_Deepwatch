"""DeepWatch server: simulated real-time telemetry replay over WebSocket,
session control REST API, dataset upload, and incident report generation.

Run:  uvicorn server.app:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import tempfile

from engine.engine import AnalyticsEngine, EngineConfig
from engine.npw import (PIPELINE_LENGTH_M, WAVE_SPEED_MS, SEGMENT_LENGTH_M,
                        num_segments_for)
from streaming.loader import (load as load_telemetry, inspect_sheets,
                              LoaderError, MultiSheetWorkbook, TelemetrySet)
from server import history as history_mod
from server.batch import evaluate_path
from server.pdf_report import build_pdf_report
from server.report import build_incident_report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
WEB_DIR = os.path.join(ROOT, "web")

SPEEDS = [1, 2, 5, 10, 25, 50]
FLUSH_INTERVAL = 0.06  # seconds between websocket batch flushes


class Session:
    """One replay session: dataset + engine + replay task + subscribers."""

    def __init__(self):
        self.telemetry: Optional[TelemetrySet] = None
        # COMPETITION MODE (default): locked official parameters, used for
        # all blind datasets. ENGINEERING MODE swaps these for user values.
        self.mode = "competition"
        self.params = {"length_m": PIPELINE_LENGTH_M,
                       "wave_speed_ms": WAVE_SPEED_MS,
                       "segment_len_m": SEGMENT_LENGTH_M}
        self.engine = self._new_engine()
        self.idx = 0
        self.speed = 5
        self.running = False
        self.finished = False
        self.task: Optional[asyncio.Task] = None
        self.clients: set[WebSocket] = set()
        self.ticks: list[dict] = []   # compact ticks kept for late joiners
        self.last_event_id: Optional[str] = None

    def _new_engine(self) -> AnalyticsEngine:
        return AnalyticsEngine(EngineConfig(**self.params))

    def set_mode(self, mode: str, length_m: float, wave_speed_ms: float,
                 segment_len_m: float):
        if mode == "competition":
            self.params = {"length_m": PIPELINE_LENGTH_M,
                           "wave_speed_ms": WAVE_SPEED_MS,
                           "segment_len_m": SEGMENT_LENGTH_M}
        else:
            self.params = {"length_m": length_m,
                           "wave_speed_ms": wave_speed_ms,
                           "segment_len_m": segment_len_m}
        self.mode = mode
        self.reset()   # fresh engine under the new configuration

    # -- lifecycle -----------------------------------------------------
    def load(self, path: str, sheet: Optional[str] = None):
        """Load one file/worksheet. reset() always builds a completely
        fresh AnalyticsEngine, so no state (baseline, noise history,
        thresholds, IsolationForest, arrivals, state machine,
        localization, severity, isolation, events) can leak from one
        scenario into another."""
        self.stop()
        self.telemetry = load_telemetry(path, sheet=sheet)
        self.reset()

    def reset(self):
        self.stop()
        self.engine = self._new_engine()
        self.idx = 0
        self.finished = False
        self.ticks = []
        self.last_event_id = None

    def stop(self):
        self.running = False
        if self.task is not None:
            self.task.cancel()
            self.task = None

    def start(self):
        if self.telemetry is None or self.running or self.finished:
            return
        self.running = True
        self.task = asyncio.get_running_loop().create_task(self._replay_loop())

    # -- replay --------------------------------------------------------
    async def _replay_loop(self):
        try:
            tel = self.telemetry
            dt = tel.sample_dt
            pending: list[dict] = []
            last_flush = time.monotonic()
            while self.running and self.idx < len(tel):
                per_iter = max(1, int(self.speed * FLUSH_INTERVAL / dt))
                for _ in range(per_iter):
                    if self.idx >= len(tel):
                        break
                    pending.append(self._step())
                now = time.monotonic()
                has_events = any(t["ev"] for t in pending)
                if pending and (has_events or now - last_flush >= FLUSH_INTERVAL):
                    await self._broadcast({"type": "batch", "ticks": pending,
                                           "idx": self.idx, "total": len(tel)})
                    pending = []
                    last_flush = now
                await asyncio.sleep(per_iter * dt / self.speed)
            if pending:
                await self._broadcast({"type": "batch", "ticks": pending,
                                       "idx": self.idx, "total": len(tel)})
            if self.idx >= len(tel):
                self.finished = True
                self.running = False
                # EVENT HISTORY: write-after logging only — built from the
                # finished engine's outputs; the engine never reads it, so
                # history cannot influence any current or future detection.
                try:
                    record = history_mod.build_record(
                        self.engine, self.dataset_meta(), self.mode)
                    history_mod.append(record)
                    self.last_event_id = record["event_id"]
                except Exception:
                    pass  # logging must never break the run
                await self._broadcast({"type": "finished",
                                       "summary": self.summary(),
                                       "event_id": self.last_event_id})
        except asyncio.CancelledError:
            pass

    def _step(self) -> dict:
        tel = self.telemetry
        i = self.idx
        tick = self.engine.update(tel.times_s[i], tel.p_in[i], tel.p_out[i])
        compact = _compact_tick(tick)
        if tel.ref_flags is not None:
            compact["ref_flag"] = tel.ref_flags[i]
        self.ticks.append(compact)
        self.idx += 1
        return compact

    # -- messaging -----------------------------------------------------
    async def _broadcast(self, msg: dict):
        dead = []
        payload = json.dumps(msg)
        for ws in self.clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def snapshot(self) -> dict:
        # thin history for late joiners: cap the replayed backlog
        backlog = self.ticks[-4000:]
        return {
            "type": "init",
            "config": {
                "mode": self.mode,
                "length_m": self.params["length_m"],
                "wave_speed_ms": self.params["wave_speed_ms"],
                "segment_len_m": self.params["segment_len_m"],
                "num_segments": num_segments_for(self.params["length_m"],
                                                 self.params["segment_len_m"]),
                "competition": {"length_m": PIPELINE_LENGTH_M,
                                "wave_speed_ms": WAVE_SPEED_MS,
                                "segment_len_m": SEGMENT_LENGTH_M},
                "speeds": SPEEDS,
            },
            "dataset": self.dataset_meta(),
            "speed": self.speed,
            "running": self.running,
            "finished": self.finished,
            "idx": self.idx,
            "total": len(self.telemetry) if self.telemetry else 0,
            "ticks": backlog,
            "events": self.engine.events,
        }

    def dataset_meta(self) -> Optional[dict]:
        if self.telemetry is None:
            return None
        tel = self.telemetry
        return {
            "id": _dataset_id(tel.name, tel.sheet),
            "name": tel.name,
            "sheet": tel.sheet,
            "label": tel.label,
            "samples": len(tel),
            # duration comes from this sheet's own Relative Time axis
            "duration_s": tel.times_s[-1] if len(tel) else 0,
            "sample_dt": tel.sample_dt,
            "columns": tel.columns,
            "validation": tel.validation,
        }

    def summary(self) -> dict:
        e = self.engine
        return {
            "state": e.state,
            "severity": e.severity,
            "t_in": e.inlet.arrival_time,
            "t_out": e.outlet.arrival_time,
            "leak": _leak(e),
            "isolated_segment": e.isolated_segment,
            "events": e.events,
        }


def _leak(engine: AnalyticsEngine):
    if engine.localization is None:
        return None
    loc = engine.localization
    return {"t_in": loc.t_in, "t_out": loc.t_out, "delta_t": loc.delta_t,
            "x_m": loc.x_m, "x_out_m": loc.x_from_outlet_m,
            "segment": loc.segment, "segment_range": loc.segment_range,
            "valid": loc.valid, "consistency_ok": loc.consistency_ok,
            "t_event": loc.t_event}


def _compact_tick(tick: dict) -> dict:
    """Wire format: short keys, only what the dashboard consumes."""
    def sensor(s):
        return {"p": s["p"], "b": s["baseline"], "r": s["ratio"],
                "sg": s["sigma"], "dp": s["rate"], "cu": s["cusum"],
                "th": s["rate_threshold"],
                "bn": s["baseline_n"], "bst": s["baseline_stable"],
                "ph": s["phase"], "tier": s["tier"], "arr": s["arrival"],
                "trig": s["trigger"]}
    return {
        "t": tick["t"],
        "in": sensor(tick["inlet"]),
        "out": sensor(tick["outlet"]),
        "st": tick["state"],
        "sev": tick["severity"],
        "gt": tick["global_tier"],
        "ml": tick["ml"],
        "leak": tick["leak"],
        "seg": [{"n": s["segment"], "lo": s["lo_m"], "hi": s["hi_m"],
                 "tier": s["tier"], "leak": s["leak"],
                 "iso": s["isolated"]} for s in tick["segments"]],
        "iso": tick["isolated"],
        "stg": tick["stages"],
        "fc": tick["forecast"],
        "ev": tick["new_events"],
    }


app = FastAPI(title="DeepWatch — Subsea Pipeline Integrity Twin")
session = Session()


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(WEB_DIR, "index.html")) as f:
        return f.read()


def _dataset_id(name: str, sheet: Optional[str]) -> str:
    return f"{name}::{sheet}" if sheet else name


_sheet_cache: dict = {}


def _sheets_for(path: str) -> list[dict]:
    key = (path, os.path.getmtime(path))
    if key not in _sheet_cache:
        _sheet_cache[key] = inspect_sheets(path)
    return _sheet_cache[key]


def _dataset_entries() -> list[dict]:
    """Dropdown entries: one per CSV / single-sheet workbook, one per
    VALID worksheet for multi-sheet workbooks (Read_Me etc. ignored)."""
    entries = []
    for f in sorted(os.listdir(DATA_DIR)):
        if not f.lower().endswith((".csv", ".xlsx", ".xls")):
            continue
        path = os.path.join(DATA_DIR, f)
        try:
            sheets = _sheets_for(path)
        except LoaderError:
            continue
        valid = [s["sheet"] for s in sheets if s["valid"]]
        if f.lower().endswith(".csv") or len(valid) <= 1:
            entries.append({"id": f, "name": f, "sheet": None, "label": f})
        else:
            for sheet in valid:
                entries.append({"id": _dataset_id(f, sheet), "name": f,
                                "sheet": sheet, "label": f"{sheet} · {f}"})
    return entries


@app.get("/api/datasets")
async def datasets():
    return {"datasets": _dataset_entries(), "loaded": session.dataset_meta()}


@app.post("/api/load")
async def load_dataset(body: dict):
    name = os.path.basename(body.get("name", ""))
    sheet = body.get("sheet") or None
    path = os.path.join(DATA_DIR, name)
    if not os.path.isfile(path):
        return JSONResponse({"error": f"dataset {name!r} not found"}, status_code=404)
    try:
        session.load(path, sheet=sheet)
    except MultiSheetWorkbook as exc:
        return JSONResponse({"error": str(exc), "sheets": exc.sheets},
                            status_code=400)
    except LoaderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"failed to parse: {exc}"}, status_code=400)
    await session._broadcast(session.snapshot())
    return {"ok": True, "dataset": session.dataset_meta()}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    name = os.path.basename(file.filename or "uploaded.csv")
    if not name.lower().endswith((".csv", ".xlsx", ".xls")):
        return JSONResponse({"error": "only .csv / .xlsx accepted"}, status_code=400)
    dest = os.path.join(DATA_DIR, name)
    with open(dest, "wb") as f:
        f.write(await file.read())
    try:
        session.load(dest)
    except MultiSheetWorkbook as exc:
        # several evaluation scenarios: populate the dropdown, do NOT
        # start processing — the user must pick a worksheet first
        return {"ok": True, "multi_sheet": True, "workbook": name,
                "sheets": exc.sheets,
                "message": f"{len(exc.sheets)} evaluation scenarios detected"}
    except LoaderError as exc:
        os.remove(dest)
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        os.remove(dest)
        return JSONResponse({"error": f"failed to parse: {exc}"}, status_code=400)
    await session._broadcast(session.snapshot())
    return {"ok": True, "dataset": session.dataset_meta()}


@app.post("/api/batch_sheets")
async def batch_sheets(body: dict):
    """Developer mode: run every valid worksheet of a workbook already in
    data/ independently — a brand-new AnalyticsEngine per sheet."""
    name = os.path.basename(body.get("name", ""))
    path = os.path.join(DATA_DIR, name)
    if not os.path.isfile(path):
        return JSONResponse({"error": f"workbook {name!r} not found"}, status_code=404)
    try:
        valid = [s["sheet"] for s in _sheets_for(path) if s["valid"]]
    except LoaderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if not valid:
        return JSONResponse({"error": "no valid telemetry worksheets"}, status_code=400)
    rows = []
    for sheet in valid:
        try:
            rows.append(evaluate_path(path, sheet=sheet))
        except Exception as exc:
            rows.append({"file": name, "sheet": sheet,
                         "dataset": f"{sheet} · {name}",
                         "error": f"processing failed: {exc}"})
    return {"results": rows, "workbook": name}


@app.post("/api/batch_eval")
async def batch_eval(files: list[UploadFile] = File(...)):
    """Developer mode: evaluate several files independently through the
    production inference path (a fresh engine per file). Files are
    processed from a temp dir and are NOT added to the demo dropdown."""
    rows = []
    with tempfile.TemporaryDirectory(prefix="dw_batch_") as tmp:
        for f in files:
            name = os.path.basename(f.filename or "unnamed.csv")
            if not name.lower().endswith((".csv", ".xlsx", ".xls")):
                rows.append({"file": name, "error": "unsupported extension"})
                continue
            path = os.path.join(tmp, name)
            with open(path, "wb") as out:
                out.write(await f.read())
            try:
                rows.append(evaluate_path(path))
            except LoaderError as exc:
                rows.append({"file": name, "error": str(exc)})
            except Exception as exc:
                rows.append({"file": name, "error": f"processing failed: {exc}"})
    return {"results": rows}


@app.post("/api/mode")
async def set_mode(body: dict):
    """Switch between COMPETITION MODE (locked official parameters) and
    ENGINEERING / SCALE MODE (user-supplied L, C and segment size)."""
    mode = body.get("mode", "competition")
    if mode not in ("competition", "engineering"):
        return JSONResponse({"error": "mode must be competition|engineering"},
                            status_code=400)
    length_m = PIPELINE_LENGTH_M
    wave = WAVE_SPEED_MS
    seg = SEGMENT_LENGTH_M
    if mode == "engineering":
        try:
            length_m = float(body.get("length_km", 10.0)) * 1000.0
            wave = float(body.get("wave_speed_ms", 1000.0))
            seg = float(body.get("segment_km", 2.0)) * 1000.0
        except (TypeError, ValueError):
            return JSONResponse({"error": "numeric parameters required"},
                                status_code=400)
        if not (100.0 <= length_m <= 10_000_000.0):
            return JSONResponse({"error": "pipeline length must be 0.1–10,000 km"},
                                status_code=400)
        if not (50.0 <= wave <= 5000.0):
            return JSONResponse({"error": "wave speed must be 50–5,000 m/s"},
                                status_code=400)
        if not (50.0 <= seg <= length_m):
            return JSONResponse({"error": "segment size must be ≥0.05 km and "
                                          "≤ pipeline length"}, status_code=400)
    session.set_mode(mode, length_m, wave, seg)
    await session._broadcast(session.snapshot())
    return {"ok": True, "mode": session.mode, "params": session.params,
            "num_segments": num_segments_for(session.params["length_m"],
                                             session.params["segment_len_m"])}


@app.post("/api/control")
async def control(body: dict):
    action = body.get("action")
    if "speed" in body and body["speed"] in SPEEDS:
        session.speed = body["speed"]
    if action == "start":
        session.start()
    elif action == "pause":
        session.stop()
    elif action == "reset":
        session.reset()
        await session._broadcast(session.snapshot())
    return {"ok": True, "running": session.running, "speed": session.speed,
            "finished": session.finished}


@app.get("/api/report", response_class=HTMLResponse)
async def incident_report():
    html = build_incident_report(session.engine, session.dataset_meta())
    return HTMLResponse(html, headers={
        "Content-Disposition": "inline; filename=incident_report.html"})


@app.get("/api/report.pdf")
async def incident_report_pdf():
    pdf = build_pdf_report(session.engine, session.dataset_meta(),
                           session.mode, session.last_event_id)
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": 'inline; filename="deepwatch_incident_report.pdf"'})


@app.get("/api/history")
async def get_history():
    records = history_mod.read_all()
    return {"records": records[-200:], "stats": history_mod.stats(records)}


@app.post("/api/history/clear")
async def clear_history():
    history_mod.clear()
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    session.clients.add(ws)
    try:
        await ws.send_text(json.dumps(session.snapshot()))
        while True:
            await ws.receive_text()  # client sends pings; content ignored
    except WebSocketDisconnect:
        pass
    finally:
        session.clients.discard(ws)


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
