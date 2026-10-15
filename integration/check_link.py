"""Connectivity check: is Wokwi (or the fake device) reaching this PC?

    python -m integration.check_link --site-id adish-dt-4821

Listens for 20 seconds on the telemetry and command topics of your site id and
tells you what it found. Run it BEFORE the bridge, while Wokwi is playing.
"""
from __future__ import annotations

import argparse
import sys
import time

import paho.mqtt.client as mqtt

from integration.protocol import DEFAULT_SITE_ID, topics


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-id", default=DEFAULT_SITE_ID)
    ap.add_argument("--broker", default="broker.hivemq.com")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--seconds", type=int, default=20)
    args = ap.parse_args(argv)
    t = topics(args.site_id)
    counts = {"telemetry": 0, "command": 0}
    sample = {}
    other = set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(c, u, f, rc, p):
        if rc.is_failure:
            print(f"Broker refused the connection: {rc}")
            return
        c.subscribe([(t["telemetry"], 0), (t["command"], 0), ("dtbems/+/telemetry", 0)])

    def on_message(c, u, m):
        for name, topic in t.items():
            if m.topic == topic:
                counts[name] += 1
                sample.setdefault(name, m.payload.decode(errors="replace")[:160])
                return
        other.add(m.topic)

    client.on_connect, client.on_message = on_connect, on_message
    try:
        client.connect(args.broker, args.port, 30)
    except OSError as exc:
        print(f"FAIL: cannot reach broker {args.broker}:{args.port} from this PC: {exc}")
        print("Check your internet/firewall, or try --broker test.mosquitto.org "
              "(and set MQTT_HOST to the same host in sketch.ino).")
        return 1
    client.loop_start()
    print(f"Connected to {args.broker}. Listening {args.seconds}s for site '{args.site_id}' ...")
    time.sleep(args.seconds)
    client.loop_stop()

    print(f"\nTelemetry messages on {t['telemetry']}: {counts['telemetry']}")
    print(f"Command messages   on {t['command']}: {counts['command']}")
    if sample.get("telemetry"):
        print("Sample telemetry:", sample["telemetry"])
    if counts["telemetry"]:
        print("\nOK: Wokwi is reaching the broker and this PC can see it. "
              "Now start the bridge: python -m integration.mqtt_bridge --site-id " + args.site_id)
        return 0
    others = sorted(other - {t["telemetry"]})
    print("\nNO telemetry received.")
    if others:
        print("But telemetry from OTHER site ids was seen, so Wokwi is running with a different "
              "SITE_ID than you typed here:\n  " + "\n  ".join(others[:5]))
    else:
        print("Likely causes, in order:\n"
              "  1. The Wokwi simulation is not running (press Play), or it is stuck on 'WiFi/MQTT connecting'.\n"
              "  2. SITE_ID in sketch.ino differs from --site-id (they must match exactly).\n"
              "  3. The public broker is busy: try --broker test.mosquitto.org and the same host in sketch.ino.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
