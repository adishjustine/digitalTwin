"""Electrical power, energy, cost and CO2 calculations."""
from __future__ import annotations

from models.building import ZoneConfig

DEFAULT_TARIFF = 8.0      # INR per kWh (configurable)
CO2_FACTOR = 0.82         # kg CO2 per kWh (approximate grid average; document your source)


def zone_power_w(cfg: ZoneConfig, mode: str, light_on: bool) -> dict:
    hvac = cfg.hvac_elec_w[mode]
    light = cfg.light_w if light_on else 0.0
    equip = cfg.equip_w
    return {"hvac": hvac, "light": light, "equip": equip,
            "total": hvac + light + equip}


def energy_kwh(power_w: float, dt_min: float = 1.0) -> float:
    """E[kWh] = P[kW] * dt[h]."""
    return power_w / 1000.0 * dt_min / 60.0


def cost(kwh: float, tariff: float = DEFAULT_TARIFF) -> float:
    return kwh * tariff


def co2_kg(kwh: float, factor: float = CO2_FACTOR) -> float:
    return kwh * factor
