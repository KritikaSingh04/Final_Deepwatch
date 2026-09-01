"""Automated incident report — professional PDF (fpdf2).

Built strictly READ-ONLY from a finished/running engine's recorded
outputs; generating it has zero effect on analytics. Contains no answer
keys and no jury ground truth — only what DeepWatch itself measured.
(Core fonts are latin-1, so all text is plain ASCII by design.)
"""

from __future__ import annotations

import datetime
from typing import Optional

from fpdf import FPDF

from engine.engine import AnalyticsEngine, ALARM_STATES, ISOLATED
from engine.forecast import forecast_sensor
from engine.npw import num_segments_for
from server.history import ai_state, detection_latency

INK = (20, 24, 31)
MUTED = (110, 118, 130)
RULE = (205, 208, 214)
BLUE = (42, 120, 214)      # inlet
ORANGE = (235, 104, 52)    # outlet
RED = (208, 59, 59)
GREEN = (12, 130, 12)

MARGIN = 15
PAGE_W = 210

# Core fonts are latin-1: transliterate engine-produced text (dashes,
# Greek letters, arrows, symbols) before rendering.
_TRANSLIT = {
    "–": "-", "—": "-", "·": "|", "Δ": "delta-", "σ": "sigma", "→": "->",
    "⛔": "", "⚠": "!", "✓": "OK", "✗": "x", "≠": "!=", "≥": ">=", "≤": "<=",
    "×": "x", "≈": "~", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
    "🟥": "", "›": ">",
}


def _ascii(text) -> str:
    s = str(text)
    for k, v in _TRANSLIT.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


class _Doc(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*MUTED)
            self.cell(0, 6, "DEEPWATCH - Pipeline Integrity Incident Report",
                      align="L")
            self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"Page {self.page_no()}/{{nb}}", align="C")


def _heading(pdf: FPDF, text: str):
    if pdf.get_y() > 265:
        pdf.add_page()
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, text.upper())
    pdf.ln(6.5)
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.4)
    y = pdf.get_y()
    pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    pdf.ln(2.5)


def _kv(pdf: FPDF, rows: list[tuple[str, str]], col_w: float = 58):
    pdf.set_line_width(0.15)
    for k, v in rows:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(col_w, 5.6, _ascii(k))
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 5.6, _ascii(v))
        pdf.set_draw_color(*RULE)
        y = pdf.get_y()
        pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
        pdf.ln(0.6)


def _fmt(v, nd=2, suffix=""):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}{suffix}"
    return f"{v}{suffix}"


