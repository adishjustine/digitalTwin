# DT-BEMS: Digital Twin-Based Building Energy Management System

A simulated three-zone building (office, meeting room, laboratory) controlled
two ways on **identical** weather and occupancy:

1. **Conventional BEMS**: thermostat with hysteresis and occupancy-sensor
   lighting timers. Reacts to current conditions only.
2. **Digital-twin BEMS**: a virtual copy of the building predicts the next
   30 minutes, evaluates 27 candidate HVAC plans per zone, rejects any that
   leave the comfort band, and applies the cheapest feasible plan (a simplified
   model predictive control loop that re-plans every 5 minutes).

All results are **modelled with illustrative parameters**. They are not
measurements of a real building; real savings would need validation against
actual building data.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py          # interactive dashboard
python run_experiments.py     # all scenarios -> data/results.csv
python tests/test_core.py     # tests (or: python -m pytest -q)
```

## Project layout

```text
app.py                     Streamlit dashboard (UI only)
run_experiments.py         Runs every scenario with both controllers
models/
  building.py              Zone config + RC thermal model
  energy.py                Power, energy, cost, CO2
  digital_twin.py          State estimation, prediction, error tracking (MAE)
  optimizer.py             Candidate-plan evaluation (finite-set MPC)
simulation/
  scenarios.py             Five seeded scenarios (fixed weather/occupancy tables)
  controllers.py           Conventional and digital-twin controllers
  simulator.py             Runs a controller; compares two fairly
integration/               MQTT bridge, live session, protocol, fake ESP32
wokwi/                     ESP32 firmware, circuit (diagram.json), setup guide
tests/test_core.py         Empty building, high temp, occupancy, fairness, MAE
tests/test_live.py         Protocol, validation, live loop vs offline simulator
data/results.csv           Output of run_experiments.py
```

## Hardware-in-the-loop with Wokwi

An ESP32 simulated in Wokwi acts as the physical layer (DHT22, occupancy
potentiometers, LEDs). It exchanges MQTT messages with `integration/mqtt_bridge.py`,
which runs the digital twin and optimiser and sends back HVAC/lighting commands.
Setup, pin map and protocol: see [`wokwi/README.md`](wokwi/README.md).

```bash
python -m integration.mqtt_bridge --site-id <your-unique-id>
python -m integration.fake_device --mqtt --scenario "Heatwave"   # same loop without Wokwi
python wokwi/host_test/check_firmware.py                         # firmware logic vs Python
python tests/test_live.py
```

## Model in brief

Indoor temperature per zone, 1-minute steps:

```
T(t+dt) = T + dt/C * [ UA*(T_out - T) + Q_occupants + Q_equipment/lighting - Q_cooling ]
```

`Q_cooling` is heat removed (electrical power x COP), not electrical power.
Energy is `kW x hours`; cost uses a configurable tariff; CO2 uses a configurable
emission factor (0.82 kg/kWh is an approximate grid average, replace it with a
documented figure for your scenario).

## Fairness and honesty notes

- Both controllers replay the same outdoor-temperature, occupancy and
  sensor-noise tables from the same initial state.
- The twin deliberately uses slightly wrong building parameters (UA +10%,
  C -5%) so its prediction error (MAE) is realistic and non-zero.
- "Saved %" can include heat stored in the building at the end of the run, so
  the output also reports a **stored-heat-adjusted** saving.
- Comfort violations (minutes outside 22-26 degC while occupied) are reported
  next to energy; savings alone are not the claim.
- Occupancy prediction is schedule-based, with no confidence score because none
  has been measured. Humidity is not modelled.

## Results

Run `python run_experiments.py` to regenerate `data/results.csv`. Add the
table from that run here before presenting.
