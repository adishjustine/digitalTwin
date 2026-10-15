"""Generates wokwi/diagram.json (the circuit) so every pin is consistent with
sketch.ino. Run:  python wokwi/make_diagram.py

Pin map (must match ZONES[] in sketch.ino):
    DHT22 data        GPIO15          (outdoor temperature / humidity)
    Potentiometers    GPIO34, 35, 32  (occupancy of zones A, B, C)
    Lighting LEDs     GPIO13, 27, 23
    HVAC LOW LEDs     GPIO12, 26, 22  (on for LOW and HIGH)
    HVAC HIGH LEDs    GPIO14, 25, 21  (on for HIGH only)
"""
import json
from pathlib import Path

ZONES = [
    {"id": "A", "name": "Office",  "pot": 34, "light": 13, "low": 12, "high": 14},
    {"id": "B", "name": "Meeting", "pot": 35, "light": 27, "low": 26, "high": 25},
    {"id": "C", "name": "Lab",     "pot": 32, "light": 23, "low": 22, "high": 21},
]

parts = [
    {"type": "board-esp32-devkit-c-v4", "id": "esp", "top": 0, "left": 0, "attrs": {}},
    {"type": "wokwi-dht22", "id": "dht1", "top": -135, "left": 120,
     "attrs": {"temperature": "32", "humidity": "55"}},
]
wires = [
    ["esp:TX", "$serialMonitor:RX", "", []],
    ["esp:RX", "$serialMonitor:TX", "", []],
    ["dht1:VCC", "esp:3V3", "red", []],
    ["dht1:SDA", "esp:15", "green", []],
    ["dht1:GND", "esp:GND.2", "black", []],
]

LED_COLORS = {"light": "yellow", "low": "cyan", "high": "blue"}
for zi, z in enumerate(ZONES):
    x0 = 330 + zi * 170
    parts.append({"type": "wokwi-potentiometer", "id": f"pot{z['id']}",
                  "top": 230, "left": x0 - 40, "attrs": {}})
    wires += [
        [f"pot{z['id']}:SIG", f"esp:{z['pot']}", "orange", []],
        [f"pot{z['id']}:VCC", "esp:3V3", "red", []],
        [f"pot{z['id']}:GND", "esp:GND.1", "black", []],
    ]
    for li, kind in enumerate(["light", "low", "high"]):
        lid, rid = f"led{z['id']}_{kind}", f"r{z['id']}_{kind}"
        y = -40 + li * 70
        parts.append({"type": "wokwi-led", "id": lid, "top": y, "left": x0 + 40,
                      "attrs": {"color": LED_COLORS[kind], "label": f"{z['name']} {kind}"}})
        parts.append({"type": "wokwi-resistor", "id": rid, "top": y + 35, "left": x0 - 10,
                      "attrs": {"value": "220"}})
        wires += [
            [f"esp:{z[kind]}", f"{rid}:1", "green", []],
            [f"{rid}:2", f"{lid}:A", "green", []],
            [f"{lid}:C", "esp:GND.3", "black", []],
        ]

diagram = {"version": 1, "author": "DT-BEMS", "editor": "wokwi",
           "parts": parts, "connections": wires, "dependencies": {}}

# Sanity checks: unique ids and every connection endpoint refers to a real part.
ids = {p["id"] for p in parts} | {"$serialMonitor"}
assert len(ids) == len(parts) + 1, "duplicate part ids"
for a, b, *_ in wires:
    for end in (a, b):
        assert end.split(":")[0] in ids, f"unknown part in connection: {end}"

out = Path(__file__).with_name("diagram.json")
out.write_text(json.dumps(diagram, indent=2) + "\n")
print(f"Wrote {out} ({len(parts)} parts, {len(wires)} connections)")
