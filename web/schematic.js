/* 2D pipeline schematic — SVG, dynamic logical segments.
   Rebuilt whenever the active pipeline configuration changes
   (competition: 5 × 2 km; engineering mode: any L / segment size). */

import { leakCardHtml } from "/static/leakcard.js";

const TIER = {
  GREEN: "var(--good)", YELLOW: "var(--warn)",
  ORANGE: "var(--serious)", RED: "var(--crit)",
};
const W = 1000, H = 168, PIPE_X0 = 92, PIPE_X1 = 908, PIPE_Y = 78, PIPE_H = 24;

export function initSchematic(container, cfg) {
  const lengthM = cfg.length_m;
  const segLenM = cfg.segment_len_m;
  const nSeg = cfg.num_segments;
  const xOf = (m) => PIPE_X0 + (m / lengthM) * (PIPE_X1 - PIPE_X0);
  const km = (m) => +(m / 1000).toFixed(2);

  // segment boundaries (final segment absorbs any remainder)
  const bounds = [];
  for (let i = 0; i < nSeg; i++) {
    const lo = i * segLenM;
    const hi = i === nSeg - 1 ? lengthM : Math.min((i + 1) * segLenM, lengthM);
    bounds.push([lo, hi]);
  }

  let segs = "", segLabels = "", ticks = "";
  const showSegText = nSeg <= 14;
  bounds.forEach(([lo, hi], i) => {
    const x0 = xOf(lo), x1 = xOf(hi);
    segs += `<rect id="sk-seg-${i + 1}" x="${x0 + 2}" y="${PIPE_Y}"
      width="${Math.max(x1 - x0 - 4, 2)}" height="${PIPE_H}" rx="5"
      fill="var(--good)" stroke="rgba(0,0,0,.35)"/>` +
      (showSegText ? `<text id="sk-segtxt-${i + 1}" x="${(x0 + x1) / 2}"
        y="${PIPE_Y + PIPE_H / 2 + 3.5}" text-anchor="middle" font-size="10.5"
        font-weight="700" fill="#08140a">S${i + 1}</text>` : "");
    if (showSegText) {
      segLabels += `<text id="sk-seglbl-${i + 1}" x="${(x0 + x1) / 2}"
        y="${PIPE_Y + PIPE_H + 16}" text-anchor="middle" font-size="9"
        fill="#7e8ea6">${km(lo)}–${km(hi)} km</text>`;
    }
  });
  // boundary tick labels, thinned when there are many segments
  const step = Math.max(1, Math.ceil((nSeg + 1) / 11));
  for (let i = 0; i <= nSeg; i++) {
    const m = i === nSeg ? lengthM : Math.min(i * segLenM, lengthM);
    const x = xOf(m);
    ticks += `<line x1="${x}" y1="${PIPE_Y - 10}" x2="${x}" y2="${PIPE_Y - 4}"
      stroke="#2c3b57"/>`;
    if (i % step === 0 || i === nSeg) {
      ticks += `<text x="${x}" y="${PIPE_Y - 15}" text-anchor="middle"
        font-size="8.5" fill="#7e8ea6">${km(m)} km</text>`;
    }
  }

  container.innerHTML = `
  <svg viewBox="0 0 ${W} ${H}" font-family="system-ui, sans-serif" role="img"
       aria-label="Pipeline schematic with ${nSeg} segments">
    <g>
      <rect x="26" y="${PIPE_Y - 18}" width="58" height="60" rx="7"
            fill="#16233a" stroke="rgba(148,178,224,.25)"/>
      <circle cx="40" cy="${PIPE_Y - 4}" r="4" fill="var(--inlet)"/>
      <text x="55" y="${PIPE_Y - 1}" font-size="9" fill="#a9b6c9">PT-001</text>
      <text x="55" y="${PIPE_Y + 13}" text-anchor="middle" font-size="9.5"
            font-weight="700" fill="#e8eef7">INLET</text>
      <text x="55" y="${PIPE_Y + 25}" text-anchor="middle" font-size="8"
            fill="#7e8ea6">MANIFOLD</text>
      <text id="sk-tin" x="55" y="${PIPE_Y + 52}" text-anchor="middle"
            font-size="9" font-weight="600" fill="var(--inlet)"
            font-family="ui-monospace, monospace"></text>
    </g>
    <g>
      <rect x="${W - 84}" y="${PIPE_Y - 18}" width="58" height="60" rx="7"
            fill="#16233a" stroke="rgba(148,178,224,.25)"/>
      <circle cx="${W - 70}" cy="${PIPE_Y - 4}" r="4" fill="var(--outlet)"/>
      <text x="${W - 55}" y="${PIPE_Y - 1}" font-size="9" fill="#a9b6c9">PT-002</text>
      <text x="${W - 55}" y="${PIPE_Y + 13}" text-anchor="middle" font-size="9.5"
            font-weight="700" fill="#e8eef7">OUTLET</text>
      <text x="${W - 55}" y="${PIPE_Y + 25}" text-anchor="middle" font-size="8"
            fill="#7e8ea6">TERMINAL</text>
      <text id="sk-tout" x="${W - 55}" y="${PIPE_Y + 52}" text-anchor="middle"
            font-size="9" font-weight="600" fill="var(--outlet)"
            font-family="ui-monospace, monospace"></text>
    </g>

    ${ticks}${segs}${segLabels}

    <text x="${PIPE_X0 + 8}" y="${PIPE_Y + PIPE_H + 34}" font-size="9"
          fill="#7e8ea6">flow →</text>

    <g id="sk-valve-l" visibility="hidden">
      <rect x="-9" y="${PIPE_Y - 7}" width="18" height="${PIPE_H + 14}" rx="3"
            fill="#4a1616" stroke="var(--crit)" stroke-width="1.5"/>
      <line x1="-4" y1="${PIPE_Y - 2}" x2="4" y2="${PIPE_Y + PIPE_H + 2}"
            stroke="var(--crit)" stroke-width="2"/>
    </g>
    <g id="sk-valve-r" visibility="hidden">
      <rect x="-9" y="${PIPE_Y - 7}" width="18" height="${PIPE_H + 14}" rx="3"
            fill="#4a1616" stroke="var(--crit)" stroke-width="1.5"/>
      <line x1="-4" y1="${PIPE_Y - 2}" x2="4" y2="${PIPE_Y + PIPE_H + 2}"
            stroke="var(--crit)" stroke-width="2"/>
    </g>
    <text id="sk-iso-lbl" visibility="hidden" y="${PIPE_Y + PIPE_H + 34}"
          text-anchor="middle" font-size="9.5" font-weight="800"
          fill="var(--crit)" letter-spacing="1.5">⛔ SEGMENT ISOLATED</text>

    <g id="sk-leak" visibility="hidden">
      <circle id="sk-leak-pulse" cy="${PIPE_Y + PIPE_H / 2}" r="10"
              fill="none" stroke="var(--crit)" stroke-width="2">
        <animate attributeName="r" values="8;20;8" dur="1.6s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values=".9;0;.9" dur="1.6s" repeatCount="indefinite"/>
      </circle>
      <path id="sk-leak-pin" d="M0 0 l7 -12 h-14 z" fill="var(--crit)"/>
      <text id="sk-leak-txt" y="${PIPE_Y - 26}" text-anchor="middle" font-size="10.5"
            font-weight="800" fill="#ff9d9d" font-family="ui-monospace, monospace"></text>
    </g>
  </svg>`;

  const card = document.createElement("div");
  card.className = "leak-card";
  card.hidden = true;
  container.appendChild(card);
  let leakInfo = null;

  const $ = (id) => container.querySelector("#" + id);
  const els = {
    segs: bounds.map((_, i) => $(`sk-seg-${i + 1}`)),
    segTxt: bounds.map((_, i) => $(`sk-segtxt-${i + 1}`)),
    segLbl: bounds.map((_, i) => $(`sk-seglbl-${i + 1}`)),
    leak: $("sk-leak"), leakPin: $("sk-leak-pin"), leakPulse: $("sk-leak-pulse"),
    leakTxt: $("sk-leak-txt"), valveL: $("sk-valve-l"), valveR: $("sk-valve-r"),
    isoLbl: $("sk-iso-lbl"), tin: $("sk-tin"), tout: $("sk-tout"),
  };
  const darkText = { GREEN: "#08140a", YELLOW: "#201600", ORANGE: "#2b1005", RED: "#fff" };

  els.leak.addEventListener("mouseenter", () => {
    if (leakInfo) { card.innerHTML = leakCardHtml(leakInfo); card.hidden = false; }
  });
  els.leak.addEventListener("mousemove", (e) => {
    const r = container.getBoundingClientRect();
    card.style.left = (e.clientX - r.left) + "px";
    card.style.top = (e.clientY - r.top - 12) + "px";
  });
  els.leak.addEventListener("mouseleave", () => { card.hidden = true; });

  const fmtM = (m) => lengthM > 20000
    ? (m / 1000).toFixed(2) + " km"
    : Math.round(m).toLocaleString() + " m";

  return {
    update(state) {
      // segment colour = GLOBAL line health (engine sends a uniform tier);
      // labels only flag the calculated leak / isolated segment
      (state.segments || []).forEach((s, i) => {
        if (!els.segs[i]) return;
        els.segs[i].setAttribute("fill", TIER[s.tier] || TIER.GREEN);
        if (els.segTxt[i]) {
          els.segTxt[i].setAttribute("fill", darkText[s.tier] || "#08140a");
        }
        if (els.segLbl[i]) {
          const rng = `${km(s.lo ?? bounds[i][0])}–${km(s.hi ?? bounds[i][1])} km`;
          els.segLbl[i].textContent =
            rng + (s.iso ? " · ISOLATED" : s.leak ? " · LEAK (calculated)" : "");
          els.segLbl[i].setAttribute("fill", s.iso || s.leak ? "var(--crit)" : "#7e8ea6");
        }
      });
      els.tin.textContent = state.tIn != null ? `t_in ${state.tIn.toFixed(2)} s` : "";
      els.tout.textContent = state.tOut != null ? `t_out ${state.tOut.toFixed(2)} s` : "";

      if (state.leak) {
        leakInfo = state.leak;
        const x = xOf(state.leak.x_m);
        els.leak.setAttribute("visibility", "visible");
        els.leakPulse.setAttribute("cx", x);
        els.leakPin.setAttribute("transform", `translate(${x} ${PIPE_Y - 3})`);
        els.leakTxt.setAttribute("x", Math.min(Math.max(x, 195), W - 195));
        els.leakTxt.textContent =
          `LEAK · ${fmtM(state.leak.x_m)} from inlet · ` +
          `${fmtM(state.leak.x_out_m)} from outlet`;
      } else {
        leakInfo = null;
        card.hidden = true;
        els.leak.setAttribute("visibility", "hidden");
      }

      if (state.isolated && state.leak && state.leak.segment) {
        const [lo, hi] = bounds[state.leak.segment - 1] || [0, lengthM];
        const xa = xOf(lo), xb = xOf(hi);
        els.valveL.setAttribute("transform", `translate(${xa} 0)`);
        els.valveR.setAttribute("transform", `translate(${xb} 0)`);
        els.valveL.setAttribute("visibility", "visible");
        els.valveR.setAttribute("visibility", "visible");
        els.isoLbl.setAttribute("x", (xa + xb) / 2);
        els.isoLbl.setAttribute("visibility", "visible");
      } else {
        els.valveL.setAttribute("visibility", "hidden");
        els.valveR.setAttribute("visibility", "hidden");
        els.isoLbl.setAttribute("visibility", "hidden");
      }
    },
  };
}
