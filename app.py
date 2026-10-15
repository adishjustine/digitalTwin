"""DT-BEMS dashboard: conventional BEMS vs digital-twin MPC BEMS.

Run with:
    pip install -r requirements.txt
    streamlit run app.py

All results are modelled with illustrative parameters. They are not
measurements of a real building.
"""
import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from models.building import default_zones
from models.digital_twin import DigitalTwin
from models.energy import CO2_FACTOR, DEFAULT_TARIFF
from simulation.controllers import DTController
from simulation.scenarios import SCENARIOS
from simulation.simulator import compare

st.set_page_config(page_title="DT-BEMS Dashboard", layout="wide")

ZONES = default_zones()
ZN = [z.name for z in ZONES]
C_BASE, C_DT = "#E07B00", "#1F77B4"   # orange = conventional, blue = digital twin
INTERVAL = 5

# --------------------------------------------------------------------------
# State + presets
# --------------------------------------------------------------------------
DEFAULTS = {"scenario": "Normal day", "out_off": 0.0, "start_off": 0.0,
            "m0": 1.0, "m1": 1.0, "m2": 1.0, "horizon": 30,
            "tariff": float(DEFAULT_TARIFF)}
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)


def preset(**kw):
    st.session_state.update(kw)


# --------------------------------------------------------------------------
# Cached simulation runs
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="Running both controllers on the same scenario...")
def run_scenario(name, out_off, start_off, mults, horizon):
    s = SCENARIOS[name]()
    occ = np.rint(s.occ * np.array(mults)[:, None]).astype(int)
    s = dataclasses.replace(
        s, t_out=s.t_out + out_off, occ=occ,
        init_temps=[t + start_off for t in s.init_temps])
    return s, compare(s, dt=DTController(horizon=horizon))


@st.cache_data(show_spinner="Running all five scenarios...")
def run_all(horizon):
    rows = []
    for name, build in SCENARIOS.items():
        r = compare(build(), dt=DTController(horizon=horizon))
        b, d = r["baseline"].summary, r["dt"].summary
        rows.append({
            "Scenario": name,
            "Conventional kWh": round(b["total_kwh"], 2),
            "Digital twin kWh": round(d["total_kwh"], 2),
            "Saved %": round(r["saved_pct"], 1),
            "Saved % (HVAC+light)": round(r["controllable_saved_pct"], 1),
            "Saved % (stored-heat adj.)": round(r["adjusted_saved_pct"], 1),
            "Comfort-violation min (conv.)": b["violation_min"],
            "Comfort-violation min (DT)": d["violation_min"],
            "Twin MAE 5 min (°C)": round(d["mae_5min"], 3),
            f"Twin MAE {horizon} min (°C)": round(d[f"mae_{horizon}min"], 3),
        })
    return pd.DataFrame(rows)


def fmt_time(minute):
    m = int(minute) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
sb = st.sidebar
sb.title("Controls")
sb.selectbox("Scenario", list(SCENARIOS), key="scenario")
sb.caption(SCENARIOS[st.session_state.scenario]().description)
sb.slider("Outdoor temperature offset (°C)", -5.0, 8.0, step=0.5, key="out_off")
sb.slider("Indoor starting temperature offset (°C)", -2.0, 5.0, step=0.5, key="start_off")
sb.markdown("**Occupancy multiplier per zone**")
sb.slider(ZN[0], 0.0, 2.0, step=0.25, key="m0")
sb.slider(ZN[1], 0.0, 2.0, step=0.25, key="m1")
sb.slider(ZN[2], 0.0, 2.0, step=0.25, key="m2")
sb.select_slider("Prediction horizon (min)", options=[15, 30, 45], key="horizon")
sb.number_input("Electricity tariff (₹/kWh)", 1.0, 30.0, step=0.5, key="tariff")

sb.markdown("**Quick presets**")
c1, c2 = sb.columns(2)
c1.button("Heatwave", on_click=preset,
          kwargs=dict(scenario="Heatwave", out_off=0.0), width="stretch")
