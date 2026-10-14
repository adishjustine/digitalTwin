"""Controllers: a conventional reactive BEMS and the digital-twin MPC BEMS."""
from __future__ import annotations

import pandas as pd

from models.building import ZoneConfig
from models.digital_twin import DigitalTwin
from models.optimizer import plan_zone


class BaselineController:
    """Conventional BEMS: thermostat with hysteresis + occupancy-sensor lights.

    Reacts to the *current* temperature and occupancy only. Lights stay on for
    `light_timeout` minutes after a zone empties (typical sensor timer).
    This is a reasonable controller, not a deliberately wasteful one.
    """
    name = "Conventional BEMS"

    def __init__(self, cool_on: float = 25.0, cool_high: float = 26.0,
                 cool_off: float = 23.0, empty_on: float = 28.0,
                 empty_off: float = 27.0, light_timeout: int = 15):
        self.cool_on, self.cool_high, self.cool_off = cool_on, cool_high, cool_off
        self.empty_on, self.empty_off = empty_on, empty_off
        self.light_timeout = light_timeout

    def reset(self, zones: list[ZoneConfig]) -> None:
        n = len(zones)
        self.mode = ["OFF"] * n
        self.last_occ = [-10**9] * n

    def decide(self, k, minute, obs_T, t_out, occ):
        actions = []
        for i, T in enumerate(obs_T):
            if occ[i] > 0:
                self.last_occ[i] = k
            light = (k - self.last_occ[i]) <= self.light_timeout
            prev = self.mode[i]
            if occ[i] > 0:
                if T > self.cool_high:
                    m = "HIGH"
                elif T > self.cool_on or (prev != "OFF" and T > self.cool_off):
                    m = "LOW"
                else:
                    m = "OFF"
            else:
                if T > self.empty_on or (prev != "OFF" and T > self.empty_off):
                    m = "LOW"
                else:
                    m = "OFF"
            self.mode[i] = m
            actions.append((m, light))
        return actions


class DTController:
    """Digital-twin MPC: re-plans every `interval` minutes using the twin."""
    name = "Digital-twin BEMS"

    def __init__(self, horizon: int = 30, interval: int = 5, **optimizer_kwargs):
        self.horizon = horizon
        self.interval = interval
        self.opt_kwargs = optimizer_kwargs

    def reset(self, zones: list[ZoneConfig]) -> None:
        self.twin = DigitalTwin(zones, horizon=self.horizon)
        n = len(zones)
        self.cmd = ["OFF"] * n
        self.plans = [None] * n
        self.plan_rows: list[dict] = []
        self.estimates: list[dict] = []

    def decide(self, k, minute, obs_T, t_out, occ):
        T_est = self.twin.assimilate(obs_T)
        n = len(obs_T)
        if k % self.interval == 0:
            for z in range(n):
                occ_pred = self.twin.predict_occupancy(z, minute, occ[z], self.horizon)
                plan = plan_zone(self.twin, z, T_est[z], t_out, occ_pred,
                                 self.cmd[z], horizon=self.horizon,
                                 **self.opt_kwargs)
                self.cmd[z] = plan.mode
                self.plans[z] = plan
                self.twin.log_prediction(k, k + self.interval, z,
                                         plan.pred_temps[self.interval], "5min")
                self.twin.log_prediction(k, k + self.horizon, z,
                                         plan.pred_temps[self.horizon], f"{self.horizon}min")
                for c in plan.candidates:
                    self.plan_rows.append({
                        "k": k, "zone": z, "plan": c["label"],
                        "first_mode": c["first_mode"], "min_temp": c["min_temp"],
                        "max_temp": c["max_temp"], "energy_kwh": c["energy_kwh"],
                        "feasible": c["feasible"], "reason": c["reason"],
                        "chosen": c["chosen"]})
        actions = [(self.cmd[z], occ[z] > 0) for z in range(n)]
        for z in range(n):
            self.estimates.append({"k": k, "zone": z, "T_est": T_est[z]})
        self.twin.remember(actions, t_out, occ)
        return actions

    def evaluate(self, k, true_T) -> None:
        """Evaluation only: score due predictions against the true temperature."""
        self.twin.score(k, true_T)

    def plans_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.plan_rows)

    def predictions_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.twin.records)
