"""Shared validation harness: run the unmodified AnalyticsEngine over a
generated scenario (or any telemetry arrays) and collect the outcome."""

from __future__ import annotations

from engine.engine import AnalyticsEngine, EngineConfig, ALARM_STATES, ISOLATED
from engine.npw import localization_error_pct
from .generate import ScenarioSpec, generate


def run_stream(times, p_in, p_out, config: EngineConfig | None = None):
    engine = AnalyticsEngine(config)
    for t, pi, po in zip(times, p_in, p_out):
        engine.update(t, pi, po)
    return engine


def summarize(engine: AnalyticsEngine) -> dict:
    loc = engine.localization if (engine.localization
                                  and engine.localization.valid) else None
    return {
        "state": engine.state,
        "leak_alarmed": engine.state in ALARM_STATES,
        "isolated": engine.state == ISOLATED,
        "t_in": engine.inlet.arrival_time,
        "t_out": engine.outlet.arrival_time,
        "delta_t": loc.delta_t if loc else None,
        "x_m": loc.x_m if loc else None,
        "segment": loc.segment if loc else None,
        "loc_invalid": engine.localization_invalid,
        "severity": engine.severity,
        "detect_time": engine.stages["detect"],
        "isolation_time": engine.isolation_time,
        "events": len(engine.events),
    }


def run_scenario(spec: ScenarioSpec, config: EngineConfig | None = None) -> dict:
    times, p_in, p_out = generate(spec)
    engine = run_stream(times, p_in, p_out, config)
    result = {"name": spec.name, "leak_truth": spec.leak, **summarize(engine)}
    if spec.leak:
        result["x_ref"] = spec.leak_x_m
        result["t_in_ref"] = spec.arrival_in
        result["t_out_ref"] = spec.arrival_out
        if result["x_m"] is not None:
            result["error_pct"] = round(
                localization_error_pct(result["x_m"], spec.leak_x_m), 3)
            result["error_m"] = round(abs(result["x_m"] - spec.leak_x_m), 1)
    return result
