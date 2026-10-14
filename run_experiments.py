"""Run every predefined scenario with both controllers and print/save results.

    python run_experiments.py
"""
from pathlib import Path

import pandas as pd

from simulation.scenarios import SCENARIOS
from simulation.simulator import compare


def main() -> pd.DataFrame:
    rows = []
    for name, build in SCENARIOS.items():
        r = compare(build())
        b, d = r["baseline"].summary, r["dt"].summary
        rows.append({
            "Scenario": name,
            "Baseline kWh": round(b["total_kwh"], 2),
            "DT kWh": round(d["total_kwh"], 2),
            "Saved %": round(r["saved_pct"], 1),
            "Saved % (HVAC+light only)": round(r["controllable_saved_pct"], 1),
            "Saved % (adj. for stored heat)": round(r["adjusted_saved_pct"], 1),
            "Baseline comfort-viol min": b["violation_min"],
            "DT comfort-viol min": d["violation_min"],
            "Cost saved (INR)": round(r["cost_saved"], 1),
            "CO2 saved (kg)": round(r["co2_saved_kg"], 2),
            "Twin MAE 5min (C)": round(d["mae_5min"], 3),
            "Twin MAE 30min (C)": round(d["mae_30min"], 3),
        })
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_columns", None)
    print(df.to_string(index=False))
    Path("data").mkdir(exist_ok=True)
    df.to_csv("data/results.csv", index=False)
    print("\nSaved to data/results.csv")
    return df


if __name__ == "__main__":
    main()
