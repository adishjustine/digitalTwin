"""Live session: turns each telemetry message into a control command.

Transport-agnostic. The MQTT bridge, the in-memory fake device and the tests
all call `LiveSession.handle()`.
"""
from __future__ import annotations

import csv
import json
import math
import os
import time
from pathlib import Path

from integration.protocol import decode_telemetry, encode_command
from models.building import default_zones
from models.energy import zone_power_w
from simulation.controllers import DTController

# Anchored to the project folder, so the bridge and the dashboard agree on the
# files no matter which directory each one was started from.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class LiveSession:
    def __init__(self, horizon: int = 30, write_files: bool = True,
                 state_path: Path | str = DATA_DIR / "live_state.json",
                 log_path: Path | str = DATA_DIR / "live_log.csv"):
        self.horizon = horizon
        self.write_files = write_files
        self.state_path = Path(state_path)
        self.log_path = Path(log_path)
        self.zones = default_zones()
        self.history: list[dict] = []
        self.resets = 0
        self._new_run()
        if write_files:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._start_log()

    # ---- lifecycle ---------------------------------------------------------
    def _new_run(self) -> None:
        self.ctrl = DTController(horizon=self.horizon)
        self.ctrl.reset(self.zones)
        self.last_k = -1
        self.kwh = 0.0
        self.violation_min = 0
        self.ticks = 0

    def _start_log(self) -> None:
        with open(self.log_path, "w", newline="") as f:
            csv.writer(f).writerow(LOG_COLUMNS)

    # ---- main entry point --------------------------------------------------
    def handle(self, telemetry) -> str:
        """telemetry: JSON string or an already-decoded dict from decode_telemetry.

        Returns the command payload to publish. Raises ValueError for
        unusable telemetry (the caller should just skip that message).
        """
        msg = decode_telemetry(telemetry) if isinstance(telemetry, (str, bytes)) else telemetry
        k = msg["k"]
        if k <= self.last_k:                 # device restarted: start a fresh run
            self.resets += 1
            self._new_run()
            if self.write_files:
                self._start_log()

        actions = self.ctrl.decide(k, msg["minute"], msg["T"], msg["t_out"], msg["occ"])
        self.ctrl.evaluate(k, msg["T"])      # score due predictions vs the sensor reading
        self.last_k = k
        self.ticks += 1

        rows = []
        for z, cfg in enumerate(self.zones):
            mode, light = actions[z]
            p = zone_power_w(cfg, mode, light)
            T, occ = msg["T"][z], msg["occ"][z]
            excess = max(0.0, T - cfg.comfort_max, cfg.comfort_min - T) if occ > 0 else 0.0
            self.kwh += p["total"] / 1000.0 / 60.0
            if excess > 0:
                self.violation_min += 1
            rows.append([k, msg["minute"], z, cfg.name, round(T, 3), occ, mode,
                         int(light), p["total"], msg["t_out"],
                         "" if math.isnan(msg["hum"]) else msg["hum"], p["hvac"]])
        self.history.extend(rows)
        if self.write_files:
            with open(self.log_path, "a", newline="") as f:
                csv.writer(f).writerows(rows)
            self._write_state(msg, actions)
        return encode_command(k, actions)

    # ---- dashboard feed ----------------------------------------------------
    def _write_state(self, msg: dict, actions) -> None:
        zones = []
        for z, cfg in enumerate(self.zones):
            plan = self.ctrl.plans[z]
            cands = []
            if plan is not None:
                ordered = sorted(plan.candidates,
                                 key=lambda c: (not c["chosen"], not c["feasible"], c["energy_kwh"]))
                cands = [{"plan": c["label"], "first_mode": c["first_mode"],
                          "min_temp": round(c["min_temp"], 2), "max_temp": round(c["max_temp"], 2),
                          "energy_kwh": round(c["energy_kwh"], 3), "feasible": bool(c["feasible"]),
                          "reason": c["reason"], "chosen": bool(c["chosen"])}
                         for c in ordered[:12]]
            p = zone_power_w(cfg, *actions[z])
            zones.append({
                "name": cfg.name, "T": round(msg["T"][z], 2),
                "T_est": round(self.ctrl.twin.T_est[z], 2), "occ": msg["occ"][z],
                "mode": actions[z][0], "light": bool(actions[z][1]),
                "power_w": p["total"], "candidates": cands,
                "n_candidates": len(plan.candidates) if plan else 0,
                "n_feasible": sum(c["feasible"] for c in plan.candidates) if plan else 0})
        h = self.horizon
        state = {
            "updated": time.time(), "k": msg["k"], "minute": msg["minute"],
            "t_out": msg["t_out"], "hum": None if math.isnan(msg["hum"]) else msg["hum"],
            "kwh": self.kwh, "violation_min": self.violation_min,
            "mae_5min": _nan_to_none(self.ctrl.twin.mae("5min")),
            f"mae_{h}min": _nan_to_none(self.ctrl.twin.mae(f"{h}min")),
            "horizon": h, "resets": self.resets, "zones": zones}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, self.state_path)


LOG_COLUMNS = ["k", "minute", "zone", "zone_name", "T", "occ", "hvac_mode",
               "light_on", "total_w", "t_out", "hum", "hvac_w"]


def _nan_to_none(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x
