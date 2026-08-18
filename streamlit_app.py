"""
Swiggy Delivery Time Predictor — Map-Based Streamlit UI
========================================================
Click the map to place restaurant & delivery pins,
fill in delivery context via the sidebar, and get an
instant ML-powered delivery time prediction.
"""

import datetime
import math
import sys
from pathlib import Path

import folium
import joblib
import pandas as pd
import streamlit as st
from sklearn import set_config
from sklearn.pipeline import Pipeline
from streamlit_folium import st_folium

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from scripts.data_clean_utils import perform_data_cleaning

set_config(transform_output="pandas")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Swiggy Delivery Predictor",
    page_icon="🛵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* ─── Global background ─────────────────────────────────────── */
.stApp { background: #0d0f1a; }

/* ─── Hide Streamlit chrome ─────────────────────────────────── */
#MainMenu, footer, header { visibility: hidden; }

/* ─── Header banner ─────────────────────────────────────────── */
.hero-banner {
    background: linear-gradient(135deg, #fc8019 0%, #e84d0e 60%, #c73a00 100%);
    border-radius: 18px;
    padding: 28px 36px;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 18px;
}
.hero-icon { font-size: 3rem; }
.hero-title { color: #fff; font-size: 2rem; font-weight: 900; margin: 0; line-height: 1.1; }
.hero-sub   { color: rgba(255,255,255,0.82); font-size: 0.92rem; margin: 5px 0 0 0; }
.hero-badge {
    margin-left: auto;
    background: rgba(255,255,255,0.18);
    border: 1px solid rgba(255,255,255,0.35);
    border-radius: 24px;
    padding: 8px 20px;
    color: white;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    white-space: nowrap;
}

/* ─── Status bar ─────────────────────────────────────────────── */
.status-bar {
    background: #161928;
    border: 1px solid #252840;
    border-radius: 12px;
    padding: 14px 20px;
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 14px;
}
.status-icon { font-size: 1.5rem; }
.status-text { color: #e0e4f0; font-size: 0.93rem; }
.status-text strong { color: #fc8019; }

/* ─── Result card ────────────────────────────────────────────── */
.result-wrap {
    background: linear-gradient(160deg, #161928 0%, #0d1020 100%);
    border: 2px solid #fc8019;
    border-radius: 22px;
    padding: 36px 32px 28px;
    text-align: center;
    margin-top: 22px;
    position: relative;
    overflow: hidden;
}
.result-wrap::before {
    content: '';
    position: absolute;
    top: -60px; left: 50%;
    transform: translateX(-50%);
    width: 220px; height: 220px;
    background: radial-gradient(circle, #fc801922, transparent 70%);
    pointer-events: none;
}
.result-label  { color: rgba(255,255,255,0.45); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.1em; }
.result-number { font-size: 6rem; font-weight: 900; color: #fc8019; line-height: 1; }
.result-unit   { color: rgba(255,255,255,0.55); font-size: 1.1rem; margin-top: 4px; }

/* ─── Speed badge ────────────────────────────────────────────── */
.speed-badge {
    display: inline-block;
    border-radius: 30px;
    padding: 7px 22px;
    font-size: 0.9rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    margin-top: 14px;
}
.fast     { background: #00c85122; color: #00c851; border: 1.5px solid #00c851; }
.moderate { background: #ffbb3322; color: #ffbb33; border: 1.5px solid #ffbb33; }
.slow     { background: #ff444422; color: #ff6666; border: 1.5px solid #ff4444; }

/* ─── Info pill row ──────────────────────────────────────────── */
.pill-row { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 22px; }
.pill {
    background: #1f2340;
    border: 1px solid #2d3155;
    border-radius: 10px;
    padding: 8px 16px;
    color: rgba(255,255,255,0.75);
    font-size: 0.82rem;
}
.pill b { color: #fc8019; }

/* ─── Model stat cards ───────────────────────────────────────── */
.stat-card {
    background: #161928;
    border: 1px solid #252840;
    border-radius: 14px;
    padding: 20px 16px;
    text-align: center;
}
.stat-icon  { font-size: 2rem; margin-bottom: 8px; }
.stat-value { color: #fc8019; font-size: 1.2rem; font-weight: 800; }
.stat-label { color: rgba(255,255,255,0.45); font-size: 0.78rem; margin-top: 4px; }

/* ─── Sidebar ────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: #12152a !important;
    border-right: 1px solid #252840;
}
section[data-testid="stSidebar"] * { color: #d0d4ea; }

/* ─── Step tracker ───────────────────────────────────────────── */
.step-track { display: flex; flex-direction: column; gap: 8px; margin: 10px 0 18px; }
.step-item {
    display: flex; align-items: center; gap: 10px;
    background: #1c2038;
    border: 1px solid #282c4a;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 0.84rem;
    color: rgba(255,255,255,0.45);
    transition: all 0.2s;
}
.step-item.active {
    border-color: #fc8019;
    background: linear-gradient(90deg, #fc801915, #fc801905);
    color: #fff;
}
.step-item.done {
    border-color: #00c851;
    background: #00c85108;
    color: #00c851;
}
.step-num {
    width: 24px; height: 24px;
    border-radius: 50%;
    background: #282c4a;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.78rem; flex-shrink: 0;
}
.step-item.active .step-num { background: #fc8019; color: white; }
.step-item.done  .step-num { background: #00c851; color: white; }

/* ─── Sidebar section header ─────────────────────────────────── */
.section-hdr {
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #fc8019;
    margin: 18px 0 8px;
}

/* ─── Distance display (sidebar) ─────────────────────────────── */
.dist-box {
    background: #1c2038;
    border: 1.5px solid #fc8019;
    border-radius: 12px;
    padding: 14px;
    text-align: center;
    margin: 10px 0;
}
.dist-num   { font-size: 2.2rem; font-weight: 900; color: #fc8019; }
.dist-label { font-size: 0.75rem; color: rgba(255,255,255,0.4); margin-top: 2px; }

/* ─── Predict button ─────────────────────────────────────────── */
div[data-testid="stButton"] > button {
    width: 100%;
    background: linear-gradient(135deg, #fc8019, #e84d0e) !important;
    color: white !important;
    font-weight: 800 !important;
    font-size: 1.05rem !important;
    padding: 14px !important;
    border: none !important;
    border-radius: 14px !important;
    letter-spacing: 0.03em;
    transition: transform 0.15s, box-shadow 0.15s !important;
    box-shadow: 0 4px 20px #fc801940 !important;
}
div[data-testid="stButton"] > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 28px #fc801960 !important;
}

/* ─── Sliders & selects ──────────────────────────────────────── */
.stSlider > div { color: #d0d4ea; }

/* ─── Footerline ─────────────────────────────────────────────── */
.footer-note { color: rgba(255,255,255,0.2); font-size: 0.73rem; margin-top: 18px; text-align: center; }
</style>
""",
    unsafe_allow_html=True,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Loading model…")
def load_pipeline():
    preprocessor = joblib.load(ROOT / "models" / "preprocessor.joblib")
    model        = joblib.load(ROOT / "models" / "model.joblib")
    return Pipeline(steps=[("preprocess", preprocessor), ("regressor", model)])


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ── Session state init ────────────────────────────────────────────────────────
for key, default in {
    "rest_coords":      None,
    "del_coords":       None,
    "last_click_key":   None,
    "prediction":       None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🛵 Swiggy Predictor")
    st.markdown(
        "<div style='color:rgba(255,255,255,0.4);font-size:0.8rem;margin-bottom:4px'>"
        "ML-powered delivery time estimation</div>",
        unsafe_allow_html=True,
    )

    # ── Step tracker
    r, d = st.session_state.rest_coords, st.session_state.del_coords
    s1 = "done" if r else "active"
    s2 = "done" if d else ("active" if r else "step-item")
    s3 = "active" if (r and d) else "step-item"

    st.markdown(
        f"""
        <div class="step-track">
          <div class="step-item {s1}">
            <div class="step-num">{'✓' if r else '1'}</div>
            Click map → Restaurant
          </div>
          <div class="step-item {s2}">
            <div class="step-num">{'✓' if d else '2'}</div>
            Click map → Delivery
          </div>
          <div class="step-item {s3}">
            <div class="step-num">3</div>
            Fill form & Predict
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Distance readout (if both pins placed)
    if r and d:
        dist_km = haversine_km(r[0], r[1], d[0], d[1])
        st.markdown(
            f"""
            <div class="dist-box">
              <div class="dist-num">{dist_km:.1f} km</div>
              <div class="dist-label">Delivery Distance</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Rider details
    st.markdown('<div class="section-hdr">🧑 Rider Details</div>', unsafe_allow_html=True)
    rider_age     = st.slider("Rider Age", 18, 55, 28)
    rider_rating  = st.slider("Rider Rating ⭐", 1.0, 5.0, 4.5, 0.1)
    vehicle_type  = st.selectbox(
        "Vehicle Type",
        ["motorcycle", "scooter", "electric_scooter", "bicycle"],
        format_func=lambda x: {"motorcycle": "🏍️ Motorcycle", "scooter": "🛵 Scooter",
                                "electric_scooter": "⚡ E-Scooter", "bicycle": "🚲 Bicycle"}[x],
    )
    vehicle_cond  = st.select_slider(
        "Vehicle Condition",
        options=[0, 1, 2, 3],
        value=2,
        format_func=lambda x: ["💀 Poor", "😐 Average", "😊 Good", "🌟 Excellent"][x],
    )
    multi_del     = st.selectbox("Multiple Deliveries", [0, 1, 2, 3],
                                  format_func=lambda x: f"{'🔴' if x > 1 else '🟡' if x == 1 else '🟢'} {x} deliveries")

    # ── Order details
    st.markdown('<div class="section-hdr">📦 Order Details</div>', unsafe_allow_html=True)
    order_type    = st.selectbox(
        "Type of Order",
        ["Snack", "Meal", "Drinks", "Buffet"],
        format_func=lambda x: {"Snack": "🍟 Snack", "Meal": "🍱 Meal",
                                "Drinks": "🥤 Drinks", "Buffet": "🍽️ Buffet"}[x],
    )
    order_date    = st.date_input("Order Date", datetime.date.today())
    order_time    = st.time_input("Order Placed At", datetime.time(12, 30), step=300)
    pickup_time   = st.time_input("Rider Picked At", datetime.time(12, 45), step=300)

    # ── Conditions
    st.markdown('<div class="section-hdr">🌤️ Conditions</div>', unsafe_allow_html=True)
    weather  = st.selectbox(
        "Weather",
        ["Sunny", "Cloudy", "Windy", "Fog", "Stormy", "Sandstorms"],
        format_func=lambda x: {"Sunny": "☀️ Sunny", "Cloudy": "☁️ Cloudy", "Windy": "💨 Windy",
                                "Fog": "🌫️ Fog", "Stormy": "⛈️ Stormy", "Sandstorms": "🌪️ Sandstorms"}[x],
    )
    traffic  = st.selectbox(
        "Traffic Density",
        ["Low", "Medium", "High", "Jam"],
        format_func=lambda x: {"Low": "🟢 Low", "Medium": "🟡 Medium",
                                "High": "🟠 High", "Jam": "🔴 Jam"}[x],
    )
    city_type = st.selectbox("City Type", ["Urban", "Metropolitian", "Semi-Urban"],
                              format_func=lambda x: {"Urban": "🏙️ Urban",
                                                      "Metropolitian": "🌆 Metropolitian",
                                                      "Semi-Urban": "🌇 Semi-Urban"}[x])
    festival  = st.selectbox("Festival?", ["No", "Yes"],
                              format_func=lambda x: "🎉 Yes" if x == "Yes" else "—  No")

    st.divider()

    # ── Reset
    if st.button("🔄 Reset Map & Prediction"):
        for key in ("rest_coords", "del_coords", "last_click_key", "prediction"):
            st.session_state[key] = None
        st.rerun()

# ── MAIN AREA ─────────────────────────────────────────────────────────────────

# Hero banner
st.markdown(
    """
    <div class="hero-banner">
      <div class="hero-icon">🛵</div>
      <div>
        <p class="hero-title">Swiggy Delivery Time Predictor</p>
        <p class="hero-sub">
          Click the map to set restaurant &amp; delivery locations · Fill details · Get instant ML prediction
        </p>
      </div>
      <div class="hero-badge">Stacking Regressor · 45K+ Orders</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Status bar
r, d = st.session_state.rest_coords, st.session_state.del_coords

if r is None:
    icon, msg = "🔴", "📍 <strong>Step 1:</strong> Click anywhere on the map to drop the <strong>Restaurant</strong> pin"
elif d is None:
    icon, msg = "🔵", (
        f"🍽️ Restaurant pinned at <strong>({r[0]:.4f}, {r[1]:.4f})</strong> · "
        "Now click to drop the <strong>Delivery Location</strong> pin"
    )
else:
    dist_km = haversine_km(r[0], r[1], d[0], d[1])
    icon, msg = "✅", (
        f"Both locations set · Distance: <strong>{dist_km:.1f} km</strong> · "
        "Fill sidebar details, then click <strong>Predict</strong>"
    )

st.markdown(
    f"""
    <div class="status-bar">
      <span class="status-icon">{icon}</span>
      <span class="status-text">{msg}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── BUILD MAP ─────────────────────────────────────────────────────────────────
map_center = [20.5937, 78.9629]
zoom_start = 5

if r and not d:
    map_center = [r[0], r[1]]
    zoom_start = 11
elif r and d:
    map_center = [(r[0] + d[0]) / 2, (r[1] + d[1]) / 2]
    zoom_start = 10

m = folium.Map(
    location=map_center,
    zoom_start=zoom_start,
    tiles="CartoDB dark_matter",
    prefer_canvas=True,
)

# Restaurant pin
if r:
    folium.Marker(
        location=r,
        tooltip=folium.Tooltip("🍽️ Restaurant", sticky=True),
        popup=folium.Popup(
            f"<b>🍽️ Restaurant</b><br>Lat: {r[0]:.5f}<br>Lon: {r[1]:.5f}",
            max_width=180,
        ),
        icon=folium.Icon(color="orange", icon="cutlery", prefix="fa"),
    ).add_to(m)

# Delivery pin
if d:
    folium.Marker(
        location=d,
        tooltip=folium.Tooltip("📦 Delivery Location", sticky=True),
        popup=folium.Popup(
            f"<b>📦 Delivery</b><br>Lat: {d[0]:.5f}<br>Lon: {d[1]:.5f}",
            max_width=180,
        ),
        icon=folium.Icon(color="blue", icon="home", prefix="fa"),
    ).add_to(m)

# Route line + distance label
if r and d:
    dist_km = haversine_km(r[0], r[1], d[0], d[1])
    folium.PolyLine(
        locations=[r, d],
        color="#fc8019",
        weight=3,
        opacity=0.85,
        dash_array="12 6",
    ).add_to(m)

    mid = [(r[0] + d[0]) / 2, (r[1] + d[1]) / 2]
    folium.Marker(
        location=mid,
        icon=folium.DivIcon(
            html=(
                f'<div style="background:#fc8019;color:#fff;padding:5px 12px;'
                f'border-radius:14px;font-weight:800;font-size:13px;'
                f'white-space:nowrap;box-shadow:0 2px 8px #00000060">'
                f'📏 {dist_km:.1f} km</div>'
            ),
            icon_size=(120, 32),
            icon_anchor=(60, 16),
        ),
    ).add_to(m)

# Render map
map_out = st_folium(
    m,
    width="100%",
    height=530,
    key="swiggy_map",
    returned_objects=["last_clicked"],
)

# ── HANDLE MAP CLICKS ─────────────────────────────────────────────────────────
if map_out and map_out.get("last_clicked"):
    lat = map_out["last_clicked"]["lat"]
    lng = map_out["last_clicked"]["lng"]
    click_key = f"{lat:.6f},{lng:.6f}"

    if click_key != st.session_state.last_click_key:
        st.session_state.last_click_key = click_key

        if st.session_state.rest_coords is None:
            st.session_state.rest_coords = (lat, lng)
            st.session_state.prediction  = None
        elif st.session_state.del_coords is None:
            st.session_state.del_coords  = (lat, lng)
            st.session_state.prediction  = None
        else:
            # Third click → restart
            st.session_state.rest_coords = (lat, lng)
            st.session_state.del_coords  = None
            st.session_state.prediction  = None

        st.rerun()

# ── PREDICT BUTTON ────────────────────────────────────────────────────────────
r, d = st.session_state.rest_coords, st.session_state.del_coords

if r and d:
    st.markdown("<br>", unsafe_allow_html=True)
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        do_predict = st.button("🚀  Predict Delivery Time", use_container_width=True)

    if do_predict:
        # ── Validate times
        t_order  = datetime.datetime.combine(datetime.date.today(), order_time)
        t_pickup = datetime.datetime.combine(datetime.date.today(), pickup_time)
        if t_pickup <= t_order:
            st.error("⚠️ 'Rider Picked At' must be later than 'Order Placed At'.")
        else:
            with st.spinner("Running prediction…"):
                try:
                    city_prefix_map = {
                        "Urban": "BANGRES",
                        "Metropolitian": "DELHIRES",
                        "Semi-Urban": "PUNERES",
                    }
                    rider_id = f"{city_prefix_map[city_type]}18DEL01"

                    input_df = pd.DataFrame(
                        {
                            "ID":                         ["0x0001"],
                            "Delivery_person_ID":          [rider_id],
                            "Delivery_person_Age":          [str(rider_age)],
                            "Delivery_person_Ratings":      [str(rider_rating)],
                            "Restaurant_latitude":          [r[0]],
                            "Restaurant_longitude":         [r[1]],
                            "Delivery_location_latitude":   [d[0]],
                            "Delivery_location_longitude":  [d[1]],
                            "Order_Date":                   [order_date.strftime("%d-%m-%Y")],
                            "Time_Orderd":                  [order_time.strftime("%H:%M:%S")],
                            "Time_Order_picked":            [pickup_time.strftime("%H:%M:%S")],
                            "Weatherconditions":            [f"conditions {weather}"],
                            "Road_traffic_density":         [traffic],
                            "Vehicle_condition":            [vehicle_cond],
                            "Type_of_order":                [order_type],
                            "Type_of_vehicle":              [vehicle_type],
                            "multiple_deliveries":          [str(multi_del)],
                            "Festival":                     [festival],
                            "City":                         [city_type],
                        }
                    )

                    cleaned = perform_data_cleaning(input_df)
                    pipe    = load_pipeline()
                    pred    = float(pipe.predict(cleaned)[0])
                    st.session_state.prediction = round(pred, 1)

                except Exception as exc:
                    st.error(f"Prediction failed: {exc}")
                    with st.expander("Debug info"):
                        st.exception(exc)

# ── RESULT CARD ───────────────────────────────────────────────────────────────
if st.session_state.prediction is not None:
    pred  = st.session_state.prediction
    r, d  = st.session_state.rest_coords, st.session_state.del_coords
    dist_km = haversine_km(r[0], r[1], d[0], d[1])

    if pred < 20:
        badge_cls, badge_txt = "fast",     "⚡ VERY FAST"
    elif pred < 35:
        badge_cls, badge_txt = "moderate", "🕐 MODERATE"
    else:
        badge_cls, badge_txt = "slow",     "🐢 SLOW"

    pickup_wait = int(
        (datetime.datetime.combine(datetime.date.today(), pickup_time)
         - datetime.datetime.combine(datetime.date.today(), order_time)).seconds / 60
    )

    st.markdown(
        f"""
        <div class="result-wrap">
          <div class="result-label">Predicted Delivery Time</div>
          <div class="result-number">{pred:.0f}</div>
          <div class="result-unit">minutes</div>
          <div><span class="speed-badge {badge_cls}">{badge_txt}</span></div>

          <div class="pill-row">
            <div class="pill">📍 Distance <b>{dist_km:.1f} km</b></div>
            <div class="pill">🚦 Traffic <b>{traffic}</b></div>
            <div class="pill">🌤️ Weather <b>{weather}</b></div>
            <div class="pill">🛵 Vehicle <b>{vehicle_type.replace('_', ' ').title()}</b></div>
            <div class="pill">⏱️ Pickup wait <b>{pickup_wait} min</b></div>
            <div class="pill">🏙️ City <b>{city_type}</b></div>
            <div class="pill">{'🎉 Festival' if festival == 'Yes' else '—'} <b>{festival}</b></div>
          </div>

          <div class="footer-note" style="margin-top:22px">
            Stacking Regressor (Random Forest + LightGBM → Linear Regression) &nbsp;·&nbsp;
            DVC Pipeline &nbsp;·&nbsp; MLflow / DagsHub Tracking
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ── MODEL STATS (shown when map is empty) ─────────────────────────────────────
elif st.session_state.rest_coords is None:
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    stats = [
        ("🤖", "Stacking Regressor", "RF + LightGBM → LinearReg"),
        ("📊", "45,593 Orders",       "Swiggy delivery dataset"),
        ("🎯", "~4.5 min MAE",        "Mean Absolute Error on test"),
        ("🔁", "DVC Pipeline",         "6-stage reproducible pipeline"),
    ]
    for col, (icon, val, lbl) in zip([c1, c2, c3, c4], stats):
        with col:
            st.markdown(
                f"""
                <div class="stat-card">
                  <div class="stat-icon">{icon}</div>
                  <div class="stat-value">{val}</div>
                  <div class="stat-label">{lbl}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
