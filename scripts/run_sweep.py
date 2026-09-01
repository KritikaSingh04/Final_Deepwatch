"""Generalization sweep — prints the validation table used in the
Technical Design Report and live demos.

Runs the UNMODIFIED AnalyticsEngine over a grid of generated scenarios
(leak position x noise x front sharpness) plus no-leak controls, and
reports detection, localization error and false-positive counts.

Usage:  python -m scripts.run_sweep [--seed N]
"""

from __future__ import annotations

import argparse
import random

from simulator.generate import ScenarioSpec
from simulator.harness import run_scenario


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    positions = [600, 1500, 2400, 3300, 4200, 5000, 5900, 6800, 7700, 8600, 9400]
    noises = [0.02, 0.10, 0.25]
    leak_rows = []
    for x in positions:
        for nz in noises:
            spec = ScenarioSpec(
                name=f"x={x} σ={nz}", leak_x_m=x,
                leak_t_s=round(rng.uniform(2.5, 8.0), 1),
                noise_in=nz, noise_out=nz,
                front_drop_frac=rng.choice([0.06, 0.10, 0.14]),
                final_frac=rng.choice([0.45, 0.52, 0.57]),
                base_in=rng.choice([60.0, 72.0, 85.0]),
                base_out=rng.choice([52.0, 55.0, 64.0]),
                duration_s=34.0, seed=rng.randrange(10_000))
            leak_rows.append(run_scenario(spec))

    controls = []
    for i in range(8):
        spec = ScenarioSpec(
            name=f"control_{i}", leak=False, duration_s=70,
            noise_in=rng.choice([0.03, 0.1, 0.2]),
            noise_out=rng.choice([0.03, 0.1, 0.2]),
            drift_bar_per_s=rng.choice([0.0, -0.01, -0.02]),
            drift_period_s=rng.choice([0.0, 18.0, 30.0]),
            drift_amp_bar=rng.choice([0.0, 0.3, 0.5]),
            spike_times=((rng.uniform(10, 60), -rng.uniform(0.6, 1.6),
                          rng.choice(["inlet", "outlet"])),),
            seed=rng.randrange(10_000))
        controls.append(run_scenario(spec))

    print(f"\n{'scenario':<18}{'alarmed':<9}{'X calc':>9}{'X ref':>8}"
          f"{'err m':>8}{'err %':>7}   seg")
    print("-" * 66)
    detected = 0
    errs = []
    for r in leak_rows:
        ok = r["leak_alarmed"] and r["x_m"] is not None
        detected += ok
        if ok:
            errs.append(r["error_pct"])
        x_c = r["x_m"] if r["x_m"] is not None else float("nan")
        e_m = r.get("error_m");  e_m = e_m if e_m is not None else float("nan")
        e_p = r.get("error_pct"); e_p = e_p if e_p is not None else float("nan")
        print(f"{r['name']:<18}{str(r['leak_alarmed']):<9}"
              f"{x_c:>9.0f}{r['x_ref']:>8.0f}{e_m:>8.1f}{e_p:>7.2f}"
              f"   S{r['segment']}")

    fp = sum(1 for r in controls if r["leak_alarmed"] or r["isolated"])
    print("-" * 66)
    print(f"leak scenarios : {len(leak_rows)}  detected: {detected} "
          f"({100 * detected / len(leak_rows):.0f}%)")
    if errs:
        print(f"localization   : mean {sum(errs)/len(errs):.2f}%  "
              f"max {max(errs):.2f}%  "
              f"within 2% (full marks): {sum(e <= 2 for e in errs)}/{len(errs)}")
    print(f"no-leak controls: {len(controls)}  false alarms: {fp}")
    for r in controls:
        print(f"  {r['name']:<12} state={r['state']:<14} events={r['events']}")


if __name__ == "__main__":
    main()