c2.button("Empty meeting room", on_click=preset, kwargs=dict(m1=0.0), width="stretch")
c3, c4 = sb.columns(2)
c3.button("Full occupancy", on_click=preset, kwargs=dict(m0=1.5, m1=1.5, m2=1.5), width="stretch")
c4.button("Reset all", on_click=preset, kwargs=DEFAULTS, width="stretch")
sb.caption("Both controllers always replay the identical weather and occupancy. "
           "These controls affect the offline tabs only; the Live tab follows Wokwi.")

# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
S = st.session_state
scenario, res = run_scenario(
    S.scenario, S.out_off, S.start_off, (S.m0, S.m1, S.m2), S.horizon)
base, dt = res["baseline"], res["dt"]
bl, dl = base.log, dt.log
bs, ds = base.summary, dt.summary
horizon = S.horizon
tariff = S.tariff

st.title("Digital Twin Building Energy Management (DT-BEMS)")
st.caption("A conventional reactive BEMS vs a digital-twin predictive controller, "
           "run on identical simulated conditions. Modelled results with illustrative "
           "parameters; real savings need validation against actual building data.")

# KPI row -------------------------------------------------------------------
saved_kwh = bs["total_kwh"] - ds["total_kwh"]
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Energy: conventional", f"{bs['total_kwh']:.1f} kWh")
k2.metric("Energy: digital twin", f"{ds['total_kwh']:.1f} kWh",
          delta=f"{-res['saved_pct']:.1f}%", delta_color="inverse")
k3.metric("Cost saved", f"₹{saved_kwh * tariff:,.0f}")
k4.metric("Comfort violations (min)", f"{ds['violation_min']}",
          delta=f"{ds['violation_min'] - bs['violation_min']} vs conv.", delta_color="inverse")
k5.metric(f"Twin MAE ({horizon} min)", f"{ds[f'mae_{horizon}min']:.2f} °C")

