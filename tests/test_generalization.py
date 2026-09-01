"""Generalization sweep: the unmodified engine must detect and localize
leaks it has never seen (any position, depth, sharpness, noise level) and
must stay silent on no-leak control scenarios (the BLIND_07 analogue).

Targets: localization error <= 2% of pipeline length (full-marks band),
arrival times within +/-100 ms of ground truth + one sample of latency,
zero leak alarms and zero isolations on controls.
"""

import pytest

from simulator.generate import ScenarioSpec
from simulator.harness import run_scenario

LEAK_CASES = [
    # (x_m, leak_t, noise, front_frac, base_in, base_out)
    (800.0, 3.0, 0.02, 0.10, 60.0, 55.0),
    (1500.0, 6.0, 0.05, 0.08, 60.0, 55.0),
    (2400.0, 2.0, 0.02, 0.10, 60.0, 55.0),
    (3300.0, 4.0, 0.10, 0.12, 60.0, 55.0),
    (5000.0, 5.0, 0.05, 0.08, 72.0, 64.0),
    (6100.0, 3.5, 0.15, 0.10, 60.0, 55.0),
    (7200.0, 5.0, 0.08, 0.12, 85.0, 78.0),
    (8600.0, 4.0, 0.05, 0.10, 60.0, 55.0),
    (9300.0, 6.0, 0.10, 0.10, 60.0, 55.0),
    (4200.0, 8.0, 0.25, 0.12, 60.0, 55.0),   # heavy noise
    (2700.0, 5.0, 0.02, 0.04, 60.0, 55.0),   # gentle front
    (7800.0, 3.0, 0.20, 0.15, 95.0, 88.0),   # noisy, different baselines
]

CONTROL_CASES = [
    ScenarioSpec(name="ctrl_quiet", leak=False, duration_s=60, noise_in=0.02,
                 noise_out=0.02, seed=101),
    ScenarioSpec(name="ctrl_noisy", leak=False, duration_s=60, noise_in=0.20,
                 noise_out=0.25, seed=102),
    ScenarioSpec(name="ctrl_sinus", leak=False, duration_s=60, noise_in=0.10,
                 noise_out=0.10, drift_period_s=20.0, drift_amp_bar=0.4, seed=103),
    ScenarioSpec(name="ctrl_slow_ramp", leak=False, duration_s=60, noise_in=0.05,
                 noise_out=0.05, drift_bar_per_s=-0.02, seed=104),
    ScenarioSpec(name="ctrl_spikes", leak=False, duration_s=60, noise_in=0.08,
                 noise_out=0.08,
                 spike_times=((12.0, -1.2, "inlet"), (25.0, -1.5, "outlet"),
                              (40.0, -0.9, "inlet")), seed=105),
    ScenarioSpec(name="ctrl_noisy_drift", leak=False, duration_s=90, noise_in=0.15,
                 noise_out=0.15, drift_bar_per_s=-0.008,
                 drift_period_s=30.0, drift_amp_bar=0.3, seed=106),
]


@pytest.mark.parametrize("x,leak_t,noise,front,bin_,bout", LEAK_CASES)
def test_leak_detected_and_localized(x, leak_t, noise, front, bin_, bout):
    spec = ScenarioSpec(
        name=f"leak_{int(x)}m_n{noise}", leak_x_m=x, leak_t_s=leak_t,
        noise_in=noise, noise_out=noise, front_drop_frac=front,
        base_in=bin_, base_out=bout, final_frac=0.52,
        duration_s=leak_t + 25.0, seed=int(x) % 97 + 5)
    r = run_scenario(spec)
    assert r["leak_alarmed"], f"leak not alarmed: {r}"
    assert r["isolated"], f"virtual isolation did not fire: {r}"
    assert r["x_m"] is not None, f"no localization: {r}"
    assert r["error_pct"] <= 2.0, f"localization outside full-marks band: {r}"
    # one 100 ms sample of front-rise latency is inherent to sampled data
    assert abs(r["t_in"] - r["t_in_ref"]) <= 0.20, r
    assert abs(r["t_out"] - r["t_out_ref"]) <= 0.20, r


@pytest.mark.parametrize("spec", CONTROL_CASES, ids=lambda s: s.name)
def test_controls_never_alarm(spec):
    r = run_scenario(spec)
    assert not r["leak_alarmed"], f"FALSE POSITIVE on control: {r}"
    assert not r["isolated"], f"false isolation on control: {r}"
