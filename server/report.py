"""Automated incident report generation.

Builds a standalone, print-ready HTML incident report from the engine's
recorded history: event timeline, NPW calculation with live values
substituted, pressure chart (inline SVG), final segment health map and a
sign-off block. Downloadable from the dashboard the moment isolation
fires; browsers print it straight to PDF.
"""

from __future__ import annotations

import datetime
from typing import Optional

from engine.engine import AnalyticsEngine, ISOLATED, LEAK_CONFIRMED
from engine.health import TIER_LABEL
from engine.npw import num_segments_for

# light-surface palette (report is a printed document, light by design)
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES_IN = "#2a78d6"    # inlet — blue
SERIES_OUT = "#eb6834"   # outlet — orange
TIER_FILL = {"GREEN": "#0ca30c", "YELLOW": "#fab219",
             "ORANGE": "#ec835a", "RED": "#d03b3b"}

CHART_W, CHART_H = 860, 300
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 18, 34


def build_incident_report(engine: AnalyticsEngine, dataset: Optional[dict]) -> str:
    now = datetime.datetime.now()
    report_id = "DW-" + now.strftime("%Y%m%d-%H%M%S")
    loc = engine.localization if (engine.localization
                                  and engine.localization.valid) else None
    leak_state = engine.state in (LEAK_CONFIRMED, "LOCALIZED", "CRITICAL",
                                  ISOLATED)

    rows = []
    def row(k, v):
        rows.append(f"<tr><th>{k}</th><td>{v}</td></tr>")

    row("Report ID", report_id)
    row("Generated", now.strftime("%Y-%m-%d %H:%M:%S"))
    row("Dataset", (dataset or {}).get("name", "—"))
    row("Samples processed", f"{engine.sample_count:,}")
    ec = engine.config
    n_seg = num_segments_for(ec.length_m, ec.segment_len_m)
    row("Pipeline", f"L = {ec.length_m:,.0f} m · C = {ec.wave_speed_ms:,.0f} m/s "
                    f"· {n_seg} logical segments "
                    f"({ec.segment_len_m / 1000:g} km each)")
    row("Final system state", _state_badge(engine.state))
    row("Event severity", engine.severity or "—")
    if engine.inlet.arrival_time is not None:
        row("Inlet transient (t<sub>in</sub>)",
            f"{engine.inlet.arrival_time:.2f} s "
            f"<span class='dim'>({engine.inlet.trigger_kind} detector)</span>")
    if engine.outlet.arrival_time is not None:
        row("Outlet transient (t<sub>out</sub>)",
            f"{engine.outlet.arrival_time:.2f} s "
            f"<span class='dim'>({engine.outlet.trigger_kind} detector)</span>")
    if loc:
        row("Δt", f"{loc.delta_t:+.2f} s")
        row("Leak location (dual-ended)",
            f"<b>{loc.x_m:,.0f} m</b> from inlet · "
            f"<b>{loc.x_from_outlet_m:,.0f} m</b> from outlet")
        row("Affected segment",
            f"Segment {loc.segment} ({loc.segment_range})")
        if loc.t_event is not None:
            row("Estimated leak-origin time t<sub>event</sub>",
                f"{loc.t_event:.2f} s "
                "<span class='dim'>(engineering diagnostic: "
                "(t<sub>in</sub> + t<sub>out</sub> − L/C) / 2)</span>")
        if not loc.consistency_ok:
            row("Localization consistency",
                "<b>WARNING</b> — X_in + X_out ≠ L within tolerance")
    elif engine.localization_invalid:
        row("Localization", "<b>INVALID</b> — Δt outside physical bounds; "
            "transients treated as uncorrelated")
    if engine.isolation_time is not None:
        row("Virtual isolation executed", f"t = {engine.isolation_time:.2f} s "
            "<span class='dim'>(automatic, no manual intervention)</span>")

    npw_block = ""
    if loc:
        npw_block = f"""
        <section>
          <h2>2 · NPW localization calculation</h2>
          <div class="npw">
            X<sub>inlet</sub>&nbsp; = (L − C·Δt) / 2
            = ({ec.length_m:,.0f} − {ec.wave_speed_ms:,.0f} × {loc.delta_t:+.2f}) / 2
            = <b>{loc.x_m:,.0f} m</b> from inlet<br>
            X<sub>outlet</sub> = (L + C·Δt) / 2
            = ({ec.length_m:,.0f} + {ec.wave_speed_ms:,.0f} × {loc.delta_t:+.2f}) / 2
            = <b>{loc.x_from_outlet_m:,.0f} m</b> from outlet<br>
            <span class="dim">cross-check: X<sub>inlet</sub> + X<sub>outlet</sub>
            = {loc.x_m + loc.x_from_outlet_m:,.0f} m = L&nbsp;✓</span>
          </div>
          <p class="dim">Δt = t<sub>out</sub> − t<sub>in</sub> =
          {loc.t_out:.2f} − {loc.t_in:.2f} = {loc.delta_t:+.2f} s.
          Arrival times were identified automatically from pressure telemetry
          (adaptive rate + CUSUM detectors); the supplied status flag was not
          used.</p>
        </section>"""

    events_html = "".join(
        f"<tr><td class='mono'>{e['t']:.2f} s</td>"
        f"<td><span class='k k-{e['kind']}'>{e['kind']}</span></td>"
        f"<td>{e['message']}</td></tr>"
        for e in engine.events) or "<tr><td colspan=3>No events recorded.</td></tr>"

    verdict = ("A loss-of-containment event was detected, localized and "
               "automatically mitigated by virtual isolation."
               if engine.state == ISOLATED else
               "A leak signature was confirmed on pressure telemetry."
               if leak_state else
               "No leak signature was identified. The pipeline remained within "
               "normal operating limits for the full record.")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Incident Report {report_id}</title>
