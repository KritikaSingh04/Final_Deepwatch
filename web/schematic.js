/* 2D pipeline schematic — SVG, five standardized logical segments. */

import { leakCardHtml } from "/static/leakcard.js";

const TIER = {
  GREEN: "var(--good)", YELLOW: "var(--warn)",
  ORANGE: "var(--serious)", RED: "var(--crit)",
};
const TIER_LABEL = { GREEN: "Healthy", YELLOW: "Caution", ORANGE: "Degraded", RED: "Critical" };

const W = 1000, H = 168, PIPE_X0 = 92, PIPE_X1 = 908, PIPE_Y = 78, PIPE_H = 24;

export function initSchematic(container, lengthM) {
  const segW = (PIPE_X1 - PIPE_X0) / 5;
  const xOf = (m) => PIPE_X0 + (m / lengthM) * (PIPE_X1 - PIPE_X0);

  let segs = "", segLabels = "", ticks = "";
  for (let i = 0; i < 5; i++) {
    const x = PIPE_X0 + i * segW;
    segs += `<rect id="sk-seg-${i + 1}" x="${x + 2}" y="${PIPE_Y}" width="${segW - 4}"
      height="${PIPE_H}" rx="5" fill="var(--good)" stroke="rgba(0,0,0,.35)"/>
      <text id="sk-segtxt-${i + 1}" x="${x + segW / 2}" y="${PIPE_Y + PIPE_H / 2 + 3.5}"
      text-anchor="middle" font-size="10.5" font-weight="700" fill="#08140a">S${i + 1}</text>`;
    segLabels += `<text id="sk-seglbl-${i + 1}" x="${x + segW / 2}" y="${PIPE_Y + PIPE_H + 16}"
      text-anchor="middle" font-size="9" fill="#7e8ea6">${i * 2}–${i * 2 + 2} km</text>`;
  }
  for (let km = 0; km <= 10; km += 2) {
    const x = xOf(km * 1000);
    ticks += `<line x1="${x}" y1="${PIPE_Y - 10}" x2="${x}" y2="${PIPE_Y - 4}"
      stroke="#2c3b57"/><text x="${x}" y="${PIPE_Y - 15}" text-anchor="middle"
      font-size="8.5" fill="#7e8ea6">${km} km</text>`;
  }

  container.innerHTML = `
  <svg viewBox="0 0 ${W} ${H}" font-family="system-ui, sans-serif" role="img"
       aria-label="Pipeline schematic with five segments">
    <!-- inlet / outlet stations -->
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

    <!-- flow arrows -->
    <text x="${PIPE_X0 + 8}" y="${PIPE_Y + PIPE_H + 34}" font-size="9"
          fill="#7e8ea6">flow →</text>

    <!-- isolation valves (hidden until isolation) -->
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

    <!-- leak marker -->
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

  // dual-ended hover card anchored near the leak pin
  const card = document.createElement("div");
  card.className = "leak-card";
  card.hidden = true;
  container.appendChild(card);
  let leakInfo = null;

  const $ = (id) => container.querySelector("#" + id);
  const els = {
    segs: [1, 2, 3, 4, 5].map((i) => $(`sk-seg-${i}`)),
    segTxt: [1, 2, 3, 4, 5].map((i) => $(`sk-segtxt-${i}`)),
    segLbl: [1, 2, 3, 4, 5].map((i) => $(`sk-seglbl-${i}`)),
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

  return {
    update(state) {
      // state: {segments:[{tier,leak,iso}], leak, isolated, tIn, tOut}
      // segment colour = GLOBAL line health (engine sends a uniform tier);
      // labels only flag the calculated leak / isolated segment
      (state.segments || []).forEach((s, i) => {
        els.segs[i].setAttribute("fill", TIER[s.tier] || TIER.GREEN);
        els.segTxt[i].setAttribute("fill", darkText[s.tier] || "#08140a");
        const km = `${i * 2}–${i * 2 + 2} km`;
        els.segLbl[i].textContent =
          km + (s.iso ? " · ISOLATED" : s.leak ? " · LEAK (calculated)" : "");
        els.segLbl[i].setAttribute("fill", s.iso || s.leak ? "var(--crit)" : "#7e8ea6");
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
          `LEAK · ${Math.round(state.leak.x_m).toLocaleString()} m from inlet · ` +
          `${Math.round(state.leak.x_out_m).toLocaleString()} m from outlet`;
      } else {
        leakInfo = null;
        card.hidden = true;
        els.leak.setAttribute("visibility", "hidden");
      }

      if (state.isolated && state.leak) {
        const seg = state.leak.segment;
        const xa = xOf((seg - 1) * 2000), xb = xOf(seg * 2000);
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
