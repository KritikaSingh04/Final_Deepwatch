/* Rolling strip chart for streaming telemetry — canvas, crosshair + tooltip. */

const INK2 = "#a9b6c9", MUTED = "#7e8ea6", GRID = "#1c2739", AXIS = "#2c3b57";

export class StripChart {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {HTMLElement} tip tooltip element
   * @param {{color:string,label:string,windowS?:number}} opts
   */
  constructor(canvas, tip, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.tip = tip;
    this.color = opts.color;
    this.label = opts.label;
    this.windowS = opts.windowS ?? 35;
    this.ts = []; this.vs = []; this.bs = [];   // time, value, baseline
    this.markers = [];                          // {t, label}
    this.cursor = null;                         // mouse x in css px
    this.dirty = true;
    this._pad = { l: 44, r: 34, t: 10, b: 20 };

    new ResizeObserver(() => { this._resize(); }).observe(canvas);
    this._resize();

    canvas.addEventListener("mousemove", (e) => {
      const r = canvas.getBoundingClientRect();
      this.cursor = { x: e.clientX - r.left, y: e.clientY - r.top };
      this.dirty = true;
    });
    canvas.addEventListener("mouseleave", () => {
      this.cursor = null; this.tip.style.display = "none"; this.dirty = true;
    });
  }

  setSeries(ts, vs, bs) { this.ts = ts; this.vs = vs; this.bs = bs; this.dirty = true; }
  setMarkers(m) { this.markers = m; this.dirty = true; }
  clear() { this.markers = []; this.dirty = true; }

  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const { clientWidth: w, clientHeight: h } = this.canvas;
    if (w === 0 || h === 0) return;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w; this.h = h; this.dirty = true;
  }

  render() {
    if (!this.dirty || !this.w) return;
    this.dirty = false;
    const { ctx, w, h } = this;
    const P = this._pad;
    ctx.clearRect(0, 0, w, h);
    const n = this.ts.length;
    if (n < 2) { this._empty(); return; }

    const t1 = this.ts[n - 1];
    const t0 = Math.max(this.ts[0], t1 - this.windowS);
    let i0 = this._bisect(t0);
    if (i0 > 0) i0--;

    // y range over the visible slice, always including the baseline band
    let lo = Infinity, hi = -Infinity;
    for (let i = i0; i < n; i++) {
      const v = this.vs[i];
      if (v < lo) lo = v; if (v > hi) hi = v;
    }
    const base = this.bs[n - 1];
    lo = Math.min(lo, base * 0.97); hi = Math.max(hi, base * 1.015);
    const span = (hi - lo) || 1; lo -= span * 0.07; hi += span * 0.07;

    const X = (t) => P.l + ((t - t0) / (t1 - t0 || 1)) * (w - P.l - P.r);
    const Y = (v) => P.t + ((hi - v) / (hi - lo)) * (h - P.t - P.b);

    // grid + y labels
    ctx.font = "10px ui-monospace, Menlo, monospace";
    ctx.fillStyle = MUTED; ctx.strokeStyle = GRID; ctx.lineWidth = 1;
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) {
      const v = lo + ((hi - lo) * i) / ticks, y = Y(v);
      ctx.beginPath(); ctx.moveTo(P.l, y); ctx.lineTo(w - P.r, y); ctx.stroke();
      ctx.textAlign = "right"; ctx.fillText(v.toFixed(1), P.l - 5, y + 3);
    }
    // x labels
    ctx.textAlign = "center";
    for (let i = 0; i <= 5; i++) {
      const t = t0 + ((t1 - t0) * i) / 5;
      ctx.fillText(t.toFixed(0) + "s", X(t), h - 6);
    }

    // health guide lines from the learned baseline (95 / 80 / 60%)
    const guides = [[0.95, "95"], [0.80, "80"], [0.60, "60"]];
    ctx.setLineDash([3, 5]); ctx.strokeStyle = AXIS;
    ctx.textAlign = "left"; ctx.fillStyle = MUTED;
    for (const [f, lbl] of guides) {
      const v = base * f;
      if (v < lo || v > hi) continue;
      const y = Y(v);
      ctx.beginPath(); ctx.moveTo(P.l, y); ctx.lineTo(w - P.r, y); ctx.stroke();
      ctx.fillText(lbl + "%", w - P.r + 4, y + 3);
    }
    ctx.setLineDash([]);

    // baseline (dotted, series hue at low alpha)
    ctx.setLineDash([2, 4]); ctx.strokeStyle = this.color; ctx.globalAlpha = 0.5;
    const yb = Y(base);
    ctx.beginPath(); ctx.moveTo(P.l, yb); ctx.lineTo(w - P.r, yb); ctx.stroke();
    ctx.globalAlpha = 1; ctx.setLineDash([]);

    // series
    ctx.strokeStyle = this.color; ctx.lineWidth = 2;
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.beginPath();
    let started = false;
    const maxPts = w - P.l - P.r;                 // ~1 point per px
    const step = Math.max(1, Math.floor((n - i0) / maxPts));
    for (let i = i0; i < n; i += step) {
      const x = X(this.ts[i]), y = Y(this.vs[i]);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // arrival markers
    for (const m of this.markers) {
      if (m.t < t0 || m.t > t1) continue;
      const x = X(m.t);
      ctx.setLineDash([5, 4]); ctx.strokeStyle = "#e8eef7"; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(x, P.t); ctx.lineTo(x, h - P.b); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#e8eef7"; ctx.font = "600 10px ui-monospace, monospace";
      ctx.textAlign = x > w - 90 ? "right" : "left";
      ctx.fillText(`${m.label}=${m.t.toFixed(2)}s`, x + (x > w - 90 ? -5 : 5), P.t + 10);
    }

    // crosshair + tooltip
    if (this.cursor && this.cursor.x >= P.l && this.cursor.x <= w - P.r) {
      const tc = t0 + ((this.cursor.x - P.l) / (w - P.l - P.r)) * (t1 - t0);
      let i = this._bisect(tc);
      if (i >= n) i = n - 1;
      if (i > 0 && Math.abs(this.ts[i - 1] - tc) < Math.abs(this.ts[i] - tc)) i--;
      const x = X(this.ts[i]), y = Y(this.vs[i]);
      ctx.strokeStyle = "rgba(232,238,247,.35)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, P.t); ctx.lineTo(x, h - P.b); ctx.stroke();
      ctx.fillStyle = this.color;
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#0b111c"; ctx.lineWidth = 2; ctx.stroke();

      const ratio = this.bs[i] > 0 ? (this.vs[i] / this.bs[i]) * 100 : 100;
      this.tip.innerHTML =
        `t <b>${this.ts[i].toFixed(2)} s</b><br>` +
        `${this.label} <b>${this.vs[i].toFixed(2)} bar</b><br>` +
        `baseline ${this.bs[i].toFixed(2)} · <b>${ratio.toFixed(1)}%</b>`;
      this.tip.style.display = "block";
      const tw = this.tip.offsetWidth;
      this.tip.style.left = Math.min(x + 12, w - tw - 6) + "px";
      this.tip.style.top = Math.max(6, y - 54) + "px";
    } else {
      this.tip.style.display = "none";
    }
  }

  _empty() {
    const { ctx, w, h } = this;
    ctx.fillStyle = MUTED; ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("awaiting telemetry stream…", w / 2, h / 2);
  }

  _bisect(t) {
    let lo = 0, hi = this.ts.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.ts[mid] < t) lo = mid + 1; else hi = mid;
    }
    return lo;
  }
}
