"""Wire protocol between the ESP32 (Wokwi) and the Python application.

Transport: MQTT. Topics (SITE_ID must match the firmware and the bridge):

    dtbems/<SITE_ID>/telemetry   ESP32  -> Python   one message per simulated minute
    dtbems/<SITE_ID>/command     Python -> ESP32    reply to that minute's telemetry

Telemetry (JSON):
    {"k":12,"minute":492,"t_out":31.2,"hum":55.0,
     "z":[{"T":24.31,"occ":8},{"T":23.9,"occ":0},{"T":25.0,"occ":3}]}

Command (compact JSON; the firmware parses it with sscanf, so keep this exact
shape): {"k":12,"z":[[1,1],[0,0],[2,1]]}  where each pair is [hvac_mode, light]
and hvac_mode is 0=OFF, 1=LOW, 2=HIGH. The command's k echoes the telemetry's k.

The firmware waits for the command with the matching k before advancing its
physics, so the real-time loop behaves like the offline simulator.
"""
from __future__ import annotations

import json

MODES = ("OFF", "LOW", "HIGH")
N_ZONES = 3
DEFAULT_SITE_ID = "adish-dt-7f3a"   # change in BOTH the firmware and the bridge


def topics(site_id: str) -> dict:
    base = f"dtbems/{site_id}"
    return {"telemetry": f"{base}/telemetry", "command": f"{base}/command"}


def encode_command(k: int, actions) -> str:
    """actions: list of (mode_name, light_on) per zone."""
    z = [[MODES.index(mode), 1 if light else 0] for mode, light in actions]
    return json.dumps({"k": int(k), "z": z}, separators=(",", ":"))


def decode_command(payload: str):
    msg = json.loads(payload)
    return msg["k"], [(MODES[m], bool(l)) for m, l in msg["z"]]


def decode_telemetry(payload) -> dict:
    """Parse and validate a telemetry message. Raises ValueError if unusable."""
    try:
        msg = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ValueError("telemetry must be a JSON object")
    try:
        k = int(msg["k"])
        minute = int(msg["minute"])
        t_out = float(msg["t_out"])
        hum = float(msg.get("hum", float("nan")))
        zones = msg["z"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"missing or malformed field: {exc}") from exc
    if k < 0 or not (0 <= minute < 1440 * 7):
        raise ValueError(f"k/minute out of range: k={k} minute={minute}")
    if not -30.0 <= t_out <= 60.0:
        raise ValueError(f"outdoor temperature out of range: {t_out}")
    if not isinstance(zones, list) or len(zones) != N_ZONES:
        raise ValueError(f"expected {N_ZONES} zones")
    temps, occ = [], []
    for i, z in enumerate(zones):
        try:
            t, o = float(z["T"]), int(z["occ"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"zone {i} malformed: {exc}") from exc
        if not -10.0 <= t <= 60.0:
            raise ValueError(f"zone {i} temperature out of range: {t}")
        if not 0 <= o <= 200:
            raise ValueError(f"zone {i} occupancy out of range: {o}")
        temps.append(t)
        occ.append(o)
    return {"k": k, "minute": minute % 1440, "t_out": t_out, "hum": hum,
            "T": temps, "occ": occ}
