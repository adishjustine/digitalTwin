"""MQTT bridge: runs the digital twin + optimiser on live telemetry.

    python -m integration.mqtt_bridge --site-id adish-dt-7f3a

Subscribes to dtbems/<site>/telemetry, publishes dtbems/<site>/command.
Requires paho-mqtt >= 2.0. The default broker is a public one, so anything
sent is visible to others: use a unique --site-id and only simulated data.
"""
from __future__ import annotations

import argparse
import sys
import time

import paho.mqtt.client as mqtt

from integration.live import LiveSession
from integration.protocol import DEFAULT_SITE_ID, MODES, topics


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-id", default=DEFAULT_SITE_ID)
    ap.add_argument("--broker", default="broker.hivemq.com")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--horizon", type=int, default=30)
    args = ap.parse_args(argv)

    t = topics(args.site_id)
    session = LiveSession(horizon=args.horizon)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"MQTT connect failed: {reason_code}")
            return
        client.subscribe(t["telemetry"])
        print(f"Connected to {args.broker}:{args.port}. Listening on {t['telemetry']}")

    def on_message(client, userdata, msg):
        try:
            cmd = session.handle(msg.payload.decode("utf-8", errors="replace"))
        except ValueError as exc:
            print(f"Ignoring bad telemetry: {exc}")
            return
        client.publish(t["command"], cmd, qos=0)
        last = session.history[-3:]
        hh, mm = divmod(last[0][1], 60)
        summary = "  ".join(f"{r[3].split(' - ')[-1]}: {r[4]:.1f}C occ={r[5]} {r[6]}"
                            f"{'+L' if r[7] else ''}" for r in last)
        print(f"k={last[0][0]:4d} {hh:02d}:{mm:02d}  {summary}  | {session.kwh:.2f} kWh, "
              f"{session.violation_min} min outside comfort")

    stats = {"rx": 0}

    def counting_on_message(client, userdata, msg):
        stats["rx"] += 1
        on_message(client, userdata, msg)

    client.on_connect = on_connect
    client.on_message = counting_on_message
    try:
        client.connect(args.broker, args.port, keepalive=60)
    except OSError as exc:
        print(f"Cannot reach broker {args.broker}:{args.port}: {exc}")
        return 1
    client.loop_start()
    waited = 0
    try:
        while True:
            time.sleep(5)
            waited += 5
            if stats["rx"] == 0 and waited % 15 == 0:
                print(f"[{waited}s] Connected but NO telemetry yet on {t['telemetry']}. "
                      "Is Wokwi playing, and is SITE_ID identical in sketch.ino? "
                      "(python -m integration.check_link helps)")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.loop_stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