def build_pdf_report(engine: AnalyticsEngine, dataset: Optional[dict],
                     mode: str, event_id: Optional[str] = None) -> bytes:
    now = datetime.datetime.now()
    event_id = event_id or ("EV-" + now.strftime("%Y%m%d-%H%M%S"))
    c = engine.config
    loc = engine.localization if (engine.localization
                                  and engine.localization.valid) else None
    leak = engine.state in ALARM_STATES
    alarm_t = next((e["t"] for e in engine.events
                    if e["kind"] == "LEAK_CONFIRMED"), None)

    pdf = _Doc(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(MARGIN, 12, MARGIN)
    pdf.add_page()

    # ---- title band --------------------------------------------------
    pdf.set_fill_color(16, 26, 44)
    pdf.rect(0, 0, PAGE_W, 26, style="F")
    pdf.set_xy(MARGIN, 6)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, "DEEPWATCH PIPELINE INTEGRITY INCIDENT REPORT")
    pdf.set_xy(MARGIN, 14)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(190, 205, 226)
    pdf.cell(0, 6, f"Event {event_id}   |   generated "
                   f"{now.strftime('%Y-%m-%d %H:%M:%S')}   |   "
                   f"{'ENGINEERING MODE' if mode == 'engineering' else 'COMPETITION MODE'}")
    pdf.set_y(30)

    # verdict strip
    verdict = ("LOSS OF CONTAINMENT - DETECTED, LOCALIZED AND "
               "AUTOMATICALLY ISOLATED" if engine.state == ISOLATED
               else "LEAK CONFIRMED - ALARM ACTIVE" if leak
               else "NO LEAK IDENTIFIED - PIPELINE WITHIN NORMAL LIMITS")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*(RED if leak else GREEN))
    pdf.cell(0, 6, verdict)
    pdf.ln(7)

    # ---- asset configuration ----------------------------------------
    n_seg = num_segments_for(c.length_m, c.segment_len_m)
    _heading(pdf, "Asset configuration")
    _kv(pdf, [
        ("Pipeline length L", f"{c.length_m:,.0f} m"),
        ("Wave speed C", f"{c.wave_speed_ms:,.0f} m/s"),
        ("Logical segments", f"{n_seg} x {c.segment_len_m / 1000:g} km"),
        ("Dataset / scenario", str((dataset or {}).get("label")
                                   or (dataset or {}).get("name") or "-")),
        ("Samples processed", f"{engine.sample_count:,}"),
    ])

    # ---- detection ---------------------------------------------------
    _heading(pdf, "Detection (pressure-only, deterministic)")
    _kv(pdf, [
        ("Inlet transient t_in",
         _fmt(engine.inlet.arrival_time, 2, " s")
         + (f"  ({engine.inlet.trigger_kind} detector)"
            if engine.inlet.trigger_kind else "")),
        ("Outlet transient t_out",
         _fmt(engine.outlet.arrival_time, 2, " s")
         + (f"  ({engine.outlet.trigger_kind} detector)"
            if engine.outlet.trigger_kind else "")),
        ("Delta-t (t_out - t_in)",
         _fmt(loc.delta_t if loc else None, 2, " s")),
        ("Detection latency", _fmt(detection_latency(engine), 2, " s")),
    ])

    # ---- localization ------------------------------------------------
    _heading(pdf, "NPW localization  X = (L - C*dt) / 2")
    if loc:
        _kv(pdf, [
            ("Distance from inlet", f"{loc.x_m:,.0f} m"),
            ("Distance from outlet", f"{loc.x_from_outlet_m:,.0f} m"),
            ("Affected segment", f"Segment {loc.segment} ({loc.segment_range})"),
            ("Cross-check X_in + X_out",
             f"{loc.x_m + loc.x_from_outlet_m:,.0f} m = L "
             + ("OK" if loc.consistency_ok else "WARNING")),
            ("Estimated origin t_event",
             _fmt(loc.t_event, 2, " s") + "  (engineering diagnostic)"),
        ])
    elif engine.localization_invalid:
        _kv(pdf, [("Localization", "INVALID - timing inconsistent with the "
                                   "configured pipeline (|dt| > L/C); "
                                   "transients treated as uncorrelated")])
    else:
        _kv(pdf, [("Localization", "not performed - no correlated transient "
                                   "pair was confirmed")])

    # ---- signal diagnostics ------------------------------------------
    _heading(pdf, "Signal diagnostics (adaptive, noise-scaled)")
    thr_in = max(c.detector.k_rate * engine.inlet.rate_sigma,
                 c.detector.rate_floor_bar / max(engine.inlet.dt_nominal, 1e-3))
    thr_out = max(c.detector.k_rate * engine.outlet.rate_sigma,
                  c.detector.rate_floor_bar / max(engine.outlet.dt_nominal, 1e-3))
    _kv(pdf, [
        ("Inlet baseline",
         _fmt(engine.inlet.baseline, 2, " bar")
         + f"  (n={engine.inlet.baseline_n}"
         + ("" if engine.inlet.baseline_stable else ", provisional") + ")"),
        ("Outlet baseline",
         _fmt(engine.outlet.baseline, 2, " bar")
         + f"  (n={engine.outlet.baseline_n}"
         + ("" if engine.outlet.baseline_stable else ", provisional") + ")"),
        ("Inlet noise sigma (MAD)", _fmt(engine.inlet.sigma, 3, " bar")),
        ("Outlet noise sigma (MAD)", _fmt(engine.outlet.sigma, 3, " bar")),
        ("Inlet adaptive trigger", f"-{thr_in:.2f} bar/s"),
        ("Outlet adaptive trigger", f"-{thr_out:.2f} bar/s"),
    ])

    # ---- condition ---------------------------------------------------
    _heading(pdf, "Condition - severity progression")
    sev_events = [e for e in engine.events
                  if e["kind"] in ("SEVERITY", "CRITICAL_CONDITION")]
    if sev_events:
        _kv(pdf, [(f"t = {e['t']:.2f} s", e["message"]) for e in sev_events])
    else:
        _kv(pdf, [("Severity", "no escalation recorded")])

    # ---- AI ----------------------------------------------------------
    _heading(pdf, "AI corroboration (advisory)")
    _kv(pdf, [("Final status", ai_state(engine))])
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4.6, "AI provides independent anomaly corroboration; "
                           "safety-critical detection and localization remain "
                           "deterministic and physics-based.")
    pdf.ln(1)

    # ---- forecast ----------------------------------------------------
    _heading(pdf, "Predictive pressure decay (trend-based estimate - advisory)")
    if leak:
        rows = []
        for name, det in (("Inlet", engine.inlet), ("Outlet", engine.outlet)):
            f = forecast_sensor(engine._forecast_buf[name.lower()], det.baseline)
            if f["trend_ok"] or f["caution_80"] == "crossed" \
                    or f["critical_60"] == "crossed":
                def eta(v):
                    return "crossed" if v == "crossed" else _fmt(v, 1, " s")
                rows.append((f"{name} (now {_fmt((f['ratio'] or 0) * 100, 1, '%')} "
                             f"of baseline)",
                             f"decay { _fmt(f['slope_bar_s'], 2, ' bar/s') }  |  "
                             f"degraded 80%: {eta(f['caution_80'])}  |  "
                             f"critical 60%: {eta(f['critical_60'])}"))
            else:
                rows.append((name, "forecast unavailable - "
                                   + (f["reason"] or "no consistent trend")))
        _kv(pdf, rows)
    else:
        _kv(pdf, [("Forecast", "not applicable - no confirmed leak")])

    # ---- response ----------------------------------------------------
    _heading(pdf, "Response")
    iso_msg = next((e["message"] for e in engine.events
                    if e["kind"] == "VIRTUAL_ISOLATION"), None)
    _kv(pdf, [
        ("Leak alarm raised", _fmt(alarm_t, 2, " s")),
        ("Critical condition", _fmt(engine.critical_time, 2, " s")),
        ("Virtual isolation executed", _fmt(engine.isolation_time, 2, " s")),
        ("Actions", iso_msg or ("automatic response armed - threshold not "
                                "reached" if leak else "none required")),
    ])

    # ---- pressure plot ----------------------------------------------
    if len(engine.history) >= 2:
        _plot(pdf, engine)

    # ---- event timeline ---------------------------------------------
    _heading(pdf, "Event timeline")
    pdf.set_font("Helvetica", "", 8.5)
    for e in engine.events:
        if pdf.get_y() > 268:
            pdf.add_page()
        pdf.set_text_color(*MUTED)
        pdf.cell(18, 5, f"{e['t']:.2f} s")
        pdf.set_text_color(*(RED if e.get("alarm") else INK))
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(44, 5, _ascii(e["kind"]))
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 5, _ascii(e["message"]))
        pdf.ln(0.3)
    if not engine.events:
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, "No events recorded.")
        pdf.ln(6)

    # ---- operator notes / sign-off ----------------------------------
    if pdf.get_y() > 215:
        pdf.add_page()
    _heading(pdf, "Operator notes")
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.2)
    for _ in range(4):
        y = pdf.get_y() + 6
        pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
        pdf.set_y(y + 1.5)
    pdf.ln(8)
    y = pdf.get_y() + 10
    pdf.set_draw_color(*INK)
    pdf.line(MARGIN, y, MARGIN + 75, y)
    pdf.line(PAGE_W - MARGIN - 75, y, PAGE_W - MARGIN, y)
    pdf.set_y(y + 1.5)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(90, 5, "Pipeline Integrity Engineer - name / signature / date")
    pdf.set_x(PAGE_W - MARGIN - 75)
    pdf.cell(75, 5, "Offshore Installation Manager - name / signature / date")

    return bytes(pdf.output())


