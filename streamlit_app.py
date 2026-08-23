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

import math

# ── Multi-City Restaurants & Delivery Neighborhoods ──────────────────────────
CITIES_DATA = {
    "Mumbai": {
        "center": (19.0760, 72.8777),
        "zoom": 13,
        "restaurants": {
            "Gajalee (Vile Parle)": {
                "lat": 19.1025, "lon": 72.8455, "cuisine": "Coastal Malvani & Seafood",
                "menu": {"Butter Garlic Jumbo Prawns": 460.0, "Bombil Fry": 310.0, "Neer Dosa with Fish Curry": 380.0, "Sol Kadhi": 70.0},
                "item_ids": {"Butter Garlic Jumbo Prawns": "ITEM-1", "Bombil Fry": "ITEM-2", "Neer Dosa with Fish Curry": "ITEM-3", "Sol Kadhi": "ITEM-4"},
            },
            "Bademiya (Colaba)": {
                "lat": 18.9220, "lon": 72.8332, "cuisine": "Mughlai & Iconic Kebabs",
                "menu": {"Chicken Tikka Roll": 220.0, "Mutton Seekh Kebab": 320.0, "Rumali Roti (2 pcs)": 60.0, "Chicken Baida Roti": 260.0},
                "item_ids": {"Chicken Tikka Roll": "ITEM-5", "Mutton Seekh Kebab": "ITEM-6", "Rumali Roti (2 pcs)": "ITEM-7", "Chicken Baida Roti": "ITEM-8"},
            },
            "Mahesh Lunch Home (Fort)": {
                "lat": 18.9324, "lon": 72.8351, "cuisine": "Mangalorean Seafood & Ghee Roast",
                "menu": {"Prawns Ghee Roast": 440.0, "Surmai Fish Fry": 390.0, "Appam (2 pcs)": 80.0, "Crab Masala": 520.0},
                "item_ids": {"Prawns Ghee Roast": "ITEM-9", "Surmai Fish Fry": "ITEM-10", "Appam (2 pcs)": "ITEM-11", "Crab Masala": "ITEM-12"},
            },
            "Kyani & Co. (Marine Lines)": {
                "lat": 18.9432, "lon": 72.8273, "cuisine": "Heritage Irani Cafe & Bakery",
                "menu": {"Bun Maska with Irani Chai": 90.0, "Chicken Kheema Pav": 180.0, "Mutton Pattice (2 pcs)": 120.0, "Mawa Cake": 60.0},
                "item_ids": {"Bun Maska with Irani Chai": "ITEM-13", "Chicken Kheema Pav": "ITEM-14", "Mutton Pattice (2 pcs)": "ITEM-15", "Mawa Cake": "ITEM-16"},
            },
            "Britannia & Co. (Ballard Estate)": {
                "lat": 18.9345, "lon": 72.8390, "cuisine": "Parsi & Irani Heritage",
                "menu": {"Berry Pulao (Chicken)": 390.0, "Mutton Dhansak": 420.0, "Sali Boti": 350.0, "Caramel Custard": 140.0},
                "item_ids": {"Berry Pulao (Chicken)": "ITEM-17", "Mutton Dhansak": "ITEM-18", "Sali Boti": "ITEM-19", "Caramel Custard": "ITEM-20"},
            },
        },
        "neighborhoods": {
            "Powai (Hiranandani Gardens)": (19.1197, 72.9051),
            "Bandra West (Pali Hill)": (19.0607, 72.8362),
            "Andheri East (MIDC)": (19.1197, 72.8697),
            "Colaba Causeway": (18.9150, 72.8258),
            "Juhu Beach Area": (19.0988, 72.8264),
        },
    },
    "Bengaluru": {
        "center": (12.9716, 77.5946),
        "zoom": 13,
        "restaurants": {
            "Meghana Foods (Koramangala)": {
                "lat": 12.9352, "lon": 77.6245, "cuisine": "Biryani & Andhra Special",
                "menu": {"Special Chicken Biryani": 340.0, "Paneer 65": 240.0, "Boneless Chicken 65": 290.0, "Gulab Jamun (2 pcs)": 80.0},
                "item_ids": {"Special Chicken Biryani": "ITEM-1", "Paneer 65": "ITEM-2", "Boneless Chicken 65": "ITEM-3", "Gulab Jamun (2 pcs)": "ITEM-4"},
            },
            "Truffles (Indiranagar)": {
                "lat": 12.9784, "lon": 77.6408, "cuisine": "Burgers, Pastas & Shakes",
                "menu": {"All American Cheese Burger": 280.0, "Peri Peri Chicken Pasta": 310.0, "Garlic Bread with Cheese": 140.0, "Belgian Chocolate Shake": 180.0},
                "item_ids": {"All American Cheese Burger": "ITEM-5", "Peri Peri Chicken Pasta": "ITEM-6", "Garlic Bread with Cheese": "ITEM-7", "Belgian Chocolate Shake": "ITEM-8"},
            },
            "Empire Restaurant (Church Street)": {
                "lat": 12.9756, "lon": 77.6066, "cuisine": "Kebabs, Shawarma & Mughlai",
                "menu": {"Empire Special Shawarma": 160.0, "Butter Chicken & Naan Combo": 320.0, "Ghee Rice with Dal": 190.0, "Coin Parotta (3 pcs)": 90.0},
                "item_ids": {"Empire Special Shawarma": "ITEM-9", "Butter Chicken & Naan Combo": "ITEM-10", "Ghee Rice with Dal": "ITEM-11", "Coin Parotta (3 pcs)": "ITEM-12"},
            },
            "CTR Shri Sagar (Malleshwaram)": {
                "lat": 13.0031, "lon": 77.5702, "cuisine": "South Indian & Filter Coffee",
                "menu": {"Benne Masala Dosa": 110.0, "Maddur Vada (2 pcs)": 70.0, "Poori Saagu": 90.0, "Degree Filter Coffee": 40.0},
                "item_ids": {"Benne Masala Dosa": "ITEM-13", "Maddur Vada (2 pcs)": "ITEM-14", "Poori Saagu": "ITEM-15", "Degree Filter Coffee": "ITEM-16"},
            },
        },
        "neighborhoods": {
            "HSR Layout Sector 4": (12.9116, 77.6389),
            "Koramangala 4th Block": (12.9344, 77.6288),
            "Indiranagar 100ft Road": (12.9719, 77.6412),
            "BTM Layout 2nd Stage": (12.9166, 77.6101),
            "Whitefield Tech Park": (12.9698, 77.7500),
        },
    },
    "Delhi NCR": {
        "center": (28.6139, 77.2090),
        "zoom": 12,
        "restaurants": {
            "Karim's (Old Delhi / Jama Masjid)": {
                "lat": 28.6507, "lon": 77.2334, "cuisine": "Royal Mughlai & Kebabs",
                "menu": {"Mutton Korma": 360.0, "Chicken Jahangiri": 380.0, "Seekh Kebab (4 pcs)": 280.0, "Khamiri Roti (2 pcs)": 70.0},
                "item_ids": {"Mutton Korma": "ITEM-1", "Chicken Jahangiri": "ITEM-2", "Seekh Kebab (4 pcs)": "ITEM-3", "Khamiri Roti (2 pcs)": "ITEM-4"},
            },
            "Gulati Restaurant (Pandara Road)": {
                "lat": 28.6080, "lon": 77.2346, "cuisine": "North Indian & Butter Chicken",
                "menu": {"Famous Butter Chicken": 440.0, "Dal Makhani": 310.0, "Paneer Lababdar": 340.0, "Garlic Naan": 85.0},
                "item_ids": {"Famous Butter Chicken": "ITEM-5", "Dal Makhani": "ITEM-6", "Paneer Lababdar": "ITEM-7", "Garlic Naan": "ITEM-8"},
            },
            "Saravana Bhavan (Connaught Place)": {
                "lat": 28.6315, "lon": 77.2197, "cuisine": "South Indian Vegetarian",
                "menu": {"Special Masala Dosa": 160.0, "Idli Vada Combo": 130.0, "Mini Tiffin Platter": 210.0, "Madras Filter Coffee": 60.0},
                "item_ids": {"Special Masala Dosa": "ITEM-9", "Idli Vada Combo": "ITEM-10", "Mini Tiffin Platter": "ITEM-11", "Madras Filter Coffee": "ITEM-12"},
            },
        },
        "neighborhoods": {
            "Connaught Place (CP)": (28.6315, 77.2197),
            "Hauz Khas Village": (28.5535, 77.1944),
            "Cyber City (Gurgaon)": (28.4950, 77.0895),
            "Noida Sector 18": (28.5708, 77.3271),
            "South Extension": (28.5728, 77.2215),
        },
    },
    "Hyderabad": {
        "center": (17.3850, 78.4867),
        "zoom": 13,
        "restaurants": {
            "Paradise Biryani (Secunderabad)": {
                "lat": 17.4411, "lon": 78.4983, "cuisine": "World Famous Hyderabadi Dum Biryani",
                "menu": {"Royal Mutton Biryani": 380.0, "Special Chicken Biryani": 340.0, "Chicken 65": 260.0, "Double Ka Meetha": 90.0},
                "item_ids": {"Royal Mutton Biryani": "ITEM-1", "Special Chicken Biryani": "ITEM-2", "Chicken 65": "ITEM-3", "Double Ka Meetha": "ITEM-4"},
            },
            "Shah Ghouse (Tolichowki)": {
                "lat": 17.3998, "lon": 78.4116, "cuisine": "Hyderabadi Haleem & Biryani",
                "menu": {"Special Mutton Haleem": 260.0, "Boti Kebab": 290.0, "Tala Hua Gosht": 320.0, "Khabsa Rice Platter": 410.0},
                "item_ids": {"Special Mutton Haleem": "ITEM-5", "Boti Kebab": "ITEM-6", "Tala Hua Gosht": "ITEM-7", "Khabsa Rice Platter": "ITEM-8"},
            },
            "Chutneys (Banjara Hills)": {
                "lat": 17.4168, "lon": 78.4382, "cuisine": "South Indian & 7 Chutneys",
                "menu": {"Babai Ghee Idli (4 pcs)": 150.0, "Steam Dosa": 160.0, "MLA Pesarattu": 180.0, "Guntur Upma Dosa": 170.0},
                "item_ids": {"Babai Ghee Idli (4 pcs)": "ITEM-9", "Steam Dosa": "ITEM-10", "MLA Pesarattu": "ITEM-11", "Guntur Upma Dosa": "ITEM-12"},
            },
        },
        "neighborhoods": {
            "Hitec City / Madhapur": (17.4483, 78.3741),
            "Banjara Hills Road No 1": (17.4156, 78.4487),
            "Gachibowli Financial Dist": (17.4401, 78.3489),
            "Jubilee Hills Checkpost": (17.4325, 78.4071),
            "Charminar Old City": (17.3616, 78.4747),
        },
    },
}


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate geodesic distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


