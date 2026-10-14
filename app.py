"""
Digital Twin — Smart Building Energy Efficiency Demo
------------------------------------------------------
Run with:
    pip install -r requirements.txt
    streamlit run app.py

Shows a live-updating Digital Twin of a 3-zone building that predicts
temperature/occupancy trends and compares energy use under a
conventional reactive BEMS vs a predictive Digital-Twin BEMS (DT-BEMS).
"""

import time
import random
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------
# Config / constants
# --------------------------------------------------------------------
ZONES = ["Zone A - Lobby", "Zone B - Offices", "Zone C - Server Room"]
SETPOINTS = {ZONES[0]: 24.0, ZONES[1]: 23.0, ZONES[2]: 20.0}
HVAC_MAX_KW = {ZONES[0]: 2.5, ZONES[1]: 3.0, ZONES[2]: 4.0}
LIGHT_KW = {ZONES[0]: 0.4, ZONES[1]: 0.6, ZONES[2]: 0.1}
CO2_FACTOR = 0.82        # kg CO2 per kWh (India grid avg, approx)
STEP_MINUTES = 5         # each simulated "tick" = 5 minutes

st.set_page_config(page_title="Digital Twin — Smart Building", layout="wide")

# --------------------------------------------------------------------
# Session state init
# --------------------------------------------------------------------
def init_state():
    if "history" not in st.session_state:
        st.session_state.history = []
    if "t" not in st.session_state:
        st.session_state.t = 0
    if "zone_temp" not in st.session_state:
        st.session_state.zone_temp = {z: SETPOINTS[z] + random.uniform(-1, 2) for z in ZONES}
    if "zone_occ" not in st.session_state:
        st.session_state.zone_occ = {z: random.randint(0, 15) for z in ZONES}
    if "humidity" not in st.session_state:
        st.session_state.humidity = 55.0
    if "prev_temp" not in st.session_state:
        st.session_state.prev_temp = dict(st.session_state.zone_temp)
    if "kwh_normal" not in st.session_state:
        st.session_state.kwh_normal = 0.0
    if "kwh_dt" not in st.session_state:
        st.session_state.kwh_dt = 0.0
    if "running" not in st.session_state:
        st.session_state.running = False

init_state()

# --------------------------------------------------------------------
# Sidebar controls
# --------------------------------------------------------------------
st.sidebar.title("⚙️ Controls")
outside_temp = st.sidebar.slider("Outside temperature (°C)", 15.0, 42.0, 30.0, 0.5)
price = st.sidebar.number_input("Electricity price (₹/kWh)", 1.0, 20.0, 8.0, 0.5)
occ_boost = st.sidebar.slider("Occupancy trend bias (people)", -10, 10, 0)
speed = st.sidebar.slider("Sim speed (sec/tick)", 0.2, 3.0, 1.0, 0.1)

col_run1, col_run2 = st.sidebar.columns(2)
if col_run1.button("▶ Run"):
    st.session_state.running = True
if col_run2.button("⏸ Pause"):
    st.session_state.running = False
if st.sidebar.button("🔄 Reset simulation"):
    for k in ["history", "t", "zone_temp", "zone_occ", "humidity",
              "prev_temp", "kwh_normal", "kwh_dt", "running"]:
        del st.session_state[k]
    init_state()
    st.rerun()

active_mode = st.sidebar.radio("Active BEMS (controls the building)",
                                ["Normal BEMS", "DT-BEMS"], index=1)

st.sidebar.caption(f"Simulated step = {STEP_MINUTES} min | t = {st.session_state.t} steps")

# --------------------------------------------------------------------
# One simulation tick
# --------------------------------------------------------------------
def step():
    s = st.session_state
    s.prev_temp = dict(s.zone_temp)

    # humidity random walk
    s.humidity = float(np.clip(s.humidity + random.uniform(-2, 2), 30, 85))

    zone_rows = []
    total_normal_kw = 0.0
    total_dt_kw = 0.0

    for z in ZONES:
        # occupancy random walk, biased by sidebar control
        occ = s.zone_occ[z] + random.randint(-2, 2) + (1 if occ_boost > 0 and random.random() < 0.3 else 0) \
              - (1 if occ_boost < 0 and random.random() < 0.3 else 0)
        occ = int(np.clip(occ, 0, 30))
        s.zone_occ[z] = occ

        # temperature drifts toward outside temp + occupant heat gain
        temp = s.zone_temp[z] + 0.15 * (outside_temp - s.zone_temp[z]) + occ * 0.02 + random.uniform(-0.2, 0.2)
        setpoint = SETPOINTS[z]
        max_kw = HVAC_MAX_KW[z]

        # --- Digital twin prediction (simple trend extrapolation) ---
        trend = temp - s.prev_temp[z]
        predicted_temp = temp + trend * 3  # look 3 steps ahead

        # --- Normal BEMS: reactive bang-bang on current temp only ---
        diff_now = temp - setpoint
        if diff_now > 1.5:
            hvac_normal = max_kw
        elif diff_now > 0.5:
            hvac_normal = max_kw * 0.5
        else:
            hvac_normal = max_kw * 0.15
        light_normal = LIGHT_KW[z] if occ > 0 else 0.0

        # --- DT-BEMS: predictive + occupancy aware ---
        diff_pred = predicted_temp - setpoint
        if occ == 0:
            hvac_dt = max_kw * 0.05          # setback when empty
        elif diff_pred > 1.5:
            hvac_dt = max_kw * 0.55          # gentle pre-cool, avoids overshoot spike
        elif diff_pred > 0.5:
            hvac_dt = max_kw * 0.30
        else:
            hvac_dt = max_kw * 0.10
        light_dt = LIGHT_KW[z] * min(1.0, occ / 10) if occ > 0 else 0.0

        # apply HVAC correction to the *actual* temp if this zone's mode is active
        correction_kw = hvac_normal if active_mode == "Normal BEMS" else hvac_dt
        temp -= (correction_kw / max_kw) * 0.6  # cooling effect proportional to power applied
        s.zone_temp[z] = float(temp)

        total_normal_kw += hvac_normal + light_normal
        total_dt_kw += hvac_dt + light_dt

        zone_rows.append({
            "zone": z, "temp": round(temp, 2), "occupancy": occ,
            "predicted_temp": round(predicted_temp, 2),
            "hvac_normal": round(hvac_normal, 2), "hvac_dt": round(hvac_dt, 2),
        })

    hours = STEP_MINUTES / 60
    s.kwh_normal += total_normal_kw * hours
    s.kwh_dt += total_dt_kw * hours

    s.history.append({
        "t": s.t, "normal_kw": total_normal_kw, "dt_kw": total_dt_kw,
        "humidity": s.humidity, "outside_temp": outside_temp,
        "zones": zone_rows,
    })
    s.history = s.history[-200:]  # cap history
    s.t += 1

