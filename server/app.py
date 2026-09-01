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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import tempfile

from engine.engine import AnalyticsEngine
from engine.npw import PIPELINE_LENGTH_M, WAVE_SPEED_MS, NUM_SEGMENTS
from streaming.loader import (load as load_telemetry, inspect_sheets,
                              LoaderError, MultiSheetWorkbook, TelemetrySet)
from server.batch import evaluate_path
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
        self.engine = AnalyticsEngine()
        self.idx = 0
        self.speed = 5
        self.running = False
        self.finished = False
        self.task: Optional[asyncio.Task] = None
        self.clients: set[WebSocket] = set()
        self.ticks: list[dict] = []   # compact ticks kept for late joiners

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
        self.engine = AnalyticsEngine()
        self.idx = 0
        self.finished = False
        self.ticks = []

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
                await self._broadcast({"type": "finished",
                                       "summary": self.summary()})
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
                "length_m": PIPELINE_LENGTH_M,
                "wave_speed_ms": WAVE_SPEED_MS,
                "num_segments": NUM_SEGMENTS,
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
                "sg": s["sigma"], "cu": s["cusum"], "th": s["rate_threshold"],
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
        "seg": [{"n": s["segment"], "tier": s["tier"], "leak": s["leak"],
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