@st.cache_data(ttl=3600, show_spinner=False)
def get_road_route(lat1, lon1, lat2, lon2):
    """
    Fetch turn-by-turn road driving route from Open Source Routing Machine (OSRM).
    Returns real street polyline and road driving distance.
    Falls back to straight-line Haversine if offline/timeout.
    """
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        r = httpx.get(url, timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            if data.get("routes"):
                route = data["routes"][0]
                # OSRM coordinates are [lon, lat] -> convert to [lat, lon] for Folium
                coords = [[pt[1], pt[0]] for pt in route["geometry"]["coordinates"]]
                distance_km = round(route["distance"] / 1000.0, 2)
                return coords, distance_km, True
    except Exception:
        pass

    # Fallback to straight-line Haversine
    dist = haversine_km(lat1, lon1, lat2, lon2)
    return [(lat1, lon1), (lat2, lon2)], dist, False


# ── Session State Initialization ─────────────────────────────────────────────
if "selected_city" not in st.session_state:
    st.session_state.selected_city = "Mumbai"
if "last_city" not in st.session_state:
    st.session_state.last_city = "Mumbai"
if "selected_restaurant" not in st.session_state:
    st.session_state.selected_restaurant = "Gajalee (Vile Parle)"
if "deliv_lat" not in st.session_state:
    st.session_state.deliv_lat = 19.1197  # Powai
if "deliv_lon" not in st.session_state:
    st.session_state.deliv_lon = 72.9051
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
    st.markdown("[⚡ Open Ops Console](http://localhost:8008/ops/)", unsafe_allow_html=True)


# ── Main Header ──────────────────────────────────────────────────────────────
st.markdown(
    """
<div class="hero-banner">
    <div>
        <h1 class="hero-title">DeliverIQ Control Center</h1>
        <p class="hero-sub">Distributed Saga Transactions • Multi-City ML Inference • Resilient Architecture</p>
    </div>
    <div class="hero-badge">v1.0 • Live Architecture</div>
</div>
""",
    unsafe_allow_html=True,
)

tab1, tab2, tab3 = st.tabs([
    "🛵 Place Order & Saga",
    "📜 Saga Audit Logs",
    "🏥 System Observability",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: Place Order & Saga
# ─────────────────────────────────────────────────────────────────────────────

with tab1:
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        st.markdown("### 🗺️ **Multi-City Route Planner**")

        # 1. City Selector
        col_city, col_rest = st.columns([1, 2])
        with col_city:
            chosen_city = st.selectbox("🏙️ **Select City**", options=list(CITIES_DATA.keys()), index=list(CITIES_DATA.keys()).index(st.session_state.selected_city), key="city_selector")
        
        city_info = CITIES_DATA[chosen_city]
        
        # If city changed, reset defaults to this city
        if chosen_city != st.session_state.last_city:
            st.session_state.selected_city = chosen_city
            st.session_state.last_city = chosen_city
            first_rest = list(city_info["restaurants"].keys())[0]
            st.session_state.selected_restaurant = first_rest
            first_hood_coords = list(city_info["neighborhoods"].values())[0]
            st.session_state.deliv_lat = first_hood_coords[0]
            st.session_state.deliv_lon = first_hood_coords[1]
            st.rerun()

        # 2. Fixed Restaurant Selector within chosen city
        with col_rest:
            chosen_rest_name = st.selectbox(
                "🏨 **Select Restaurant (Fixed Location & Menu)**",
                options=list(city_info["restaurants"].keys()),
                index=list(city_info["restaurants"].keys()).index(st.session_state.selected_restaurant) if st.session_state.selected_restaurant in city_info["restaurants"] else 0,
                key="rest_selector",
            )
        
        st.session_state.selected_restaurant = chosen_rest_name
        rest_info = city_info["restaurants"][chosen_rest_name]
        rest_lat, rest_lon = rest_info["lat"], rest_info["lon"]

        # 3. Delivery Drop Location Selector (Quick area or custom map click)
        col_drop, col_quick = st.columns([2, 1])
        with col_drop:
            st.caption("📍 **Delivery Destination**: Click anywhere on map or choose preset")
        with col_quick:
            preset_area = st.selectbox("Quick Areas", ["(Custom Map Pin)"] + list(city_info["neighborhoods"].keys()), index=0, key="preset_picker")
            if preset_area != "(Custom Map Pin)":
                n_lat, n_lon = city_info["neighborhoods"][preset_area]
                st.session_state.deliv_lat = n_lat
                st.session_state.deliv_lon = n_lon

        # Road navigation & distance calculation
        route_coords, distance, is_road = get_road_route(rest_lat, rest_lon, st.session_state.deliv_lat, st.session_state.deliv_lon)
        route_label = "🚗 Road Distance" if is_road else "📏 Direct Distance"

        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            st.markdown(f'<div class="location-badge location-badge-green">🏨 <strong>{chosen_rest_name.split("(")[0]}</strong><br><span style="font-size:0.75rem; color:#94a3b8;">{rest_info["cuisine"]}</span></div>', unsafe_allow_html=True)
        with col_b2:
            st.markdown(f'<div class="location-badge location-badge-red">🏠 <strong>Delivery Destination</strong><br><span style="font-size:0.75rem; color:#94a3b8;">{st.session_state.deliv_lat:.4f}, {st.session_state.deliv_lon:.4f}</span></div>', unsafe_allow_html=True)
        with col_b3:
            st.markdown(f'<div class="location-badge" style="border-left: 4px solid #6366f1;">{route_label}<br><span style="font-size:1.05rem; font-weight:800; color:#818cf8;">{distance} km</span></div>', unsafe_allow_html=True)

        # Build Interactive Map centered on the route
        center_lat = (rest_lat + st.session_state.deliv_lat) / 2
        center_lon = (rest_lon + st.session_state.deliv_lon) / 2

        m = folium.Map(location=[center_lat, center_lon], zoom_start=city_info["zoom"], tiles="CartoDB dark_matter")
        folium.Marker(
            [rest_lat, rest_lon],
            tooltip=f"🟢 {chosen_rest_name}",
            icon=folium.Icon(color="green", icon="cutlery"),
        ).add_to(m)
        folium.Marker(
            [st.session_state.deliv_lat, st.session_state.deliv_lon],
            tooltip="🔴 Delivery Drop Location (Click map to change)",
            icon=folium.Icon(color="red", icon="home"),
        ).add_to(m)
        folium.PolyLine(
            route_coords,
            color="#6366f1", weight=5, opacity=0.85,
            tooltip=f"Driving Route: {distance} km",
        ).add_to(m)

        map_data = st_folium(m, height=320, width=None, key=f"delivery_map_{chosen_city}")

        # Capture click to update delivery location with full freedom
        if map_data and map_data.get("last_clicked"):
            c_lat = map_data["last_clicked"]["lat"]
            c_lon = map_data["last_clicked"]["lng"]
            if abs(c_lat - st.session_state.deliv_lat) > 0.0005 or abs(c_lon - st.session_state.deliv_lon) > 0.0005:
                st.session_state.deliv_lat = c_lat
                st.session_state.deliv_lon = c_lon
                st.rerun()

    with col_right:
        st.markdown(f"### 🍱 **Menu: {chosen_rest_name.split('(')[0]}**")
        st.caption("Select your dishes (Total bill auto-calculates):")

        # Real Dish Checkboxes & Price Calculation
        selected_dishes = []
        selected_item_ids = []
        total_amount = 0.0

        for dish, price in rest_info["menu"].items():
            checked = st.checkbox(f"{dish} — **₹{price:.0f}**", value=(dish == list(rest_info["menu"].keys())[0]))
            if checked:
                selected_dishes.append(dish)
                selected_item_ids.append(rest_info["item_ids"][dish])
                total_amount += price

        if not selected_dishes:
            st.warning("Please select at least 1 dish.")
            total_amount = 99.0

        st.markdown(f"#### 💳 Total Bill: <span style='color:#10b981; font-weight:800;'>₹{total_amount:.2f}</span>", unsafe_allow_html=True)
        st.markdown(f"<div style='color:#94a3b8; font-size:0.85rem;'>Dishes selected: <strong>{len(selected_dishes)}</strong> ({', '.join(selected_dishes) if selected_dishes else 'None'})</div>", unsafe_allow_html=True)

    # ── Full-Width ML Trip Simulation Dashboard ──────────────────────────────
    st.markdown("---")
    st.markdown("### 🎛️ **Live ML Trip & Environmental Parameters**")
    st.caption("Adjust real-world conditions to see how the LightGBM model dynamically adapts its predicted delivery time:")

    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    with col_p1:
        st.markdown("##### 🌦️ **Atmosphere & Road**")
        weather = st.selectbox("Weather Condition", ["sunny", "cloudy", "windy", "fog", "stormy", "sandstorms"], index=0, key="sim_weather")
        traffic = st.selectbox("Traffic Density", ["low", "medium", "high", "jam"], index=1, key="sim_traffic")

    with col_p2:
        st.markdown("##### 👤 **Delivery Partner**")
        rider_age = st.slider("Rider Age", min_value=18, max_value=50, value=28, step=1, key="sim_age")
        rider_rating = st.slider("Rider Rating", min_value=1.0, max_value=5.0, value=4.7, step=0.1, key="sim_rating")

    with col_p3:
        st.markdown("##### 🛵 **Vehicle & Fleet**")
        vehicle = st.selectbox("Vehicle Type", ["motorcycle", "scooter", "electric_scooter", "bicycle"], index=0, key="sim_vehicle")
        vehicle_cond = st.select_slider("Vehicle Condition", options=[0, 1, 2, 3], value=2, format_func=lambda x: {0: "0 (Poor)", 1: "1 (Fair)", 2: "2 (Good)", 3: "3 (Excellent)"}[x], key="sim_veh_cond")

    with col_p4:
        st.markdown("##### 🎪 **Market & Context**")
        festival = st.selectbox(
            "Festival / Peak Rush",
            options=["no", "yes"],
            index=0,
            format_func=lambda x: "No (Normal Day)" if x == "no" else "Yes (Festival Surge)",
            key="sim_festival",
        )
        city_type = st.selectbox(
            "City Density",
            options=["metropolitan", "urban", "semi-urban"],
            index=0,
            format_func=lambda x: x.capitalize(),
            key="sim_city_type",
        )

    st.markdown("<br>", unsafe_allow_html=True)
    place_btn = st.button(f"🚀 Place Order (₹{total_amount:.0f}) via Saga", use_container_width=True, type="primary")

    # ── Order Submission & Saga Execution ────────────────────────────────────
    if place_btn:
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

        st.markdown("---")
        st.markdown(f"### ⚡ **Executing Distributed Saga for `{order_id}`**")

        order_data = {
            "order_id": order_id,
            "delivery_person_age": float(rider_age),
            "delivery_person_ratings": float(rider_rating),
            "restaurant_latitude": float(rest_lat),
            "restaurant_longitude": float(rest_lon),
            "delivery_location_latitude": float(st.session_state.deliv_lat),
            "delivery_location_longitude": float(st.session_state.deliv_lon),
            "order_date": datetime.now().strftime("%d-%m-%Y"),
            "time_order_picked": datetime.now().strftime("%H:%M:%S"),
            "weather_conditions": str(weather).lower(),
            "road_traffic_density": str(traffic).lower(),
            "vehicle_condition": int(vehicle_cond),
            "type_of_order": "meal",
            "type_of_vehicle": str(vehicle).lower(),
            "festival": str(festival).lower(),
            "city": city_type,
            "city_type": str(city_type).lower(),
        }

        with st.spinner("Coordinating Saga (Payment ➔ Inventory ➔ ML ETA Prediction ➔ Confirm)..."):
            try:
                response = httpx.post(
                    f"{ORCHESTRATOR_URL}/saga/start",
                    json={
                        "order_id": order_id,
                        "items": selected_item_ids or ["ITEM-1"],
                        "total_amount": total_amount,
                        "order_data": order_data,
                    },
                    timeout=10.0,
                )

                if response.status_code == 200:
                    result = response.json()
                    st.session_state.saga_result = result
                    st.session_state.saga_result["_order_id"] = order_id
                    st.session_state.saga_result["_dishes"] = selected_dishes
                    st.session_state.saga_result["_amount"] = total_amount
                    st.session_state.saga_result["_distance"] = distance
                    final_state = result.get("state", "UNKNOWN")

                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.metric("Saga Final State", final_state)
                    with c2:
                        eta_val = result.get("eta_minutes")
                        st.metric("Predicted Delivery Time", f"{eta_val:.1f} min" if eta_val else "N/A", delta=f"{distance} km trip")
                    with c3:
                        st.metric("Payment Gateway ID", result.get("payment_id") or "N/A")
                    with c4:
                        st.metric("Inventory Reservation", result.get("reservation_id") or "N/A")

                    if final_state == "CONFIRMED":
                        st.success(f"🎉 Order **{order_id}** Confirmed! Total **₹{total_amount:.2f}** charged, kitchen items reserved, and LightGBM predicted **{eta_val:.1f} mins** ETA.")
                    elif final_state == "CONFIRMED_DEGRADED":
                        st.warning(f"⚠️ Order **{order_id}** confirmed in degraded fallback mode.")
                    elif final_state == "CANCELLED":
                        st.error(f"❌ Order **{order_id}** Cancelled & Compensated. Reason: {result.get('error_reason')}")

                else:
                    st.error(f"Orchestrator returned error {response.status_code}: {response.text}")

            except Exception as e:
                st.error(f"Failed to communicate with Saga Orchestrator: {e}")

    elif st.session_state.saga_result:
        result = st.session_state.saga_result
        order_id = result.get("_order_id", "N/A")
        final_state = result.get("state", "UNKNOWN")

        st.markdown("---")
        st.markdown(f"### 📋 **Last Saga Summary** — `{order_id}`")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("State", final_state)
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
# TAB 3: System Observability & Metrics
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown("### 🏥 **Distributed Observability Architecture**")
    st.markdown(
        """
        DeliverIQ is instrumented with **Prometheus Metrics**, **Grafana Dashboards**, and an **Admin Ops Console**:
        - **Prometheus** scrapes `/metrics` across all microservices every 15s.
        - **Grafana** provisions real-time dashboards for latency percentiles, saga success/compensation rates, and error budgets.
        - **Ops Console** provides live inspection of saga state machines, transactional outbox tables, and chaos injection.
        """
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("#### 📊 **Grafana System Dashboard**")
        st.write("- P50 / P95 / P99 HTTP latency")
        st.write("- Saga success vs compensation rate")
        st.write("- Outbox lag & Redis Stream depth")
        st.link_button("Open Grafana", f"{GRAFANA_URL}/d/deliveriq-system", use_container_width=True)

    with c2:
        st.markdown("#### ⚡ **Admin Ops Console**")
        st.write("- Visual Saga Timeline Stepper")
        st.write("- 10-Second Idempotency Demo")
        st.write("- Live Redis Stream Event Feed")
        st.link_button("Open Ops Console", "http://localhost:8008/ops/", use_container_width=True)

    with c3:
        st.markdown("#### 🔍 **Prometheus Scraper**")
        st.write("- Live metric query explorer")
        st.write("- Raw histogram & counter values")
        st.write("- Target endpoint health statuses")
        st.link_button("Open Prometheus", f"{PROMETHEUS_URL}", use_container_width=True)
