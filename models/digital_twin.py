"""Digital twin: a virtual copy of the building that is corrected by sensor
data and used to predict the future.

The twin deliberately uses slightly *wrong* parameters (UA +10 %, C -5 %) so
its predictions have a realistic, non-zero error that can be measured.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from models.building import ZoneConfig, scheduled_occupancy, step_temp


class DigitalTwin:
    def __init__(self, zones: list[ZoneConfig], horizon: int = 30,
                 ua_error: float = 1.10, c_error: float = 0.95,
                 gain: float = 0.3):
        self.real_zones = list(zones)
        self.zones = [replace(z, UA=z.UA * ua_error, C=z.C * c_error)
                      for z in zones]
        self.horizon = horizon
        self.gain = gain                  # correction gain toward observations
        self.T_est: list[float | None] = [None] * len(zones)
        self._prev = None                 # (actions, t_out, occ) of last step
        self._pending: list[tuple] = []   # (target_k, zone, predicted, label, made_k)
        self.records: list[dict] = []     # resolved predictions

    # ---- state estimation -------------------------------------------------
    def assimilate(self, obs_T: list[float]) -> list[float]:
        """Predict one step with the model, then correct with the sensor."""
        if self.T_est[0] is None or self._prev is None:
            self.T_est = [float(t) for t in obs_T]
        else:
            actions, t_out, occ = self._prev
            for i, z in enumerate(self.zones):
                pred = step_temp(self.T_est[i], t_out, occ[i],
                                 actions[i][0], actions[i][1], z)
                self.T_est[i] = pred + self.gain * (obs_T[i] - pred)
        return list(self.T_est)

    def remember(self, actions, t_out: float, occ) -> None:
        self._prev = (list(actions), t_out, list(occ))

    # ---- prediction --------------------------------------------------------
    def predict_occupancy(self, zone_idx: int, minute_of_day: int,
                          current_occ: int, horizon: int | None = None) -> list[int]:
        """Current occupancy shifted by the *scheduled change* ahead.

        Index 0 is now. This is a simple schedule-based estimate; it has no
        confidence value because none has been measured.
        """
        h = self.horizon if horizon is None else horizon
        cfg = self.zones[zone_idx]
        base = scheduled_occupancy(cfg, minute_of_day)
        return [max(0, int(round(current_occ + scheduled_occupancy(cfg, minute_of_day + j) - base)))
                for j in range(h + 1)]

    def simulate(self, zone_idx: int, T0: float, t_out: float,
                 occ_pred: list[int], modes: list[str]):
        """Roll the twin forward. Returns (temps[0..H], hvac+light kWh).

        Outdoor temperature is assumed constant (persistence forecast).
        """
        cfg = self.zones[zone_idx]
        T = T0
        temps = [T]
        energy_wh = 0.0
        for j, mode in enumerate(modes):
            light_on = occ_pred[j] > 0
            T = step_temp(T, t_out, occ_pred[j], mode, light_on, cfg)
            temps.append(T)
            energy_wh += (cfg.hvac_elec_w[mode]
                          + (cfg.light_w if light_on else 0.0)) / 60.0
        return temps, energy_wh / 1000.0

    # ---- accuracy tracking -------------------------------------------------
    def log_prediction(self, made_k: int, target_k: int, zone_idx: int,
                       predicted: float, label: str) -> None:
        self._pending.append((target_k, zone_idx, predicted, label, made_k))

    def score(self, k: int, true_T: list[float]) -> None:
        """Compare due predictions with the actual simulated temperature."""
        still = []
        for target_k, z, pred, label, made_k in self._pending:
            if target_k == k:
                err = true_T[z] - pred
                self.records.append({
                    "made_at": made_k, "target": target_k, "zone": z,
                    "label": label, "predicted": pred, "actual": true_T[z],
                    "error": err, "abs_error": abs(err)})
            else:
                still.append((target_k, z, pred, label, made_k))
        self._pending = still

    def mae(self, label: str | None = None, zone: int | None = None) -> float:
        rows = [r for r in self.records
                if (label is None or r["label"] == label)
                and (zone is None or r["zone"] == zone)]
        return float(np.mean([r["abs_error"] for r in rows])) if rows else float("nan")
