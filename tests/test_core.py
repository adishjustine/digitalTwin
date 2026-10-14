"""Core tests. Run with:  python -m pytest -q   (or: python tests/test_core.py)"""
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from models.building import default_zones, step_temp
from models.digital_twin import DigitalTwin
from models.energy import energy_kwh
from models.optimizer import plan_zone
from simulation.controllers import BaselineController, DTController
from simulation.scenarios import SCENARIOS, normal_day
from simulation.simulator import compare, run

ZONES = default_zones()
OFFICE = ZONES[0]


# ---- model sanity ---------------------------------------------------------
def test_energy_unit_conversion():
    assert abs(energy_kwh(3000, 30) - 1.5) < 1e-9          # 3 kW for 30 min


def test_hvac_cools_and_heat_gains_warm():
    off = step_temp(25, 30, 5, "OFF", True, OFFICE)
    high = step_temp(25, 30, 5, "HIGH", True, OFFICE)
    assert high < off
    assert off > 25


# ---- Test 1: empty building -----------------------------------------------
def test_empty_building_lights_off_and_temps_bounded():
    s = normal_day()
    s = replace(s, occ=np.zeros_like(s.occ))
    for ctrl in (BaselineController(), DTController()):
        r = run(s, ctrl)
        assert r.log.light_on.sum() == 0
        assert r.log["T"].max() < 29.5                      # relaxed empty band
        assert r.summary["violation_min"] == 0              # nobody present


# ---- Test 2: high indoor temperature --------------------------------------
def test_high_indoor_temperature_selects_cooling():
    twin = DigitalTwin(ZONES)
    occ_pred = [10] * 31
    plan = plan_zone(twin, 0, 29.0, 30.0, occ_pred, "OFF")
    assert len(plan.candidates) == 27                       # alternatives evaluated
    assert plan.mode == "HIGH"
    assert plan.pred_temps[-1] < 29.0                       # violation reduced


# ---- Test 3: high outdoor temperature -------------------------------------
def test_outdoor_temperature_drives_warming_and_decision():
    mild = step_temp(24, 26, 5, "OFF", True, OFFICE)
    hot = step_temp(24, 40, 5, "OFF", True, OFFICE)
    assert hot > mild
    twin = DigitalTwin(ZONES)
    occ_pred = [10] * 31

    def chosen_energy(t_out):
        plan = plan_zone(twin, 0, 25.0, t_out, occ_pred, "OFF")
        return next(c for c in plan.candidates if c["chosen"])["energy_kwh"]

    assert chosen_energy(40.0) > chosen_energy(26.0)


# ---- Test 4: occupancy increase -------------------------------------------
def test_occupancy_adds_heat_and_twin_anticipates_arrivals():
    assert step_temp(24, 28, 20, "OFF", True, OFFICE) > step_temp(24, 28, 0, "OFF", True, OFFICE)
    twin = DigitalTwin(ZONES)
    # Meeting room, 09:50, empty now; a meeting is scheduled for 10:00
    pred = twin.predict_occupancy(1, 9 * 60 + 50, 0, 30)
    assert pred[0] == 0 and pred[15] > 0


# ---- Test 5: fair comparison -----------------------------------------------
def test_comparison_is_fair_and_savings_arithmetic_correct():
    s = normal_day()
    r = compare(s)
    b, d = r["baseline"], r["dt"]
    assert (b.log.t_out.values == d.log.t_out.values).all()
    assert (b.log.occ.values == d.log.occ.values).all()
    assert len(b.log) == len(d.log)
    assert abs(r["saved_kwh"] - (b.summary["total_kwh"] - d.summary["total_kwh"])) < 1e-9
    pct = r["saved_kwh"] / b.summary["total_kwh"] * 100
    assert abs(r["saved_pct"] - pct) < 1e-9
    r2 = compare(normal_day())                              # deterministic
    assert abs(r2["dt"].summary["total_kwh"] - d.summary["total_kwh"]) < 1e-9


# ---- Test 6: prediction accuracy -------------------------------------------
def test_prediction_mae_across_scenarios():
    for name, build in SCENARIOS.items():
        r = run(build(), DTController())
        assert np.isfinite(r.summary["mae_5min"]), name
        assert np.isfinite(r.summary["mae_30min"]), name
        assert r.summary["mae_5min"] < 0.5, name
        assert r.summary["mae_30min"] < 1.5, name


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"{len(tests)} tests passed")
