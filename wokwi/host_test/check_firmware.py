"""Compiles wokwi/sketch.ino on this PC (with stub Arduino headers) and checks
that its thermal model and command parser agree with the Python code.

    python wokwi/host_test/check_firmware.py

This does NOT replace testing in Wokwi (WiFi/MQTT/DHT behaviour is stubbed),
but it catches syntax errors and any drift between firmware and model.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from integration.protocol import encode_command  # noqa: E402
from models.building import default_zones, step_temp  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "fw_test"
        cmd = ["g++", "-std=c++17", "-Wall", "-Wextra", "-x", "c++",
               f"-I{HERE / 'stubs'}", "-o", str(exe), str(HERE / "test_main.cpp")]
        build = subprocess.run(cmd, capture_output=True, text=True)
        if build.returncode != 0:
            print(build.stderr)
            print("FAIL: sketch.ino does not compile")
            return 1
        if build.stderr.strip():
            print("compiler warnings:\n" + build.stderr)
        out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout

    lines = out.strip().splitlines()
    parse = [l for l in lines if l.startswith("PARSE")]
    temps = [l for l in lines if l.startswith("TEMP")]

    # Parser: first two valid, the rest rejected; and the Python encoder's exact output parses.
    expected_ok = [True, True, False, False, False, False]
    assert [p.split()[1] == "1" for p in parse] == expected_ok, parse
    assert parse[0].split()[2:] == ["k=12", "m=102", "l=101"], parse[0]
    assert encode_command(12, [("LOW", True), ("OFF", False), ("HIGH", True)]) == \
        '{"k":12,"z":[[1,1],[0,0],[2,1]]}'

    # Physics: replay the same inputs through Python's step_temp.
    zones = default_zones()
    T = [24.0] * 3
    py = {}
    for i in range(300):
        t_out = 28.0 + 0.01 * i
        for z in range(3):
            people = (i // 20 + z * 3) % 12
            mode = ("OFF", "LOW", "HIGH")[(i // 40 + z) % 3]
            T[z] = step_temp(T[z], t_out, people, mode, people > 0, zones[z])
        if i % 50 == 49:
            py[i] = list(T)
    worst = 0.0
    for line in temps:
        _, i, *vals = line.split()
        for fw, ref in zip(map(float, vals), py[int(i)]):
            worst = max(worst, abs(fw - ref))
    assert worst < 5e-3, f"firmware physics differs from Python by {worst:.5f} degC"
    print(f"OK: sketch.ino compiles; parser behaves; physics matches Python "
          f"(max difference {worst:.5f} degC over 300 steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
