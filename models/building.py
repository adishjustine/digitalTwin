"""Zone configuration and the simplified RC thermal model.

All parameter values are illustrative simulation assumptions, not
specifications of a real building.

Units: C in J/degC, UA in W/degC, heat flows in W, time in seconds.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HVAC_MODES = ("OFF", "LOW", "HIGH")


def _default_hvac_power() -> dict:
    # Electrical input power per mode (W).
    return {"OFF": 0.0, "LOW": 1500.0, "HIGH": 3000.0}


@dataclass(frozen=True)
class ZoneConfig:
    name: str
    purpose: str
    C: float                      # effective thermal capacity (J/degC)
    UA: float                     # envelope heat-transfer coefficient (W/degC)
    equip_w: float                # equipment load, electrical = heat (W)
    light_w: float = 400.0        # lighting power when ON (electrical = heat)
    hvac_elec_w: dict = field(default_factory=_default_hvac_power)
    cop: float = 2.0              # cooling delivered per electrical watt
    occ_heat_w: float = 100.0     # heat per occupant (W)
    comfort_min: float = 22.0
    comfort_max: float = 26.0
    relaxed_min: float = 20.0     # allowed band while the zone is empty
    relaxed_max: float = 29.0
    # Expected occupancy: tuple of (start_hour, end_hour, people)
    schedule: tuple = ()


def default_zones() -> list[ZoneConfig]:
    """Three independent zones: office, meeting room, laboratory."""
    return [
        ZoneConfig(
            "Zone A - Office", "Office", C=3.0e6, UA=150.0, equip_w=300.0,
            schedule=((8, 12, 10), (12, 13, 3), (13, 17, 10)),
        ),
        ZoneConfig(
            "Zone B - Meeting room", "Meeting room", C=1.8e6, UA=100.0,
            equip_w=150.0,
            hvac_elec_w={"OFF": 0.0, "LOW": 1000.0, "HIGH": 2000.0},
            schedule=((10, 11, 6), (14, 15.5, 8)),
        ),
        ZoneConfig(
            "Zone C - Laboratory", "Laboratory", C=4.0e6, UA=180.0,
            equip_w=800.0,
            schedule=((9, 12, 4), (12, 13, 2), (13, 17, 4)),
        ),
    ]


def scheduled_occupancy(cfg: ZoneConfig, minute_of_day: float) -> int:
    """Expected number of people in the zone at this time of day."""
    hour = (minute_of_day % 1440) / 60.0
    for start, end, people in cfg.schedule:
        if start <= hour < end:
            return people
    return 0


def cooling_w(cfg: ZoneConfig, mode: str) -> float:
    """Heat removed from the room (W). NOT the electrical power."""
    return cfg.hvac_elec_w[mode] * cfg.cop


def step_temp(T: float, t_out: float, occ: float, mode: str,
              light_on: bool, cfg: ZoneConfig, dt_s: float = 60.0) -> float:
    """One explicit step of the RC thermal model."""
    q_env = cfg.UA * (t_out - T)
    q_occ = occ * cfg.occ_heat_w
    q_equip = cfg.equip_w + (cfg.light_w if light_on else 0.0)
    q_hvac = cooling_w(cfg, mode)
    return T + dt_s / cfg.C * (q_env + q_occ + q_equip - q_hvac)


class Building:
    """The 'physical' building the controllers act on."""

    def __init__(self, zones: list[ZoneConfig], init_temps: list[float]):
        self.zones = list(zones)
        self.T = [float(t) for t in init_temps]

    def step(self, actions, t_out: float, occ, dt_s: float = 60.0) -> None:
        """actions: list of (hvac_mode, light_on), one per zone."""
        self.T = [
            step_temp(self.T[i], t_out, occ[i], actions[i][0], actions[i][1],
                      self.zones[i], dt_s)
            for i in range(len(self.zones))
        ]
