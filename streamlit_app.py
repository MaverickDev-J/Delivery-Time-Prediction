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
from datetime import datetime

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

.location-badge {
    background: #1e2235;
    border: 1px solid #303558;
    border-radius: 8px;
    padding: 8px 14px;
    margin: 4px 0;
    font-size: 0.85rem;
}
.location-badge-green { border-left: 4px solid #10b981; }
.location-badge-red   { border-left: 4px solid #ef4444; }
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

# ── Cached Health Checks (avoids re-calling on every rerun) ──────────────────
@st.cache_data(ttl=30, show_spinner=False)
def _check_all_services():
    """Check all services once and cache for 30 seconds."""
    services = [
        (ORCHESTRATOR_URL, "Saga Orchestrator"),
        (ETA_URL, "ETA Inference"),
        (MONITORING_URL, "ML Monitoring"),
        (ORDER_URL, "Order Service"),
        (PAYMENT_URL, "Payment Service"),
        (INVENTORY_URL, "Inventory Service"),
    ]
    results = []
    for url, name in services:
        try:
            r = httpx.get(f"{url}/health", timeout=2.0)
            if r.status_code == 200:
                results.append((name, "up"))
            else:
                results.append((name, "warn"))
        except Exception:
            results.append((name, "down"))
    return results

# ── Session State Initialization ─────────────────────────────────────────────
# Default Bengaluru coordinates
if "rest_lat" not in st.session_state:
    st.session_state.rest_lat = 12.9716
if "rest_lon" not in st.session_state:
    st.session_state.rest_lon = 77.5946
if "deliv_lat" not in st.session_state:
    st.session_state.deliv_lat = 12.9352
if "deliv_lon" not in st.session_state:
    st.session_state.deliv_lon = 77.6245
if "next_click" not in st.session_state:
    st.session_state.next_click = "restaurant"  # alternates: restaurant → delivery → restaurant ...
if "saga_result" not in st.session_state:
    st.session_state.saga_result = None

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚡ **DeliverIQ Platform**")
    st.caption("Event-Driven Saga & ML Observability")

    st.markdown("---")
    st.markdown("#### 🔗 **Service Mesh Status**")

    service_statuses = _check_all_services()
    for name, status in service_statuses:
        if status == "up":
            st.success(f"🟢 **{name}** (UP)")
        elif status == "warn":
            st.warning(f"🟡 **{name}** (Degraded)")
        else:
            st.error(f"🔴 **{name}** (Offline)")

    if st.button("🔄 Refresh Status", use_container_width=True, key="refresh_health"):
        _check_all_services.clear()
        st.rerun()

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
        st.caption(
            "**How to use:** Click on the map to set locations. "
            "Clicks alternate between 🟢 Restaurant and 🔴 Delivery."
        )

        # Show current coordinates
        next_label = "🟢 Restaurant" if st.session_state.next_click == "restaurant" else "🔴 Delivery"
        st.info(f"**Next click sets:** {next_label} location")

        col_loc1, col_loc2 = st.columns(2)
        with col_loc1:
            st.markdown(
                f'<div class="location-badge location-badge-green">'
                f'🟢 Restaurant: {st.session_state.rest_lat:.4f}, {st.session_state.rest_lon:.4f}</div>',
                unsafe_allow_html=True,
            )
        with col_loc2:
            st.markdown(
                f'<div class="location-badge location-badge-red">'
                f'🔴 Delivery: {st.session_state.deliv_lat:.4f}, {st.session_state.deliv_lon:.4f}</div>',
                unsafe_allow_html=True,
            )

        # Reset button
        if st.button("🔄 Reset to Default (Bengaluru)", key="reset_map"):
            st.session_state.rest_lat = 12.9716
            st.session_state.rest_lon = 77.5946
            st.session_state.deliv_lat = 12.9352
            st.session_state.deliv_lon = 77.6245
            st.session_state.next_click = "restaurant"
            st.rerun()

        # Build map with current locations
        center_lat = (st.session_state.rest_lat + st.session_state.deliv_lat) / 2
        center_lon = (st.session_state.rest_lon + st.session_state.deliv_lon) / 2

        m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="CartoDB dark_matter")
        folium.Marker(
            [st.session_state.rest_lat, st.session_state.rest_lon],
            tooltip="🟢 Restaurant (click map to change)",
            icon=folium.Icon(color="green", icon="cutlery"),
        ).add_to(m)
        folium.Marker(
            [st.session_state.deliv_lat, st.session_state.deliv_lon],
            tooltip="🔴 Customer Location (click map to change)",
            icon=folium.Icon(color="red", icon="home"),
        ).add_to(m)
        folium.PolyLine(
            [(st.session_state.rest_lat, st.session_state.rest_lon),
             (st.session_state.deliv_lat, st.session_state.deliv_lon)],
            color="#6366f1", weight=3, dash_array="6",
        ).add_to(m)

        # Render map and capture click data
        map_data = st_folium(m, height=340, width=None, key="main_map")

        # Process map click
        if map_data and map_data.get("last_clicked"):
            clicked_lat = map_data["last_clicked"]["lat"]
            clicked_lon = map_data["last_clicked"]["lng"]

            if st.session_state.next_click == "restaurant":
                # Only update if location actually changed
                if (abs(clicked_lat - st.session_state.rest_lat) > 0.0001
                        or abs(clicked_lon - st.session_state.rest_lon) > 0.0001):
                    st.session_state.rest_lat = clicked_lat
                    st.session_state.rest_lon = clicked_lon
                    st.session_state.next_click = "delivery"
                    st.rerun()
            else:
                if (abs(clicked_lat - st.session_state.deliv_lat) > 0.0001
                        or abs(clicked_lon - st.session_state.deliv_lon) > 0.0001):
                    st.session_state.deliv_lat = clicked_lat
                    st.session_state.deliv_lon = clicked_lon
                    st.session_state.next_click = "restaurant"
                    st.rerun()

    # ── Order Submission & Saga Execution ────────────────────────────────────
    if place_btn:
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

        st.markdown("---")
        st.markdown(f"### ⚡ **Executing Saga for `{order_id}`**")

        order_data = {
            "delivery_person_age": rider_age,
            "delivery_person_ratings": rider_rating,
            "restaurant_latitude": st.session_state.rest_lat,
            "restaurant_longitude": st.session_state.rest_lon,
            "delivery_location_latitude": st.session_state.deliv_lat,
            "delivery_location_longitude": st.session_state.deliv_lon,
            "order_date": datetime.now().strftime("%Y-%m-%d"),
            "time_order_picked": datetime.now().strftime("%H:%M:%S"),
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
                    st.session_state.saga_result = result
                    st.session_state.saga_result["_order_id"] = order_id
                    final_state = result.get("state", "UNKNOWN")

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

    # Show last saga result if available (persists across reruns)
    elif st.session_state.saga_result:
        result = st.session_state.saga_result
        order_id = result.get("_order_id", "N/A")
        final_state = result.get("state", "UNKNOWN")

        st.markdown("---")
        st.markdown(f"### 📋 **Last Saga Result** — `{order_id}`")

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
            st.success(f"🎉 Order **{order_id}** confirmed!")
        elif final_state == "CONFIRMED_DEGRADED":
            st.warning(f"⚠️ Order **{order_id}** confirmed (degraded mode).")
        elif final_state == "CANCELLED":
            st.error(f"❌ Order **{order_id}** cancelled. Reason: {result.get('error_reason')}")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: Saga Audit Logs
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown("### 🔍 **Query Saga Lifecycle**")

    # Pre-fill with last order ID if available
    default_lookup = ""
    if st.session_state.saga_result:
        default_lookup = st.session_state.saga_result.get("_order_id", "")

    lookup_id = st.text_input("Enter Order ID (e.g. ORD-1234ABCD)", value=default_lookup)

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
