"""Run a controller against a scenario, and compare two controllers fairly."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from models.building import Building, default_zones
from models.energy import CO2_FACTOR, DEFAULT_TARIFF, co2_kg, cost, zone_power_w
from simulation.controllers import BaselineController, DTController
from simulation.scenarios import Scenario


@dataclass
class RunResult:
    controller: str
    scenario: str
    log: pd.DataFrame
    summary: dict
    plans: pd.DataFrame | None = None
    predictions: pd.DataFrame | None = None


def run(scenario: Scenario, controller, zones=None,
        tariff: float = DEFAULT_TARIFF, co2_factor: float = CO2_FACTOR) -> RunResult:
    zones = zones or default_zones()
    building = Building(zones, scenario.init_temps)
    controller.reset(zones)
    n = len(zones)
    rows = []

    for k in range(scenario.steps):
        minute = (scenario.start_minute + k) % 1440
        t_out = float(scenario.t_out[k])
        occ = [int(scenario.occ[z][k]) for z in range(n)]
        obs = [building.T[z] + float(scenario.noise[z][k]) for z in range(n)]

        actions = controller.decide(k, minute, obs, t_out, occ)
        if hasattr(controller, "evaluate"):
            controller.evaluate(k, list(building.T))

        for z, cfg in enumerate(zones):
            T = building.T[z]
            mode, light = actions[z]
            p = zone_power_w(cfg, mode, light)
            occupied = occ[z] > 0
            excess = 0.0
            if occupied:
                excess = max(0.0, T - cfg.comfort_max, cfg.comfort_min - T)
            rows.append({
                "k": k, "minute": minute, "zone": z, "zone_name": cfg.name,
                "T": T, "T_obs": obs[z], "t_out": t_out, "occ": occ[z],
                "hvac_mode": mode, "light_on": light,
                "hvac_w": p["hvac"], "light_w": p["light"],
                "equip_w": p["equip"], "total_w": p["total"],
                "violation": 1 if excess > 0 else 0, "excess_degc": excess})
        building.step(actions, t_out, occ)

    log = pd.DataFrame(rows)
    hours = 1.0 / 60.0
    hvac_kwh = log.hvac_w.sum() / 1000 * hours
    light_kwh = log.light_w.sum() / 1000 * hours
    equip_kwh = log.equip_w.sum() / 1000 * hours
    total_kwh = hvac_kwh + light_kwh + equip_kwh

    # Heat stored in the building at the end vs the start, as electricity
    # equivalent. Lets us see whether "savings" were just deferred cooling.
    stored = sum((building.T[z] - scenario.init_temps[z]) * cfg.C / (cfg.cop * 3.6e6)
                 for z, cfg in enumerate(zones))

    summary = {
        "total_kwh": total_kwh,
        "hvac_kwh": hvac_kwh,
        "light_kwh": light_kwh,
        "equip_kwh": equip_kwh,
        "controllable_kwh": hvac_kwh + light_kwh,
        "stored_heat_kwh": stored,
        "adjusted_total_kwh": total_kwh + stored,
        "cost": cost(total_kwh, tariff),
        "co2_kg": co2_kg(total_kwh, co2_factor),
        "violation_min": int(log.violation.sum()),
        "violation_degmin": float(log.excess_degc.sum()),
        "peak_kw": float(log.groupby("k").total_w.sum().max() / 1000),
        "end_temp_mean": float(sum(building.T) / n),
    }
    result = RunResult(controller.name, scenario.name, log, summary)
    if isinstance(controller, DTController):
        result.plans = controller.plans_df()
        result.predictions = controller.predictions_df()
        summary["mae_5min"] = controller.twin.mae("5min")
        summary[f"mae_{controller.horizon}min"] = controller.twin.mae(f"{controller.horizon}min")
    return result


def _pct(saved: float, base: float) -> float:
    return saved / base * 100.0 if base > 0 else 0.0


def compare(scenario: Scenario, tariff: float = DEFAULT_TARIFF,
            baseline=None, dt=None) -> dict:
    """Run both controllers on the identical scenario table."""
    base = run(scenario, baseline or BaselineController(), tariff=tariff)
    twin = run(scenario, dt or DTController(), tariff=tariff)
    b, d = base.summary, twin.summary
    return {
        "scenario": scenario.name,
        "baseline": base,
        "dt": twin,
        "saved_kwh": b["total_kwh"] - d["total_kwh"],
        "saved_pct": _pct(b["total_kwh"] - d["total_kwh"], b["total_kwh"]),
        "controllable_saved_pct": _pct(b["controllable_kwh"] - d["controllable_kwh"],
                                       b["controllable_kwh"]),
        "adjusted_saved_pct": _pct(b["adjusted_total_kwh"] - d["adjusted_total_kwh"],
                                   b["adjusted_total_kwh"]),
        "cost_saved": b["cost"] - d["cost"],
        "co2_saved_kg": b["co2_kg"] - d["co2_kg"],
        "violation_min_baseline": b["violation_min"],
        "violation_min_dt": d["violation_min"],
    }