def _plot(pdf: FPDF, engine: AnalyticsEngine):
    """Compact inlet/outlet pressure plot drawn with vector primitives."""
    if pdf.get_y() > 200:
        pdf.add_page()
    _heading(pdf, "Pressure telemetry record")
    x0, w, h = MARGIN, PAGE_W - 2 * MARGIN, 52
    y0 = pdf.get_y() + 2

    hist = engine.history
    step = max(1, len(hist) // 500)
    pts = hist[::step]
    ts = [p[0] for p in pts]
    t_lo, t_hi = ts[0], ts[-1] if ts[-1] > ts[0] else ts[0] + 1
    vals = [p[1] for p in pts] + [p[2] for p in pts]
    v_lo, v_hi = min(vals), max(vals)
    pad = (v_hi - v_lo or 1) * 0.08
    v_lo -= pad
    v_hi += pad

    def X(t):
        return x0 + (t - t_lo) / (t_hi - t_lo) * w

    def Y(v):
        return y0 + (v_hi - v) / (v_hi - v_lo) * h

    # frame + gridlines
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.2)
    pdf.rect(x0, y0, w, h)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MUTED)
    for i in range(1, 4):
        v = v_lo + (v_hi - v_lo) * i / 4
        pdf.line(x0, Y(v), x0 + w, Y(v))
        pdf.set_xy(x0 + 1, Y(v) - 3.5)
        pdf.cell(14, 3, f"{v:.0f}")
    for i in range(6):
        t = t_lo + (t_hi - t_lo) * i / 5
        pdf.set_xy(X(t) - 5, y0 + h + 1)
        pdf.cell(10, 3, f"{t:.0f}s", align="C")

    # arrival markers
    pdf.set_line_width(0.25)
    for arr, col, lbl in ((engine.inlet.arrival_time, BLUE, "t_in"),
                          (engine.outlet.arrival_time, ORANGE, "t_out")):
        if arr is not None and t_lo <= arr <= t_hi:
            pdf.set_draw_color(*col)
            xx = X(arr)
            yy = y0
            while yy < y0 + h - 1.5:            # dashed vertical
                pdf.line(xx, yy, xx, min(yy + 1.6, y0 + h))
                yy += 3.2
            pdf.set_text_color(*col)
            pdf.set_xy(min(xx + 0.8, x0 + w - 16), y0 + 0.5)
            pdf.cell(16, 3, f"{lbl}={arr:.2f}s")

    # series
    pdf.set_line_width(0.45)
    for idx, col in ((1, BLUE), (2, ORANGE)):
        pdf.set_draw_color(*col)
        prev = None
        for p in pts:
            cur = (X(p[0]), Y(p[idx]))
            if prev:
                pdf.line(prev[0], prev[1], cur[0], cur[1])
            prev = cur

    # legend
    pdf.set_font("Helvetica", "", 7.5)
    lx = x0 + w - 52
    for col, lbl in ((BLUE, "Inlet (bar)"), (ORANGE, "Outlet (bar)")):
        pdf.set_fill_color(*col)
        pdf.rect(lx, y0 + 2, 3, 3, style="F")
        pdf.set_text_color(*INK)
        pdf.set_xy(lx + 4, y0 + 1.4)
        pdf.cell(22, 4, lbl)
        lx += 27

    pdf.set_y(y0 + h + 6)
