"""Synthetic telemetry generation.

Two producers:

1. `dev_replica()` — a faithful reconstruction of the Development Dataset
   from the reference telemetry log printed in the problem statement
   (uniform 100 ms sampling; the excerpt's skipped rows are filled by
   linear interpolation; the tail is extended until both sensors fall
   below 60% of baseline, as the PS specifies). Used until the official
   .xlsx/.csv is dropped into data/ — the loader treats both identically.

2. `generate(ScenarioSpec)` — a parametric blind-scenario generator:
   arbitrary leak location, event time, front sharpness, drop depth,
   noise level, baseline drift and no-leak controls. This powers the
   generalization test sweep: the unmodified engine must detect and
   localize scenarios it has never seen.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

from engine.npw import PIPELINE_LENGTH_M, WAVE_SPEED_MS


@dataclass
class ScenarioSpec:
    name: str = "scenario"
    leak: bool = True
    leak_x_m: float = 6500.0        # leak coordinate from inlet
    leak_t_s: float = 4.0           # instant the breach occurs
    duration_s: float = 40.0
    dt_s: float = 0.1               # 100 ms sampling, as in the PS
    base_in: float = 60.0
    base_out: float = 55.0
    noise_in: float = 0.02          # 1-sigma gaussian noise, bar
    noise_out: float = 0.02
    front_drop_frac: float = 0.10   # immediate front amplitude (fraction of baseline)
    front_tau_s: float = 0.15       # sharpness of the initial front
    final_frac: float = 0.50        # eventual plateau (fraction of baseline)
    decay_tau_s: float = 5.0        # slow decline toward the plateau
    drift_bar_per_s: float = 0.0    # slow common-mode operational drift
    drift_period_s: float = 0.0     # optional sinusoidal variation period
    drift_amp_bar: float = 0.0
    spike_times: tuple = ()         # single-sample glitches (t, delta_bar, sensor)
    length_m: float = PIPELINE_LENGTH_M   # engineering/scale scenarios may override
    wave_speed_ms: float = WAVE_SPEED_MS
    seed: int = 42

    @property
    def arrival_in(self) -> float:
        return self.leak_t_s + self.leak_x_m / self.wave_speed_ms

    @property
    def arrival_out(self) -> float:
        return self.leak_t_s + (self.length_m - self.leak_x_m) / self.wave_speed_ms


def generate(spec: ScenarioSpec):
    """Returns (times_s, p_in, p_out) lists."""
    rng = random.Random(spec.seed)
    n = int(round(spec.duration_s / spec.dt_s)) + 1
    times, pin, pout = [], [], []
    for i in range(n):
        t = round(i * spec.dt_s, 3)
        times.append(t)
        pin.append(_pressure(spec, t, spec.base_in, spec.noise_in,
                             spec.arrival_in if spec.leak else None, rng))
        pout.append(_pressure(spec, t, spec.base_out, spec.noise_out,
                              spec.arrival_out if spec.leak else None, rng))
    for (ts, delta, sensor) in spec.spike_times:
        idx = int(round(ts / spec.dt_s))
        if 0 <= idx < n:
            if sensor == "inlet":
                pin[idx] += delta
            else:
                pout[idx] += delta
    return times, pin, pout


def _pressure(spec: ScenarioSpec, t: float, base: float, noise: float,
              arrival: Optional[float], rng: random.Random) -> float:
    p = base
    if spec.drift_bar_per_s:
        p += spec.drift_bar_per_s * t
    if spec.drift_period_s and spec.drift_amp_bar:
        p += spec.drift_amp_bar * math.sin(2 * math.pi * t / spec.drift_period_s)
    if arrival is not None and t >= arrival:
        dtb = t - arrival
        front = spec.front_drop_frac * base * (1 - math.exp(-dtb / spec.front_tau_s))
        residual_frac = 1.0 - spec.front_drop_frac - spec.final_frac
        slow = residual_frac * base * (1 - math.exp(-dtb / spec.decay_tau_s))
        p -= front + max(slow, 0.0)
    p += rng.gauss(0.0, noise)
    return round(p, 3)


# ----------------------------------------------------------------------
# Development-dataset replica (from the PS reference telemetry log)
# ----------------------------------------------------------------------

# Rows exactly as printed in the problem statement (relative ms, inlet, outlet, flag)
_PS_ROWS = [
    (0, 60.01, 55.08, "NORMAL"), (100, 59.99, 55.10, "NORMAL"),
    (200, 60.03, 55.09, "NORMAL"), (300, 60.00, 55.11, "NORMAL"),
    (400, 60.02, 55.07, "NORMAL"), (500, 60.01, 55.10, "NORMAL"),
    (600, 59.98, 55.12, "NORMAL"), (700, 60.04, 55.06, "NORMAL"),
    (800, 60.01, 55.09, "NORMAL"), (900, 60.00, 55.08, "NORMAL"),
    (1000, 60.02, 55.11, "NORMAL"), (1100, 59.99, 55.10, "NORMAL"),
    (1200, 60.03, 55.07, "NORMAL"), (1300, 60.01, 55.12, "NORMAL"),
    (1400, 60.00, 55.09, "NORMAL"), (1500, 60.02, 55.08, "NORMAL"),
    (1600, 60.01, 55.11, "NORMAL"), (1700, 59.98, 55.10, "NORMAL"),
    (1800, 60.04, 55.07, "NORMAL"), (1900, 60.01, 55.12, "NORMAL"),
    (2000, 60.00, 55.09, "NORMAL"), (2100, 60.02, 55.08, "NORMAL"),
    (2200, 60.01, 55.11, "NORMAL"), (2300, 59.99, 55.10, "NORMAL"),
    (2400, 54.20, 55.09, "ANOMALY_INLET"), (2500, 48.50, 55.11, "LEAK_PROPAGATING"),
    (2600, 47.80, 55.12, "LEAK_PROPAGATING"), (2700, 47.10, 55.09, "LEAK_PROPAGATING"),
    (2800, 46.50, 55.10, "LEAK_PROPAGATING"), (2900, 46.20, 55.11, "LEAK_PROPAGATING"),
    (3000, 46.00, 55.08, "LEAK_PROPAGATING"), (3100, 45.90, 55.12, "LEAK_PROPAGATING"),
    (3200, 45.80, 55.09, "LEAK_PROPAGATING"), (3300, 45.70, 55.07, "LEAK_PROPAGATING"),
    (3400, 45.60, 55.10, "LEAK_PROPAGATING"), (3500, 45.50, 55.08, "LEAK_PROPAGATING"),
    (4000, 45.40, 55.11, "LEAK_PROPAGATING"), (4500, 45.30, 55.09, "LEAK_PROPAGATING"),
    (5000, 45.20, 55.07, "LEAK_PROPAGATING"), (5500, 45.10, 55.12, "LEAK_PROPAGATING"),
    (6000, 45.05, 55.08, "LEAK_PROPAGATING"), (6500, 45.03, 55.09, "LEAK_PROPAGATING"),
    (7000, 45.02, 55.06, "LEAK_PROPAGATING"), (7300, 45.01, 55.05, "LEAK_PROPAGATING"),
    (7400, 45.00, 55.00, "LEAK_PROPAGATING"), (7500, 44.99, 54.50, "LEAK_PROPAGATING"),
    (7600, 44.97, 49.30, "ANOMALY_OUTLET"), (7700, 45.02, 43.15, "CRITICAL_DROP"),
    (7800, 45.01, 40.20, "CRITICAL_DROP"), (7900, 45.03, 38.50, "CRITICAL_DROP"),
]


def dev_replica():
    """Returns (times_s, p_in, p_out, flags) at uniform 100 ms sampling.

    The PS states the real Development Dataset is uniformly sampled at
    100 ms and continues until both sensors fall below 60% of baseline
    (RED - Critical). Missing 100 ms rows inside the excerpt are filled
    by linear interpolation; the tail extends the decline accordingly.
    """
    rng = random.Random(7)
    by_ms = {ms: (pi, po, fl) for ms, pi, po, fl in _PS_ROWS}
    known_ms = [ms for ms, *_ in _PS_ROWS]
    times, pin, pout, flags = [], [], [], []

    ms = 0
    while ms <= 7900:
        if ms in by_ms:
            pi, po, fl = by_ms[ms]
        else:
            lo = max(k for k in known_ms if k < ms)
            hi = min(k for k in known_ms if k > ms)
            f = (ms - lo) / (hi - lo)
            pi = round(by_ms[lo][0] + f * (by_ms[hi][0] - by_ms[lo][0]), 2)
            po = round(by_ms[lo][1] + f * (by_ms[hi][1] - by_ms[lo][1]), 2)
            fl = "LEAK_PROPAGATING"
        times.append(ms / 1000.0)
        pin.append(pi)
        pout.append(po)
        flags.append(fl)
        ms += 100

    # tail: exponential decline until both sensors are well below 60%
    t = 8.0
    while t <= 16.0:
        pi = 30.0 + 15.03 * math.exp(-(t - 7.9) / 4.0) + rng.gauss(0, 0.02)
        po = 28.0 + 10.50 * math.exp(-(t - 7.9) / 3.0) + rng.gauss(0, 0.02)
        times.append(round(t, 3))
        pin.append(round(pi, 2))
        pout.append(round(po, 2))
        flags.append("CRITICAL_DROP")
        t = round(t + 0.1, 3)
    return times, pin, pout, flags


# ----------------------------------------------------------------------
# CSV writers
# ----------------------------------------------------------------------

def write_csv(path, times, pin, pout, flags=None):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        header = ["Timestamp", "Relative Time (ms)",
                  "Inlet Pressure (Bar)", "Outlet Pressure (Bar)"]
        if flags is not None:
            header.append("Status Flag")
        w.writerow(header)
        for i, t in enumerate(times):
            total_ms = int(round(t * 1000))
            hh = 11
            mm, rem = divmod(total_ms, 60_000)
            ss, ms = divmod(rem, 1000)
            stamp = f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"
            row = [stamp, total_ms, pin[i], pout[i]]
            if flags is not None:
                row.append(flags[i])
            w.writerow(row)


# ----------------------------------------------------------------------
# Mock official evaluation workbook (multi-sheet XLSX)
# ----------------------------------------------------------------------

def make_mock_workbook(path, seed: int = 5):
    """Build a workbook shaped like the official evaluation file:
    a Read_Me sheet plus BLIND_01..BLIND_07, each an independent
    12-second scenario sampled every 100 ms (six leaks + one no-leak
    control). Returns {sheet_name: ScenarioSpec} for test assertions —
    the truths are NEVER written into the workbook."""
    import pandas as pd

    leaks = [1400.0, 3200.0, 5000.0, 6600.0, 8200.0, 9200.0]
    noises = [0.02, 0.05, 0.08, 0.10, 0.15, 0.06]
    specs = {}
    for i, (x, nz) in enumerate(zip(leaks, noises), start=1):
        specs[f"BLIND_{i:02d}"] = ScenarioSpec(
            name=f"BLIND_{i:02d}", leak_x_m=x,
            leak_t_s=1.8 if x > 8500 else 2.0,
            duration_s=12.0, noise_in=nz, noise_out=nz,
            front_drop_frac=0.12, final_frac=0.45, decay_tau_s=1.5,
            base_in=[60.0, 72.0, 65.0, 85.0, 60.0, 78.0][i - 1],
            base_out=[55.0, 64.0, 58.0, 78.0, 52.0, 70.0][i - 1],
            seed=seed * 100 + i)
    specs["BLIND_07"] = ScenarioSpec(
        name="BLIND_07", leak=False, duration_s=12.0,
        noise_in=0.12, noise_out=0.12,
        drift_period_s=6.0, drift_amp_bar=0.25, seed=seed * 100 + 7)

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame({
            "Evaluation workbook — READ ME": [
                "Each BLIND_xx sheet is an independent 12-second scenario",
                "sampled every 100 ms.",
                "Columns: Timestamp, Relative Time (ms),",
                "Inlet Pressure (Bar), Outlet Pressure (Bar).",
            ]}).to_excel(xw, sheet_name="Read_Me", index=False)
        for sheet, spec in specs.items():
            times, p_in, p_out = generate(spec)
            stamps = []
            for t in times:
                ms_total = int(round(t * 1000))
                mm, rem = divmod(ms_total, 60_000)
                ss, ms = divmod(rem, 1000)
                stamps.append(f"11:{mm:02d}:{ss:02d}.{ms:03d}")
            pd.DataFrame({
                "Timestamp": stamps,
                "Relative Time (ms)": [int(round(t * 1000)) for t in times],
                "Inlet Pressure (Bar)": p_in,
                "Outlet Pressure (Bar)": p_out,
            }).to_excel(xw, sheet_name=sheet, index=False)
    return specs


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = os.path.join(here, "data")
    os.makedirs(data, exist_ok=True)

    t, pi, po, fl = dev_replica()
    write_csv(os.path.join(data, "dev_dataset.csv"), t, pi, po, fl)

    demos = [
        ScenarioSpec(name="sample_blind_A_leak7200m", leak_x_m=7200, leak_t_s=5.0,
                     noise_in=0.08, noise_out=0.10, front_drop_frac=0.12,
                     final_frac=0.52, seed=11),
        ScenarioSpec(name="sample_blind_B_leak5000m", leak_x_m=5000, leak_t_s=3.0,
                     noise_in=0.05, noise_out=0.05, front_drop_frac=0.08,
                     final_frac=0.55, base_in=72.0, base_out=64.5, seed=23),
        ScenarioSpec(name="sample_blind_C_noleak_control", leak=False,
                     duration_s=60.0, noise_in=0.12, noise_out=0.15,
                     drift_period_s=25.0, drift_amp_bar=0.35,
                     spike_times=((14.0, -0.9, "outlet"), (33.0, -1.1, "inlet")),
                     seed=31),
    ]
    for spec in demos:
        ts, pin_, pout_ = generate(spec)
        write_csv(os.path.join(data, f"{spec.name}.csv"), ts, pin_, pout_)

    make_mock_workbook(os.path.join(data, "BLIND_MOCK_WORKBOOK.xlsx"))
    print("datasets written to", data)
