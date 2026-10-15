"""Python stand-in for the Wokwi ESP32 firmware.

Same plant physics and same wire protocol as wokwi/sketch.ino, driven by one
of the predefined scenarios instead of pots and a DHT22. Uses:

  * automated tests of the whole telemetry -> twin -> command loop
  * a fallback demo if Wokwi networking misbehaves

In-memory:   from integration.fake_device import run_in_memory
Over MQTT:   python -m integration.fake_device --mqtt --scenario "Heatwave"
             (run `python -m integration.mqtt_bridge` in another terminal)
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import time

from integration.protocol import DEFAULT_SITE_ID, decode_command, topics
from models.building import Building, default_zones
from models.energy import zone_power_w
from simulation.scenarios import SCENARIOS, Scenario


class FakeDevice:
    def __init__(self, scenario: Scenario, hum: float = 55.0):
        self.s = scenario
        self.zones = default_zones()
        self.building = Building(self.zones, scenario.init_temps)
        self.actions = [("OFF", False)] * len(self.zones)
        self.hum = hum
        self.kwh = 0.0
        self.violation_min = 0
        self.temps_log: list[list[float]] = []

    def telemetry(self, k: int) -> str:
        """Telemetry exactly as the firmware formats it (rounded values)."""
        s = self.s
        z = [{"T": round(self.building.T[i] + float(s.noise[i][k]), 2),
              "occ": int(s.occ[i][k])} for i in range(len(self.zones))]
        return json.dumps({"k": k, "minute": (s.start_minute + k) % 1440,
                           "t_out": round(float(s.t_out[k]), 2),
                           "hum": round(self.hum, 1), "z": z}, separators=(",", ":"))

    def apply_and_step(self, k: int, command_payload: str | None) -> None:
        if command_payload is not None:
            ck, self.actions = decode_command(command_payload)
            assert ck == k, f"command k={ck} does not match telemetry k={k}"
        s = self.s
        occ = [int(s.occ[i][k]) for i in range(len(self.zones))]
        for i, cfg in enumerate(self.zones):
            T = self.building.T[i]
            mode, light = self.actions[i]
            self.kwh += zone_power_w(cfg, mode, light)["total"] / 1000.0 / 60.0
            if occ[i] > 0 and not (cfg.comfort_min <= T <= cfg.comfort_max):
                self.violation_min += 1
        self.temps_log.append(list(self.building.T))
        self.building.step(self.actions, float(s.t_out[k]), occ)


def run_in_memory(session, scenario: Scenario, steps: int | None = None) -> FakeDevice:
    """Closed loop with no network: device <-JSON-> LiveSession."""
    dev = FakeDevice(scenario)
    for k in range(steps or scenario.steps):
        cmd = session.handle(dev.telemetry(k))      # goes through the real JSON path
        dev.apply_and_step(k, cmd)
    return dev


def run_over_mqtt(args) -> int:
    import paho.mqtt.client as mqtt

    scenario = SCENARIOS[args.scenario]()
    t = topics(args.site_id)
    inbox: queue.Queue = queue.Queue()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = lambda c, u, f, rc, p: c.subscribe(t["command"])
    client.on_message = lambda c, u, m: inbox.put(m.payload.decode())
    client.connect(args.broker, args.port, 60)
    client.loop_start()

    dev = FakeDevice(scenario)
    steps = args.steps or scenario.steps
    print(f"Fake device: scenario '{scenario.name}', {steps} steps, site {args.site_id}")
    for k in range(steps):
        client.publish(t["telemetry"], dev.telemetry(k), qos=0)
        cmd = None
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            try:
                payload = inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            if json.loads(payload)["k"] == k:
                cmd = payload
                break
        if cmd is None:
            print(f"k={k}: no command within {args.timeout}s (is the bridge running?)")
        dev.apply_and_step(k, cmd)
        time.sleep(args.delay)
    client.loop_stop()
    print(f"Done. {dev.kwh:.2f} kWh, {dev.violation_min} min outside comfort.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mqtt", action="store_true", help="talk to a real broker")
    ap.add_argument("--scenario", default="Normal day", choices=list(SCENARIOS))
    ap.add_argument("--site-id", default=DEFAULT_SITE_ID)
    ap.add_argument("--broker", default="broker.hivemq.com")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--steps", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.2, help="seconds between ticks")
    ap.add_argument("--timeout", type=float, default=4.0)
    args = ap.parse_args(argv)
    if not args.mqtt:
        from integration.live import LiveSession
        dev = run_in_memory(LiveSession(write_files=False), SCENARIOS[args.scenario](),
                            args.steps or None)
        print(f"In-memory run: {dev.kwh:.2f} kWh, {dev.violation_min} min outside comfort.")
        return 0
    return run_over_mqtt(args)


if __name__ == "__main__":
    sys.exit(main())
