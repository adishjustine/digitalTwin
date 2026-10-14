"""Predefined, seeded scenarios.

A scenario is a fixed table of outdoor temperature, per-zone occupancy and
sensor noise for every simulated minute. Both controllers replay the *same*
table, which is what makes the comparison fair.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from models.building import ZoneConfig, default_zones, scheduled_occupancy


@dataclass
class Scenario:
    name: str
    description: str
    expected: str                 # test objective, NOT a guaranteed result
    start_minute: int             # minute of day at step 0
    steps: int                    # number of 1-minute steps
    t_out: np.ndarray             # (steps,)
    occ: np.ndarray               # (n_zones, steps) int
    noise: np.ndarray             # (n_zones, steps) sensor noise in degC
    init_temps: list


def _outdoor(start_min: int, steps: int, base: float, amp: float,
             rng: np.random.Generator, peak_hour: float = 15.0) -> np.ndarray:
    minutes = (start_min + np.arange(steps)) % 1440
    curve = base + amp * np.cos(2 * np.pi * (minutes / 60.0 - peak_hour) / 24.0)
    return curve + rng.normal(0.0, 0.1, steps)


def _occupancy(zones: list[ZoneConfig], start_min: int, steps: int,
               rng: np.random.Generator) -> np.ndarray:
    """Scheduled occupancy plus a slowly varying +/-1 person fluctuation."""
    occ = np.zeros((len(zones), steps), dtype=int)
    for zi, z in enumerate(zones):
        wobble = 0
        for k in range(steps):
            minute = (start_min + k) % 1440
            if k % 10 == 0:
                wobble = int(rng.integers(-1, 2))
            sched = scheduled_occupancy(z, minute)
            occ[zi, k] = max(0, sched + wobble) if sched > 0 else 0
    return occ


def _edit(occ, zone_idx, start_min, end_min, scenario_start, mode, value):
    """Apply an occupancy edit over an absolute time window (minutes of day)."""
    a = max(0, start_min - scenario_start)
    b = max(0, end_min - scenario_start)
    seg = occ[zone_idx, a:b]
    if mode == "set":
        seg[:] = value
    elif mode == "add":
        seg[:] = np.maximum(0, seg + value)


def _build(name, description, expected, start_hour, hours, base, amp,
           init_temp, seed, edits=()):
    rng = np.random.default_rng(seed)
    zones = default_zones()
    start_min = int(start_hour * 60)
    steps = int(hours * 60)
    t_out = _outdoor(start_min, steps, base, amp, rng)
    occ = _occupancy(zones, start_min, steps, rng)
    for zi, s, e, mode, val in edits:
        _edit(occ, zi, int(s * 60), int(e * 60), start_min, mode, val)
    noise = rng.normal(0.0, 0.2, (len(zones), steps))
    return Scenario(name, description, expected, start_min, steps, t_out, occ,
                    noise, [init_temp] * len(zones))


def normal_day(seed: int = 1) -> Scenario:
    return _build(
        "Normal day", "Moderate weather, scheduled occupancy.",
        "Both controllers keep comfort; compare energy.",
        8, 10, 28.0, 3.0, 24.0, seed)


def heatwave(seed: int = 2) -> Scenario:
    return _build(
        "Heatwave", "High outdoor temperature, normal occupancy.",
        "Twin anticipates rising indoor temperature and pre-cools.",
        8, 10, 36.0, 4.0, 25.0, seed)


def empty_meeting_room(seed: int = 3) -> Scenario:
    return _build(
        "Empty meeting room",
        "Both scheduled meetings are cancelled (room stays empty).",
        "Unnecessary lighting and HVAC in the meeting room are reduced.",
        8, 10, 28.0, 3.0, 24.0, seed,
        edits=[(1, 10, 11, "set", 0), (1, 14, 15.5, "set", 0)])


def sudden_occupancy(seed: int = 4) -> Scenario:
    return _build(
        "Sudden occupancy increase",
        "Unscheduled crowd arrives in the office (11:00-12:30) and lab (14:00-15:30).",
        "Controller responds to additional heat and occupancy.",
        8, 10, 30.0, 3.0, 24.0, seed,
        edits=[(0, 11, 12.5, "add", 12), (2, 14, 15.5, "add", 8)])


def evening_shutdown(seed: int = 5) -> Scenario:
    return _build(
        "Evening shutdown",
        "People leave earlier than scheduled from 16:45.",
        "Zones move to lower-energy modes after occupancy drops.",
        16, 6, 29.0, 3.0, 24.5, seed,
        edits=[(0, 16.75, 17.25, "set", 4), (0, 17.25, 22, "set", 0),
               (2, 16.5, 22, "set", 0)])


SCENARIOS = {
    "Normal day": normal_day,
    "Heatwave": heatwave,
    "Empty meeting room": empty_meeting_room,
    "Sudden occupancy increase": sudden_occupancy,
    "Evening shutdown": evening_shutdown,
}


def get_scenario(name: str) -> Scenario:
    return SCENARIOS[name]()