# Time selector -------------------------------------------------------------
options = list(range(0, scenario.steps, INTERVAL))
label = lambda k: fmt_time(scenario.start_minute + k)
k_sel = st.select_slider(
    "Time of day (inspect the building and the optimiser at this moment)",
    options=options, value=options[len(options) // 4], format_func=label,
    key=f"time_{S.scenario}_{scenario.steps}")
minute = (scenario.start_minute + k_sel) % 1440

tabs = st.tabs(["Building", "Digital twin", "Energy", "Optimiser", "Impact",
                "All scenarios", "Live hardware (Wokwi)"])

# --------------------------------------------------------------------------
# Tab: building overview
# --------------------------------------------------------------------------
with tabs[0]:
    b_now = bl[bl.k == k_sel].set_index("zone")
    d_now = dl[dl.k == k_sel].set_index("zone")
    st.subheader(f"Building at {label(k_sel)}")
    a, b_, c = st.columns(3)
    a.metric("Outdoor temperature", f"{d_now.t_out.iloc[0]:.1f} °C")
    b_.metric("Building power: conventional", f"{b_now.total_w.sum() / 1000:.2f} kW")
    c.metric("Building power: digital twin", f"{d_now.total_w.sum() / 1000:.2f} kW")
    rows = []
    for z in range(3):
        rows.append({
            "Zone": ZN[z], "Occupancy": int(d_now.occ[z]),
            "Temp conv. (°C)": round(b_now["T"][z], 2),
            "Temp DT (°C)": round(d_now["T"][z], 2),
            "HVAC conv.": b_now.hvac_mode[z], "HVAC DT": d_now.hvac_mode[z],
            "Lights conv.": "ON" if b_now.light_on[z] else "OFF",
            "Lights DT": "ON" if d_now.light_on[z] else "OFF",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Comfort band while occupied: 22-26 °C. Humidity is not modelled in this version.")

# --------------------------------------------------------------------------
# Tab: digital twin
# --------------------------------------------------------------------------
with tabs[1]:
    z_sel = st.selectbox("Zone", range(3), format_func=lambda i: ZN[i], key="z_twin")
    zb = bl[bl.zone == z_sel]
    zd = dl[dl.zone == z_sel]
    pred = dt.predictions
    pred = pred[(pred.zone == z_sel) & (pred.label == f"{horizon}min")]
    hx = lambda k: (scenario.start_minute + k) / 60.0

    fig = go.Figure()
    fig.add_hrect(y0=ZONES[z_sel].comfort_min, y1=ZONES[z_sel].comfort_max,
                  fillcolor="#2CA02C", opacity=0.10, line_width=0,
                  annotation_text="comfort band", annotation_position="top left")
    fig.add_trace(go.Scatter(x=hx(zb.k), y=zb["T"], name="Conventional (actual)",
                             line=dict(color=C_BASE, width=2)))
    fig.add_trace(go.Scatter(x=hx(zd.k), y=zd["T"], name="Digital twin (actual)",
                             line=dict(color=C_DT, width=2)))
    fig.add_trace(go.Scatter(x=hx(pred.target), y=pred.predicted,
                             name=f"Twin prediction ({horizon} min ahead)",
                             mode="lines", line=dict(color=C_DT, width=1.5, dash="dot")))
    fig.add_vline(x=hx(k_sel), line_dash="dash", line_color="gray")
    fig.update_layout(height=380, xaxis_title="Hour of day", yaxis_title="Temperature (°C)",
                      margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, width="stretch")

    pw = go.Figure()
    for lg_, nm, col in ((zb, "Conventional", C_BASE), (zd, "Digital twin", C_DT)):
        pw.add_trace(go.Scatter(x=hx(lg_.k), y=lg_.hvac_w / 1000.0, name=f"{nm} HVAC power",
                                line=dict(color=col, width=1.5, shape="hv")))
    pw.add_vline(x=hx(k_sel), line_dash="dash", line_color="gray")
    pw.update_layout(height=230, xaxis_title="Hour of day", yaxis_title="HVAC power (kW)",
                     margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.15))
    st.plotly_chart(pw, width="stretch")
    st.caption("Temperatures are held near the setpoint by design, so slider changes show up "
               "mainly here and in the Energy tab, as more or less HVAC power.")

    m1_, m2_, m3_ = st.columns(3)
    m1_.metric("MAE 5 min ahead (all zones)", f"{ds['mae_5min']:.3f} °C")
    m2_.metric(f"MAE {horizon} min ahead (all zones)", f"{ds[f'mae_{horizon}min']:.3f} °C")
    zone_mae = dt.predictions
    zone_mae = zone_mae[(zone_mae.zone == z_sel) & (zone_mae.label == f"{horizon}min")].abs_error.mean()
    m3_.metric(f"MAE {horizon} min, this zone", f"{zone_mae:.3f} °C")
    st.caption(f"The {horizon}-minute prediction assumes the chosen plan is held, but the "
               "controller re-plans every 5 minutes, so part of that error comes from changed "
               "decisions and not only model error. The twin deliberately uses slightly wrong "
               "building parameters (UA +10%, C -5%).")

    tw = DigitalTwin(ZONES, horizon=horizon)
    occ_rows = []
    for z in range(3):
        now_occ = int(dl[(dl.k == k_sel) & (dl.zone == z)].occ.iloc[0])
        occ_rows.append({"Zone": ZN[z], "Occupancy now": now_occ,
                         f"Predicted in {horizon} min": tw.predict_occupancy(z, minute, now_occ, horizon)[-1]})
    st.markdown(f"**Occupancy prediction from {label(k_sel)}** (schedule-based estimate)")
    st.dataframe(pd.DataFrame(occ_rows), hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# Tab: energy comparison
# --------------------------------------------------------------------------
with tabs[2]:
    pb = bl.groupby("k").total_w.sum() / 1000
    pd_ = dl.groupby("k").total_w.sum() / 1000
    x = (scenario.start_minute + pb.index) / 60.0
    f1 = go.Figure()
    f1.add_trace(go.Scatter(x=x, y=pb.values, name="Conventional", line=dict(color=C_BASE)))
    f1.add_trace(go.Scatter(x=x, y=pd_.values, name="Digital twin", line=dict(color=C_DT)))
    f1.add_vline(x=hx(k_sel), line_dash="dash", line_color="gray")
    f1.update_layout(height=320, xaxis_title="Hour of day", yaxis_title="Building power (kW)",
                     margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.1))
    st.plotly_chart(f1, width="stretch")

    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=x, y=(pb / 60).cumsum().values, name="Conventional",
                            line=dict(color=C_BASE)))
    f2.add_trace(go.Scatter(x=x, y=(pd_ / 60).cumsum().values, name="Digital twin",
                            line=dict(color=C_DT)))
    f2.update_layout(height=300, xaxis_title="Hour of day", yaxis_title="Cumulative energy (kWh)",
                     margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.1))
    st.plotly_chart(f2, width="stretch")

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Energy saved", f"{saved_kwh:.2f} kWh")
    e2.metric("Reduction (total)", f"{res['saved_pct']:.1f} %")
    e3.metric("Reduction (HVAC + lighting only)", f"{res['controllable_saved_pct']:.1f} %")
    e4.metric("Reduction (adjusted for stored heat)", f"{res['adjusted_saved_pct']:.1f} %")
    st.caption("Total includes equipment load, which neither controller can change. The adjusted "
               "figure accounts for rooms ending warmer than they started, which would otherwise "
               "look like savings but is just deferred cooling.")

