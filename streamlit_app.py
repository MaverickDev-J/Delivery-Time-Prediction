"""
DeliverIQ Demo Console — Streamlit Web UI.
=========================================
Thin client interacting with DeliverIQ microservices:
  - Saga Orchestrator (Port 8004)
  - ML Inference / ETA (Port 8000)
  - ML Monitoring (Port 8006)
  - Observability / Grafana & Prometheus (Ports 3000 & 9090)
"""

import os
import uuid

import folium
import httpx
import streamlit as st
from streamlit_folium import st_folium

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DeliverIQ Console",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #0d0f1a; color: #e0e4f0; }
#MainMenu, footer, header { visibility: hidden; }

.hero-banner {
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%);
    border-radius: 16px;
    padding: 24px 32px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 18px;
}
.hero-title { color: #fff; font-size: 1.8rem; font-weight: 900; margin: 0; line-height: 1.1; }
.hero-sub   { color: rgba(255,255,255,0.85); font-size: 0.9rem; margin: 4px 0 0 0; }
.hero-badge {
    margin-left: auto;
    background: rgba(255,255,255,0.18);
    border: 1px solid rgba(255,255,255,0.35);
    border-radius: 20px;
    padding: 6px 16px;
    color: white;
    font-size: 0.8rem;
    font-weight: 700;
}

.metric-card {
    background: #161928;
    border: 1px solid #252840;
    border-radius: 12px;
    padding: 16px 20px;
    text-align: center;
}
.metric-val { font-size: 2rem; font-weight: 900; color: #818cf8; }
.metric-lbl { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }

.step-card {
    background: #161928;
    border-radius: 10px;
    border-left: 4px solid #6366f1;
    padding: 12px 16px;
    margin-bottom: 8px;
}
.step-success { border-left-color: #10b981; }
.step-failed  { border-left-color: #ef4444; }
.step-degraded { border-left-color: #f59e0b; }

div[data-testid="stButton"] > button {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    color: white !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 10px 24px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ── Service URL Configuration ────────────────────────────────────────────────
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8004")
ETA_URL = os.getenv("ETA_URL", "http://localhost:8000")
MONITORING_URL = os.getenv("MONITORING_URL", "http://localhost:8006")
ORDER_URL = os.getenv("ORDER_URL", "http://localhost:8001")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:8002")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:8003")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚡ **DeliverIQ Platform**")
    st.caption("Event-Driven Saga & ML Observability")

    st.markdown("---")
    st.markdown("#### 🔗 **Service Mesh Status**")

    def check_service(url, name):
        try:
            r = httpx.get(f"{url}/health", timeout=1.0)
            if r.status_code == 200:
                st.success(f"🟢 **{name}** (UP)")
            else:
                st.warning(f"🟡 **{name}** ({r.status_code})")
        except Exception:
            st.error(f"🔴 **{name}** (Offline)")

    check_service(ORCHESTRATOR_URL, "Saga Orchestrator")
    check_service(ETA_URL, "ETA Inference")
    check_service(MONITORING_URL, "ML Monitoring")
    check_service(ORDER_URL, "Order Service")
    check_service(PAYMENT_URL, "Payment Service")
    check_service(INVENTORY_URL, "Inventory Service")

    st.markdown("---")
    st.markdown("#### 📊 **Dashboards**")
    st.markdown(f"[📈 Open Grafana]({GRAFANA_URL})", unsafe_allow_html=True)
    st.markdown(f"[🔍 Open Prometheus]({PROMETHEUS_URL})", unsafe_allow_html=True)


# ── Main Header ──────────────────────────────────────────────────────────────
st.markdown(
    """
<div class="hero-banner">
    <div>
        <h1 class="hero-title">DeliverIQ Control Center</h1>
        <p class="hero-sub">Distributed Saga Transactions • ML Inference • Closed-Loop Drift & Retraining</p>
    </div>
    <div class="hero-badge">v1.0 • Live Architecture</div>
</div>
""",
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4 = st.tabs([
    "🛵 Place Order & Saga",
    "📜 Saga Audit Logs",
    "📊 ML Monitoring & Drift",
    "🏥 System Observability",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: Place Order & Saga
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    col_map, col_form = st.columns([3, 2], gap="medium")

    with col_form:
        st.markdown("### 📦 **Order Parameters**")
        order_amount = st.number_input("Total Amount (₹)", min_value=50.0, max_value=20000.0, value=450.0, step=50.0)
        items_selected = st.multiselect(
            "Order Items",
            options=[f"ITEM-{i}" for i in range(1, 21)],
            default=["ITEM-1", "ITEM-2"],
        )
        weather = st.selectbox("Weather Conditions", ["sunny", "cloudy", "windy", "fog", "stormy"], index=0)
        traffic = st.selectbox("Road Traffic Density", ["low", "medium", "high", "jam"], index=1)
        vehicle = st.selectbox("Vehicle Type", ["motorcycle", "scooter", "electric_scooter", "bicycle"], index=0)
        rider_age = st.slider("Rider Age", 18, 50, 28)
        rider_rating = st.slider("Rider Rating", 1.0, 5.0, 4.6, step=0.1)

        place_btn = st.button("🚀 Place Order via Saga", use_container_width=True)

    with col_map:
        st.markdown("### 🗺️ **Interactive Route Selection**")
        st.caption("Click on the map to set restaurant (green) & delivery (red) locations.")

        # Default Bengaluru coordinates
        rest_lat, rest_lon = 12.9716, 77.5946
        deliv_lat, deliv_lon = 12.9352, 77.6245

        m = folium.Map(location=[12.95, 77.60], zoom_start=12, tiles="CartoDB dark_matter")
        folium.Marker([rest_lat, rest_lon], tooltip="Restaurant", icon=folium.Icon(color="green", icon="cutlery")).add_to(m)
        folium.Marker([deliv_lat, deliv_lon], tooltip="Customer Location", icon=folium.Icon(color="red", icon="home")).add_to(m)
        folium.PolyLine([(rest_lat, rest_lon), (deliv_lat, deliv_lon)], color="#6366f1", weight=3, dash_array="6").add_to(m)

        st_folium(m, height=340, width=None)

    # ── Order Submission & Saga Execution ────────────────────────────────────
    if place_btn:
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

        st.markdown("---")
        st.markdown(f"### ⚡ **Executing Saga for `{order_id}`**")

        order_data = {
            "delivery_person_age": rider_age,
            "delivery_person_ratings": rider_rating,
            "restaurant_latitude": rest_lat,
            "restaurant_longitude": rest_lon,
            "delivery_location_latitude": deliv_lat,
            "delivery_location_longitude": deliv_lon,
            "order_date": "2026-08-18",
            "time_order_picked": "19:30:00",
            "weather_conditions": weather,
            "road_traffic_density": traffic,
            "vehicle_condition": 2,
            "type_of_order": "meal",
            "type_of_vehicle": vehicle,
            "city": "Metropolitian",
        }

        with st.spinner("Executing distributed saga transactions..."):
            try:
                response = httpx.post(
                    f"{ORCHESTRATOR_URL}/saga/start",
                    json={
                        "order_id": order_id,
                        "items": items_selected or ["ITEM-1"],
                        "total_amount": order_amount,
                        "order_data": order_data,
                    },
                    timeout=10.0,
                )

                if response.status_code == 200:
                    result = response.json()
                    final_state = result.get("final_state", "UNKNOWN")

                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.metric("Final State", final_state)
                    with c2:
                        eta_val = result.get("eta_minutes")
                        st.metric("Predicted ETA", f"{eta_val:.1f} min" if eta_val else "N/A")
                    with c3:
                        st.metric("Payment ID", result.get("payment_id") or "N/A")
                    with c4:
                        st.metric("Reservation ID", result.get("reservation_id") or "N/A")

                    if final_state == "CONFIRMED":
                        st.success(f"🎉 Order **{order_id}** successfully confirmed! Payment authorized, stock reserved, and ETA computed.")
                    elif final_state == "CONFIRMED_DEGRADED":
                        st.warning(f"⚠️ Order **{order_id}** confirmed in degraded mode using heuristic fallback.")
                    elif final_state == "CANCELLED":
                        st.error(f"❌ Order **{order_id}** cancelled and compensated. Reason: {result.get('error_reason')}")

                else:
                    st.error(f"Orchestrator returned error {response.status_code}: {response.text}")

            except Exception as e:
                st.error(f"Failed to communicate with Saga Orchestrator: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: Saga Audit Logs
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown("### 🔍 **Query Saga Lifecycle**")
    lookup_id = st.text_input("Enter Order ID (e.g. ORD-1234ABCD)", value="")

    if st.button("Fetch Saga State"):
        if lookup_id:
            try:
                resp = httpx.get(f"{ORCHESTRATOR_URL}/saga/{lookup_id.strip()}", timeout=5.0)
                if resp.status_code == 200:
                    saga_info = resp.json()
                    st.json(saga_info)
                else:
                    st.warning(f"No saga instance found for `{lookup_id}`")
            except Exception as e:
                st.error(f"Error connecting to orchestrator: {e}")
        else:
            st.info("Please enter an Order ID.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: ML Monitoring & Drift
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown("### 📈 **Closed-Loop ML Monitoring**")
    st.caption("Tracks prediction distributions, label lag, feature drift (PSI), and automated retrain gates.")

    col_btn1, col_btn2 = st.columns([1, 1])
    with col_btn1:
        eval_gate_btn = st.button("⚖️ Evaluate Retrain Gate", use_container_width=True)
    with col_btn2:
        refresh_mon_btn = st.button("🔄 Refresh Metrics", use_container_width=True)

    if eval_gate_btn:
        try:
            resp = httpx.post(f"{MONITORING_URL}/monitoring/evaluate-gate", timeout=5.0)
            if resp.status_code == 200:
                gate_res = resp.json()
                if gate_res.get("triggered"):
                    st.error(f"🚨 **Retrain Gate Triggered!** Reason: {gate_res.get('reason')}")
                else:
                    st.info(f"🛡️ **Retrain Gate Suppressed:** {gate_res.get('reason')}")
        except Exception as e:
            st.error(f"Failed to trigger retrain gate evaluation: {e}")

    try:
        perf_resp = httpx.get(f"{MONITORING_URL}/monitoring/performance", timeout=3.0)
        if perf_resp.status_code == 200:
            perf = perf_resp.json()
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.markdown(f'<div class="metric-card"><div class="metric-val">{perf.get("mae", 0.0):.2f}m</div><div class="metric-lbl">Rolling MAE</div></div>', unsafe_allow_html=True)
            with m2:
                st.markdown(f'<div class="metric-card"><div class="metric-val">{perf.get("late_rate", 0.0)*100:.1f}%</div><div class="metric-lbl">Late Delivery Rate</div></div>', unsafe_allow_html=True)
            with m3:
                st.markdown(f'<div class="metric-card"><div class="metric-val">{perf.get("interval_coverage", 0.0)*100:.1f}%</div><div class="metric-lbl">Interval Coverage</div></div>', unsafe_allow_html=True)
            with m4:
                st.markdown(f'<div class="metric-card"><div class="metric-val">{perf.get("labelled_count", 0)}</div><div class="metric-lbl">Labelled Predictions</div></div>', unsafe_allow_html=True)
    except Exception:
        st.caption("Monitoring performance metrics currently unavailable.")

    st.markdown("---")
    st.markdown("#### 🔬 **Recent Drift Reports (PSI)**")
    try:
        drift_resp = httpx.get(f"{MONITORING_URL}/monitoring/drift-report", timeout=3.0)
        if drift_resp.status_code == 200:
            reports = drift_resp.json().get("reports", [])
            if reports:
                st.table(reports)
            else:
                st.info("No drift reports recorded yet. Run the drift injector or traffic simulator to generate reports.")
    except Exception:
        st.info("Monitoring service offline or no reports available.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4: System Observability
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.markdown("### 🏥 **Observability Architecture**")
    st.markdown(
        """
        DeliverIQ is instrumented with **Prometheus Metrics** and **Grafana Dashboards**:
        - **Prometheus** scrapes `/metrics` across all microservices every 15s.
        - **Grafana** provisions real-time dashboards for latency percentiles, saga success/compensation rates, and ML drift.
        """
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 📊 **System Overview Dashboard**")
        st.write("- Request rates per service (req/s)")
        st.write("- P50 / P95 / P99 HTTP latency histograms")
        st.write("- Saga transaction outcomes & compensations")
        st.write("- Outbox lag & DLQ depth")
        st.link_button("Open System Dashboard", f"{GRAFANA_URL}/d/deliveriq-system", use_container_width=True)

    with c2:
        st.markdown("#### 📈 **ML Monitoring Dashboard**")
        st.write("- Rolling MAE (min) & Late-delivery %")
        st.write("- Prediction interval coverage (90% SLO)")
        st.write("- PSI Drift scores per feature")
        st.write("- Retrain gate evaluations & suppressions")
        st.link_button("Open ML Dashboard", f"{GRAFANA_URL}/d/deliveriq-ml", use_container_width=True)