# manual single step always available
manual_step = st.sidebar.button("⏭ Step once")
if manual_step:
    step()

# --------------------------------------------------------------------
# Header
# --------------------------------------------------------------------
st.title("🏢 Digital Twin — Smart Building Energy Dashboard")
st.caption("Digital Twin predicts zone conditions and drives a predictive BEMS (DT-BEMS), "
           "compared live against a conventional reactive BEMS.")

if not st.session_state.history:
    step()

latest = st.session_state.history[-1]
zdf = pd.DataFrame(latest["zones"])

normal_now = latest["normal_kw"]
dt_now = latest["dt_kw"]
saved_now = normal_now - dt_now
reduction_pct = (saved_now / normal_now * 100) if normal_now > 0 else 0

# --------------------------------------------------------------------
# Top metrics
# --------------------------------------------------------------------
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Normal BEMS", f"{normal_now:.2f} kW")
m2.metric("DT-BEMS", f"{dt_now:.2f} kW", delta=f"-{reduction_pct:.1f}%")
m3.metric("Energy saved (now)", f"{saved_now:.2f} kW")
m4.metric("Cumulative cost saved", f"₹{(st.session_state.kwh_normal - st.session_state.kwh_dt) * price:,.1f}")
co2_saved = (st.session_state.kwh_normal - st.session_state.kwh_dt) * CO2_FACTOR
m5.metric("CO₂ avoided", f"{co2_saved:.2f} kg")

st.divider()

# --------------------------------------------------------------------
# Zone table + gauges
# --------------------------------------------------------------------
left, right = st.columns([1.3, 1])

with left:
    st.subheader("📊 Live energy comparison")
    hist_df = pd.DataFrame(st.session_state.history)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist_df["t"], y=hist_df["normal_kw"], name="Normal BEMS",
                              mode="lines", line=dict(color="#d9534f", width=2)))
    fig.add_trace(go.Scatter(x=hist_df["t"], y=hist_df["dt_kw"], name="DT-BEMS",
                              mode="lines", line=dict(color="#5cb85c", width=2)))
    fig.update_layout(xaxis_title="time step", yaxis_title="Power (kW)",
                       height=380, margin=dict(l=10, r=10, t=10, b=10),
                       legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("🧠 Digital Twin — zone state")
    st.dataframe(
        zdf.rename(columns={
            "zone": "Zone", "temp": "Temp °C", "occupancy": "Occupancy",
            "predicted_temp": "Predicted °C", "hvac_normal": "HVAC Normal (kW)",
            "hvac_dt": "HVAC DT (kW)"
        }),
        hide_index=True, use_container_width=True
    )
    st.metric("Outside temperature", f"{outside_temp:.1f} °C")
    st.metric("Building humidity", f"{latest['humidity']:.1f} %")
    st.metric("Active controller", active_mode)

st.divider()
st.subheader("💡 Cumulative energy & cost")
c1, c2, c3 = st.columns(3)
c1.metric("Total kWh — Normal BEMS", f"{st.session_state.kwh_normal:.2f} kWh")
c2.metric("Total kWh — DT-BEMS", f"{st.session_state.kwh_dt:.2f} kWh")
c3.metric("Overall reduction", f"{(1 - st.session_state.kwh_dt / st.session_state.kwh_normal) * 100:.1f} %"
          if st.session_state.kwh_normal > 0 else "0 %")

st.caption("Normal BEMS reacts only to the current temperature. DT-BEMS uses the Digital Twin's "
           "short-horizon prediction plus live occupancy to pre-cool/heat gently, set back HVAC in "
           "empty zones, and dim lighting proportionally to occupancy — this is what drives the "
           "energy savings shown above.")

# --------------------------------------------------------------------
# Auto-run loop
# --------------------------------------------------------------------
if st.session_state.running:
    time.sleep(speed)
    step()
    st.rerun()
