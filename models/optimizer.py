"""Finite-candidate model predictive control for one zone.

Candidates are every HVAC mode sequence over `n_blocks` consecutive blocks
(3 modes ** 3 blocks = 27 plans over a 30-minute horizon). Each is simulated
with the digital twin. Plans that leave the comfort band are rejected, and the
cheapest feasible plan wins; only its first action is applied, then the
optimiser re-plans on the next control interval.

Lighting is not a decision variable: it follows occupancy (ON when the zone is
occupied, OFF when empty).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from models.building import HVAC_MODES
from models.digital_twin import DigitalTwin


@dataclass
class Plan:
    mode: str                 # first action to apply
    sequence: tuple           # full chosen block sequence
    pred_temps: list          # predicted temperatures under the chosen plan
    candidates: list          # list of dicts describing every candidate
    feasible_found: bool


def plan_zone(twin: DigitalTwin, zi: int, T0: float, t_out: float,
              occ_pred: list[int], last_mode: str, horizon: int = 30,
              n_blocks: int = 3, margin: float = 0.3,
              switch_penalty_kwh: float = 0.02,
              terminal_weight: float = 0.5, t_ref: float = 24.0) -> Plan:
    cfg = twin.zones[zi]
    block = -(-horizon // n_blocks)
    # kWh of electricity needed later to remove 1 degC of stored heat
    kwh_per_degc = cfg.C / (cfg.cop * 3.6e6)

    candidates = []
    for order, seq in enumerate(itertools.product(HVAC_MODES, repeat=n_blocks)):
        modes = [seq[min(j // block, n_blocks - 1)] for j in range(horizon)]
        temps, energy = twin.simulate(zi, T0, t_out, occ_pred, modes)

        over = under = 0.0
        for j in range(1, horizon + 1):
            if occ_pred[j] > 0:
                lo, hi = cfg.comfort_min + margin, cfg.comfort_max - margin
            else:
                lo, hi = cfg.relaxed_min + margin, cfg.relaxed_max - margin
            over += max(0.0, temps[j] - hi)
            under += max(0.0, lo - temps[j])
        violation = over + under
        feasible = violation < 1e-9

        reason = ""
        if over > 0:
            reason = f"too hot (max {max(temps[1:]):.1f}C)"
        if under > 0:
            reason = (reason + "; " if reason else "") + f"too cold (min {min(temps[1:]):.1f}C)"

        terminal = terminal_weight * max(0.0, temps[-1] - t_ref) * kwh_per_degc
        switch = switch_penalty_kwh if seq[0] != last_mode else 0.0
        candidates.append({
            "order": order,
            "sequence": seq,
            "label": "→".join(seq),
            "first_mode": seq[0],
            "min_temp": min(temps[1:]),
            "max_temp": max(temps[1:]),
            "end_temp": temps[-1],
            "energy_kwh": energy,
            "cost_kwh": energy + terminal + switch,
            "violation": violation,
            "feasible": feasible,
            "reason": reason or "ok",
            "temps": temps,
        })

    feasible = [c for c in candidates if c["feasible"]]
    if feasible:
        best = min(feasible, key=lambda c: (c["cost_kwh"], c["order"]))
    else:  # nothing satisfies the band: minimise how badly it is violated
        best = min(candidates, key=lambda c: (c["violation"], c["cost_kwh"], c["order"]))
    for c in candidates:
        c["chosen"] = c is best
    return Plan(best["first_mode"], best["sequence"], best["temps"],
                candidates, bool(feasible))
