"""Tests for the hardware-in-the-loop path (no network needed).

Run with:  python tests/test_live.py   (or: python -m pytest -q)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integration.fake_device import FakeDevice, run_in_memory
from integration.live import LiveSession
from integration.protocol import decode_command, decode_telemetry, encode_command
from simulation.controllers import DTController
from simulation.scenarios import SCENARIOS, heatwave, normal_day
from simulation.simulator import run


def _good(k=0, **over):
    msg = {"k": k, "minute": 480, "t_out": 30.0, "hum": 55.0,
           "z": [{"T": 24.0, "occ": 5}, {"T": 24.0, "occ": 0}, {"T": 25.0, "occ": 2}]}
    msg.update(over)
    return json.dumps(msg)


def test_command_roundtrip_and_exact_wire_format():
    actions = [("LOW", True), ("OFF", False), ("HIGH", True)]
    payload = encode_command(12, actions)
    assert payload == '{"k":12,"z":[[1,1],[0,0],[2,1]]}'   # firmware sscanf depends on this
    k, back = decode_command(payload)
    assert k == 12 and back == actions


def test_telemetry_validation_rejects_bad_readings():
    assert decode_telemetry(_good())["T"] == [24.0, 24.0, 25.0]
    bad = [
        "not json", "[]", json.dumps({"k": 0}),
        _good(t_out=99.0),
        _good(z=[{"T": 24, "occ": 1}]),
        _good(z=[{"T": 200.0, "occ": 1}] * 3),
        _good(z=[{"T": 24.0, "occ": -3}] * 3),
        _good(k=-1),
    ]
    for payload in bad:
        try:
            decode_telemetry(payload)
        except ValueError:
            continue
        raise AssertionError(f"accepted bad telemetry: {payload}")


def test_live_loop_matches_offline_simulator():
    """Going through JSON + the live session must not change behaviour."""
    for build in (normal_day, heatwave):
        offline = run(build(), DTController())
        dev = run_in_memory(LiveSession(write_files=False), build())
        assert abs(dev.kwh - offline.summary["total_kwh"]) < 0.05
        assert dev.violation_min == offline.summary["violation_min"]


def test_command_echoes_k_and_covers_all_zones():
    s = LiveSession(write_files=False)
    k, actions = decode_command(s.handle(_good(k=0)))
    assert k == 0 and len(actions) == 3


def test_device_restart_starts_a_fresh_run():
    s = LiveSession(write_files=False)
    for k in range(10):
        s.handle(_good(k=k))
    assert s.resets == 0 and s.last_k == 9
    s.handle(_good(k=0))                    # device rebooted
    assert s.resets == 1 and s.last_k == 0 and s.ticks == 1


def test_dashboard_files_written(tmp_path=None):
    import tempfile
    d = Path(tmp_path or tempfile.mkdtemp())
    s = LiveSession(state_path=d / "state.json", log_path=d / "log.csv")
    for k in range(6):
        s.handle(_good(k=k))
    state = json.loads((d / "state.json").read_text())
    assert state["k"] == 5 and len(state["zones"]) == 3
    assert state["zones"][0]["n_candidates"] == 27
    assert sum(c["chosen"] for c in state["zones"][0]["candidates"]) == 1
    assert len((d / "log.csv").read_text().strip().splitlines()) == 1 + 6 * 3


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"{len(tests)} tests passed")