<style>
  body {{ font: 14px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
         color: {INK}; background: #f9f9f7; margin: 0; }}
  .page {{ max-width: 940px; margin: 24px auto; background: #fcfcfb;
          border: 1px solid rgba(11,11,11,.1); border-radius: 8px;
          padding: 40px 48px; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline;
           border-bottom: 2px solid {INK}; padding-bottom: 12px; }}
  h1 {{ font-size: 20px; margin: 0; letter-spacing: .02em; }}
  .brand {{ font-size: 12px; color: {INK2}; text-align: right; }}
  h2 {{ font-size: 15px; margin: 28px 0 10px; }}
  table.kv {{ border-collapse: collapse; width: 100%; }}
  table.kv th {{ text-align: left; width: 260px; color: {INK2}; font-weight: 500;
               padding: 5px 8px 5px 0; vertical-align: top; }}
  table.kv td {{ padding: 5px 0; }}
  table.kv tr {{ border-bottom: 1px solid {GRID}; }}
  .dim {{ color: {MUTED}; }}
  .mono {{ font-variant-numeric: tabular-nums; }}
  .npw {{ font-family: ui-monospace, Menlo, monospace; font-size: 14px;
         background: #f4f3f0; border: 1px solid {GRID}; border-radius: 6px;
         padding: 14px 16px; }}
  table.ev {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  table.ev td {{ border-bottom: 1px solid {GRID}; padding: 6px 10px 6px 0;
               vertical-align: top; }}
  table.ev td:first-child {{ white-space: nowrap; }}
  .k {{ font-size: 11px; font-weight: 600; letter-spacing: .04em; }}
  .k-LEAK_CONFIRMED, .k-VIRTUAL_ISOLATION, .k-SEVERITY,
  .k-CRITICAL_CONDITION {{ color: #d03b3b; }}
  .k-TRANSIENT_DETECTED, .k-LEAK_LOCALIZED {{ color: #1c5cab; }}
  .k-ANOMALY_SUSPECTED, .k-LOCALIZATION_INVALID {{ color: #b07200; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 99px;
           font-size: 12px; font-weight: 600; color: #fff; }}
  .seg-map {{ display: flex; gap: 3px; margin: 10px 0 4px; }}
  .seg {{ flex: 1; border-radius: 4px; color: #fff; text-align: center;
         padding: 10px 4px 8px; font-size: 12px; font-weight: 600; }}
  .seg small {{ display: block; font-weight: 400; opacity: .9; }}
  .verdict {{ border-left: 4px solid {'#d03b3b' if leak_state else '#0ca30c'};
             background: #f4f3f0; padding: 12px 16px; border-radius: 0 6px 6px 0; }}
  .sign {{ display: grid; grid-template-columns: 1fr 1fr; gap: 40px; margin-top: 44px; }}
  .sign div {{ border-top: 1px solid {INK}; padding-top: 6px; font-size: 12px;
              color: {INK2}; }}
  figcaption {{ font-size: 12px; color: {MUTED}; margin-top: 4px; }}
  @media print {{ body {{ background: #fff; }} .page {{ border: none; margin: 0; }} }}
</style></head><body><div class="page">
<header>
  <h1>SUBSEA PIPELINE INCIDENT REPORT</h1>
  <div class="brand">DEEPWATCH · Real-Time Pipeline Integrity Twin<br>
  Offshore Production Manifold — 10 km subsea segment</div>
</header>

<section>
  <h2>1 · Event summary</h2>
  <div class="verdict">{verdict}</div>
  <table class="kv">{''.join(rows)}</table>
</section>

{npw_block}

<section>
  <h2>{3 if loc else 2} · Pressure telemetry record</h2>
  <figure style="margin:0">{_pressure_svg(engine)}
  <figcaption>Inlet and outlet pressure vs time. Dashed verticals mark the
  detected transient arrivals; dotted horizontals mark each sensor's learned
  baseline.</figcaption></figure>
</section>

<section>
  <h2>{4 if loc else 3} · Final segment health map</h2>
  {_segment_map(engine)}
  <p class="dim" style="font-size:12px">Health legend: GREEN Healthy ≥95% ·
  YELLOW Caution 80–95% · ORANGE Degraded 60–80% · RED Critical &lt;60% of
  baseline. {"⛔ = virtually isolated segment." if engine.state == ISOLATED else ""}</p>
</section>

<section>
  <h2>{5 if loc else 4} · Event timeline</h2>
  <table class="ev">{events_html}</table>
</section>

<div class="sign">
  <div>Pipeline Integrity Engineer — name / signature / date</div>
  <div>Offshore Installation Manager — name / signature / date</div>
</div>
</div></body></html>"""


def _state_badge(state: str) -> str:
    color = {"NORMAL": "#0ca30c", "ANOMALY_SUSPECTED": "#c98500",
             "LEAK_CONFIRMED": "#d03b3b", "LOCALIZED": "#d03b3b",
             "CRITICAL": "#d03b3b", "ISOLATED": "#d03b3b"}.get(state, MUTED)
    return f"<span class='badge' style='background:{color}'>{state}</span>"


def _segment_map(engine: AnalyticsEngine) -> str:
    from engine.health import classify, worst
    if engine.history:
        _, p_in, p_out, b_in, b_out = engine.history[-1]
        tier = worst(classify(p_in / b_in if b_in else 1.0).tier,
                     classify(p_out / b_out if b_out else 1.0).tier)
    else:
        tier = "GREEN"
    segs = engine._segment_states(tier)
    cells = []
    for s in segs:
        mark = " ⛔" if s["isolated"] else (" ▼ LEAK" if s["leak"] else "")
        rng = f"{s['lo_m'] / 1000:g}–{s['hi_m'] / 1000:g} km"
        cells.append(
            f"<div class='seg' style='background:{TIER_FILL[s['tier']]}'>"
            f"S{s['segment']}{mark}<small>{rng}"
            f" · {TIER_LABEL[s['tier']]}</small></div>")
    return f"<div class='seg-map'>{''.join(cells)}</div>"


def _pressure_svg(engine: AnalyticsEngine) -> str:
    hist = engine.history
    if len(hist) < 2:
        return "<p class='dim'>No telemetry recorded.</p>"
    # downsample to <= 700 points
    step = max(1, len(hist) // 700)
    pts = hist[::step]
    ts = [p[0] for p in pts]
    t0, t1 = ts[0], ts[-1]
    vals = [p[1] for p in pts] + [p[2] for p in pts]
    v0, v1 = min(vals), max(vals)
    span = (v1 - v0) or 1.0
    v0 -= span * 0.08
    v1 += span * 0.08

    def X(t): return PAD_L + (t - t0) / (t1 - t0 or 1) * (CHART_W - PAD_L - PAD_R)
    def Y(v): return PAD_T + (v1 - v) / (v1 - v0) * (CHART_H - PAD_T - PAD_B)

    def path(idx):
        return "M" + " L".join(f"{X(p[0]):.1f} {Y(p[idx]):.1f}" for p in pts)

    grid = []
    n_ticks = 5
    for i in range(n_ticks + 1):
        v = v0 + (v1 - v0) * i / n_ticks
        y = Y(v)
        grid.append(f"<line x1='{PAD_L}' y1='{y:.1f}' x2='{CHART_W-PAD_R}' "
                    f"y2='{y:.1f}' stroke='{GRID}' stroke-width='1'/>"
                    f"<text x='{PAD_L-8}' y='{y+4:.1f}' text-anchor='end' "
                    f"fill='{MUTED}' font-size='11'>{v:.0f}</text>")
    for i in range(6):
        t = t0 + (t1 - t0) * i / 5
        x = X(t)
        grid.append(f"<text x='{x:.1f}' y='{CHART_H-10}' text-anchor='middle' "
                    f"fill='{MUTED}' font-size='11'>{t:.0f}s</text>")

    marks = []
    for arr, color, label in ((engine.inlet.arrival_time, SERIES_IN, "t_in"),
                              (engine.outlet.arrival_time, SERIES_OUT, "t_out")):
        if arr is not None and t0 <= arr <= t1:
            x = X(arr)
            marks.append(
                f"<line x1='{x:.1f}' y1='{PAD_T}' x2='{x:.1f}' "
                f"y2='{CHART_H-PAD_B}' stroke='{color}' stroke-width='1.5' "
                f"stroke-dasharray='5 4'/>"
                f"<text x='{x+4:.1f}' y='{PAD_T+12}' fill='{color}' "
                f"font-size='11' font-weight='600'>{label}={arr:.2f}s</text>")
    for base, color in ((pts[0][3], SERIES_IN), (pts[0][4], SERIES_OUT)):
        y = Y(base)
        marks.append(f"<line x1='{PAD_L}' y1='{y:.1f}' x2='{CHART_W-PAD_R}' "
                     f"y2='{y:.1f}' stroke='{color}' stroke-width='1' "
                     f"stroke-dasharray='2 4' opacity='.55'/>")

    return f"""<svg viewBox="0 0 {CHART_W} {CHART_H}" role="img"
  aria-label="Inlet and outlet pressure telemetry"
  style="width:100%;height:auto;background:#fcfcfb;border:1px solid {GRID};
  border-radius:6px" font-family="system-ui, sans-serif">
  {''.join(grid)}
  <line x1='{PAD_L}' y1='{CHART_H-PAD_B}' x2='{CHART_W-PAD_R}'
        y2='{CHART_H-PAD_B}' stroke='{AXIS}' stroke-width='1'/>
  <path d="{path(1)}" fill="none" stroke="{SERIES_IN}" stroke-width="2"/>
  <path d="{path(2)}" fill="none" stroke="{SERIES_OUT}" stroke-width="2"/>
  {''.join(marks)}
  <g font-size="12" font-weight="600">
    <rect x="{CHART_W-190}" y="{PAD_T}" width="10" height="10" rx="2" fill="{SERIES_IN}"/>
    <text x="{CHART_W-175}" y="{PAD_T+9}" fill="{INK2}" font-weight="400">Inlet (bar)</text>
    <rect x="{CHART_W-100}" y="{PAD_T}" width="10" height="10" rx="2" fill="{SERIES_OUT}"/>
    <text x="{CHART_W-85}" y="{PAD_T+9}" fill="{INK2}" font-weight="400">Outlet (bar)</text>
  </g>
</svg>"""
