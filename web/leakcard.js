/* Shared leak-info card content for the 3D scene and 2D schematic. */

export function leakCardHtml(info) {
  if (!info) return "";
  const km = (m) => (m / 1000).toFixed(2) + " km";
  const s = (v) => v != null ? v.toFixed(2) + " s" : "—";
  const dt = info.delta_t != null
    ? (info.delta_t >= 0 ? "+" : "−") + Math.abs(info.delta_t).toFixed(2) + " s"
    : "—";
  return `<div class="lc-title">LEAK LOCATION</div>` +
    `From inlet: <b>${km(info.x_m)}</b><br>` +
    `From outlet: <b>${km(info.x_out_m)}</b><br>` +
    `Segment: <b>S${info.segment}</b><br>` +
    `t_in: <b>${s(info.t_in)}</b> · t_out: <b>${s(info.t_out)}</b><br>` +
    `Δt: <b>${dt}</b>`;
}