# --------------------------------------------------------------------------
# Tab: optimiser
# --------------------------------------------------------------------------
with tabs[3]:
    z_opt = st.selectbox("Zone", range(3), format_func=lambda i: ZN[i], key="z_opt")
    kp = (k_sel // INTERVAL) * INTERVAL
    plans = dt.plans
    cand = plans[(plans.k == kp) & (plans.zone == z_opt)].copy()
    chosen = cand[cand.chosen].iloc[0]
    n_rej = int((~cand.feasible).sum())
    st.markdown(
        f"**Decision at {label(kp)} for {ZN[z_opt]}:** plan `{chosen.plan}` "
        f"-> apply **{chosen.first_mode}** for the next {INTERVAL} min. "
        f"{len(cand)} plans evaluated, {n_rej} rejected, "
        f"{len(cand) - n_rej} feasible.")
    cand = cand.sort_values(["chosen", "feasible", "energy_kwh"],
                            ascending=[False, False, True])
    show = cand.rename(columns={
        "plan": "Plan (3 x 10 min)", "first_mode": "First action",
        "min_temp": "Min temp (°C)", "max_temp": "Max temp (°C)",
        "energy_kwh": "Energy (kWh)", "feasible": "Feasible",
        "reason": "Reason", "chosen": "Chosen"})[
        ["Chosen", "Plan (3 x 10 min)", "First action", "Min temp (°C)",
         "Max temp (°C)", "Energy (kWh)", "Feasible", "Reason"]]
    styled = (show.style
              .format({"Min temp (°C)": "{:.2f}", "Max temp (°C)": "{:.2f}",
                       "Energy (kWh)": "{:.3f}"})
              .apply(lambda r: ["background-color: rgba(31,119,180,0.18)" if r["Chosen"] else ""
                                for _ in r], axis=1))
    st.dataframe(styled, hide_index=True, width="stretch", height=420)
    st.caption("Each plan is simulated with the twin. Plans leaving the comfort band "
               "(with a 0.3 °C safety margin) are rejected; the lowest-cost feasible plan wins, "
               "including a small penalty for switching and for leaving stored heat at the end.")

# --------------------------------------------------------------------------
# Tab: environmental / cost impact
# --------------------------------------------------------------------------
with tabs[4]:
    def runtime(log, mode=None):
        on = (log.hvac_mode != "OFF") if mode is None else (log.hvac_mode == mode)
        return on.mean() * 100

    imp = pd.DataFrame({
        "Metric": ["Energy (kWh)", "Electricity cost (₹)", "CO₂ (kg)",
                   "Comfort-violation minutes", "Degree-minutes outside comfort",
                   "Peak building power (kW)", "HVAC running (% of zone-minutes)",
                   "HVAC on HIGH (% of zone-minutes)"],
        "Conventional": [bs["total_kwh"], bs["total_kwh"] * tariff, bs["total_kwh"] * CO2_FACTOR,
                         bs["violation_min"], bs["violation_degmin"], bs["peak_kw"],
                         runtime(bl), runtime(bl, "HIGH")],
        "Digital twin": [ds["total_kwh"], ds["total_kwh"] * tariff, ds["total_kwh"] * CO2_FACTOR,
                         ds["violation_min"], ds["violation_degmin"], ds["peak_kw"],
                         runtime(dl), runtime(dl, "HIGH")],
    })
    imp["Difference (DT - conv.)"] = imp["Digital twin"] - imp["Conventional"]
    st.dataframe(imp.style.format({"Conventional": "{:.2f}", "Digital twin": "{:.2f}",
                                   "Difference (DT - conv.)": "{:+.2f}"}),
                 hide_index=True, width="stretch")
    st.caption(f"CO₂ uses {CO2_FACTOR} kg/kWh (approximate grid average; replace with a documented "
               "figure for your intended scenario). Tariff is set in the sidebar.")

# --------------------------------------------------------------------------
# Tab: all scenarios
# --------------------------------------------------------------------------
with tabs[5]:
    st.markdown("**All five predefined scenarios** (default sliders, current horizon)")
    st.dataframe(run_all(horizon), hide_index=True, width="stretch")
    st.caption("Evidence table for the demo. Expected behaviours are test objectives, not "
               "guaranteed savings; report any scenario where the twin does worse.")

# --------------------------------------------------------------------------
# Tab: live hardware (Wokwi ESP32 -> MQTT -> bridge -> twin -> optimiser)
# --------------------------------------------------------------------------
_DATA = Path(__file__).resolve().parent / "data"
LIVE_STATE = _DATA / "live_state.json"
LIVE_LOG = _DATA / "live_log.csv"


@st.fragment(run_every="2s")
def live_panel():
    if not LIVE_STATE.exists():
        st.info(
            "No live data yet. Start the bridge in a terminal:\n\n"
            "`python -m integration.mqtt_bridge`\n\n"
            "then press Play on the Wokwi project (see wokwi/README.md). "
            "No Wokwi? Test the same path with "
            "`python -m integration.fake_device --mqtt --scenario \"Heatwave\"`.")
        return
    try:
        state = json.loads(LIVE_STATE.read_text())
    except (OSError, ValueError):
        st.caption("Reading live data...")
        return

    age = time.time() - state["updated"]
    h = state["horizon"]
    st.markdown(
        f"**Simulated time {fmt_time(state['minute'])}** (tick {state['k']}). "
        + (f":green[receiving data, last update {age:.0f}s ago]" if age < 15
           else f":orange[no update for {age:.0f}s. Is the ESP32 running and the bridge connected?]"))
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Outdoor (DHT22)", f"{state['t_out']:.1f} °C")
    c2.metric("Humidity", "n/a" if state["hum"] is None else f"{state['hum']:.0f} %")
    c3.metric("Energy so far", f"{state['kwh']:.2f} kWh")
    c4.metric("Minutes outside comfort", state["violation_min"])
    mae = state.get(f"mae_{h}min")
    c5.metric(f"Twin MAE {h} min", "n/a" if mae is None else f"{mae:.2f} °C")

    zrows = [{"Zone": z["name"], "Sensor temp (°C)": z["T"], "Twin estimate (°C)": z["T_est"],
              "Occupancy": z["occ"], "HVAC": z["mode"], "Lights": "ON" if z["light"] else "OFF",
              "Power (W)": z["power_w"],
              "Plans feasible": f"{z['n_feasible']}/{z['n_candidates']}"}
             for z in state["zones"]]
    st.dataframe(pd.DataFrame(zrows), hide_index=True, width="stretch")

    try:
        log = pd.read_csv(LIVE_LOG)
    except (OSError, ValueError, pd.errors.EmptyDataError):
        log = pd.DataFrame()
    if not log.empty:
        from plotly.subplots import make_subplots
        x0 = log.minute.iloc[0] - log.k.iloc[0]
        log = log.assign(hour=(x0 + log.k) / 60.0)          # continuous simulated hours
        recent = log[log.k > log.k.max() - 240]
        zone_names = sorted(recent.zone_name.unique())
        colors = ["#1F77B4", "#E07B00", "#9467BD"]
        fig = make_subplots(
            rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.06,
            subplot_titles=("Sensor temperature (°C): the controlled variable, held in the band",
                            "HVAC electrical power (kW): where the controller's response shows",
                            "Occupancy (people), set by the Wokwi potentiometers",
                            "Outdoor temperature (°C), set by the Wokwi DHT22"))
        fig.add_hrect(y0=22, y1=26, fillcolor="#2CA02C", opacity=0.10, line_width=0, row=1, col=1)
        for zi, name in enumerate(zone_names):
            zz = recent[recent.zone_name == name]
            col = colors[zi % 3]
            fig.add_trace(go.Scatter(x=zz.hour, y=zz["T"], name=name, mode="lines",
                                     line=dict(color=col), legendgroup=name), row=1, col=1)
            power = zz["hvac_w"] / 1000.0 if "hvac_w" in zz else zz["total_w"] / 1000.0
            fig.add_trace(go.Scatter(x=zz.hour, y=power, name=name, mode="lines",
                                     line=dict(color=col, shape="hv"), legendgroup=name,
                                     showlegend=False), row=2, col=1)
            fig.add_trace(go.Scatter(x=zz.hour, y=zz.occ, name=name, mode="lines",
                                     line=dict(color=col, shape="hv"), legendgroup=name,
                                     showlegend=False), row=3, col=1)
        one = recent[recent.zone_name == zone_names[0]]
        fig.add_trace(go.Scatter(x=one.hour, y=one.t_out, name="Outdoor", mode="lines",
                                 line=dict(color="#555555"), showlegend=False), row=4, col=1)
        fig.update_xaxes(title_text="Simulated hour of day", row=4, col=1)
        fig.update_layout(height=760, margin=dict(l=10, r=10, t=40, b=10),
                          legend=dict(orientation="h", y=1.06))
        st.plotly_chart(fig, width="stretch")
        st.caption("Why the temperature line looks calm: the twin's job is to keep it inside the "
                   "22-26 °C band, so a disturbance (hotter outside, more people) shows up as "
                   "more HVAC power, not as a different temperature. Watch the second panel.")

    zsel = st.selectbox("Latest optimiser decision for", range(len(state["zones"])),
                        format_func=lambda i: state["zones"][i]["name"], key="z_live")
    cands = state["zones"][zsel]["candidates"]
    if cands:
        st.caption("Top 12 of the plans evaluated at the latest 5-minute re-plan "
                   "(chosen first, then feasible by energy).")
        st.dataframe(pd.DataFrame(cands).rename(columns={
            "plan": "Plan", "first_mode": "First action", "min_temp": "Min °C",
            "max_temp": "Max °C", "energy_kwh": "kWh", "feasible": "Feasible",
            "reason": "Reason", "chosen": "Chosen"}), hide_index=True, width="stretch")
    st.caption("The sidebar sliders and presets only affect the offline tabs. The live view is driven "
               "by Wokwi: DHT22 = outdoor temperature, the three potentiometers = occupancy. "
               "Live mode shows the digital-twin controller acting on the (simulated) hardware. "
               "The fair side-by-side energy comparison is the offline simulator in the other tabs, "
               "because a conventional controller cannot be run on the same physical history here.")


with tabs[6]:
    live_panel()
