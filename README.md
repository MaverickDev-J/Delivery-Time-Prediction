# ⚡ DeliverIQ — Distributed Delivery Intelligence & Resilient Microservices Mesh

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Redis Streams](https://img.shields.io/badge/Redis-Streams-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![LightGBM](https://img.shields.io/badge/ML%20Inference-LightGBM-brightgreen)](https://lightgbm.readthedocs.io)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)

An event-driven, fault-tolerant food delivery platform combining **Distributed Saga Orchestration**, **Transactional Outbox Event Streaming**, **Real-Time ML ETA Inference**, and an **Operational Chaos Engineering Control Plane**.

---

## 🏛️ System Architecture

```
                                  [ Streamlit Customer App ] (:8501)
                                              │
                     ┌────────────────────────┴────────────────────────┐
                     ▼                                                 ▼
          [ Order Service ] (:8001)                       [ Ops Console / Chaos UI ] (:8008)
           (Transactional Outbox)                                (HTMX + Jinja2 Control Plane)
                     │                                                 │
                     ▼ (Async Outbox Relay)                            │
            [ Redis Streams ] ◄────────────────────────────────────────┘
          (Event Bus & Consumers)
                     │
                     ▼
       [ Saga Orchestrator ] (:8004)
        (Distributed State Machine)
         │           │           │
         ▼           ▼           ▼
   [ Payment ]  [ Inventory ] [ ML ETA ]
    (:8002)       (:8003)      (:8000)
   (Idempotent   (Row-Locked  (LightGBM +
    + Chaos)      Flash Sale)  OSRM Roads)
```

---

## ✨ Core Engineering Capabilities

### 1. 🔄 Distributed Saga Orchestration (Compensating Transactions)
* Coordinates distributed multi-step checkouts across isolated database boundaries (`orders_db`, `payments_db`, `inventory_db`, `saga_db`).
* Automatically executes backward-compensating actions (e.g., instant payment refund if item stock exhausts mid-checkout).
* Guaranteed state persistence with full audit step-logging.

### 2. 🛡️ Transactional Outbox Pattern & Event Streaming
* Eliminates the distributed dual-write problem by recording domain events (`order.created`, `order.confirmed`, `order.cancelled`) atomically inside the database transaction.
* An asynchronous publisher polls the outbox and streams events to **Redis Streams** consumer groups with at-least-once delivery guarantees.

### 3. 🔒 IETF Idempotency & Concurrency Flash Sale Protection
* Cryptographic header hashing (`Idempotency-Key`) guarantees safe automated retries without duplicate credit card charges or duplicate stock decrements.
* Enforces PostgreSQL row-level pessimistic locking (`SELECT ... FOR UPDATE`) and database constraints (`CHECK stock >= 0`), proven via automated race-condition benchmarks with 20 parallel shoppers competing for 1 stock item.

### 4. 🧠 Real-Time ML ETA Inference & Road Navigation
* **LightGBM Pipeline:** Predicts hyper-accurate delivery times using dynamic weather, road traffic density, rider ratings/age, vehicle condition, and city characteristics.
* **Real Road Geometries:** Integrates OpenStreetMap / OSRM routing engine with live turn-by-turn road curves across Mumbai, Bengaluru, Delhi NCR, and Hyderabad.
* **Graceful Degradation:** Employs fallback heuristic models if the ML inference service experiences downtime, ensuring 100% checkout availability.

### 5. 💥 Operational Control Plane & Chaos Engineering
* **Admin Ops Console (FastAPI + HTMX):** Real-time monitoring of active saga instances, outbox queue health, and event feeds.
* **Live Chaos Injector:** Dynamically injects artificial payment latencies (0–5000ms), simulated 500 server errors, and 1-click system restore controls.
* **Visual Flash Sale Arena:** Demonstrates optimistic/pessimistic lock resolution live in the browser.

---

## 🌐 Microservices Mesh & Port Map

| Service | Port | Database | Primary Responsibility |
| :--- | :--- | :--- | :--- |
| **Customer App** | `8501` | — | Streamlit map UI, Multi-City selector, 4-col ML parameter controls |
| **Ops Console** | `8008` | `saga_db` | HTMX Admin dashboard, Chaos fault injector, Flash Sale arena |
| **Order Service** | `8001` | `orders_db` | Order intake, Transactional Outbox event publishing |
| **Payment Service** | `8002` | `payments_db` | Payment authorization, refunds, idempotency cache |
| **Inventory Service** | `8003` | `inventory_db` | Row-locked inventory reservation & atomic release |
| **Saga Orchestrator** | `8004` | `saga_db` | Distributed state machine execution & failure compensation |
| **ETA / ML Service** | `8000` | — | LightGBM inference engine & heuristic fallback |
| **Auth Service** | `8005` | `auth_db` | JWT issuance & role-based authentication |
| **Webhook Service** | `8009` | `webhook_db` | HMAC-SHA256 event subscription delivery |
| **Monitoring** | `8006` | `monitoring_db`| Redis stream consumer & system health aggregator |
| **PostgreSQL** | `5432` | *(Multi-DB)* | Database-per-service logical isolation |
| **Redis** | `6379` | — | Event streaming message broker & distributed cache |

---

## 🚀 Quickstart

### Prerequisites
* [Docker & Docker Compose](https://www.docker.com/)
* Python 3.12+ (managed with [`uv`](https://github.com/astral-sh/uv))

### 1. Launch the Microservices Mesh
```bash
# Clone the repository
git clone https://github.com/MaverickDev-J/Delivery-Time-Prediction.git
cd Delivery-Time-Prediction

# Start all microservices, databases, and message broker in Docker
docker compose -f ops/docker-compose.yml up -d --build
```

### 2. Launch the Customer App
```bash
# Install host dependencies and run Streamlit UI
uv sync
uv run streamlit run streamlit_app.py
```

### 3. Open the Interfaces
* 🍕 **Customer Food Delivery App:** [http://localhost:8501](http://localhost:8501)
* 🎛️ **Admin Ops & Chaos Console:** [http://localhost:8008/ops/dashboard](http://localhost:8008/ops/dashboard)
* ⚡ **Chaos Panel & Flash Sale Arena:** [http://localhost:8008/ops/chaos](http://localhost:8008/ops/chaos)

---

## 🧪 Testing & Verification

Run the comprehensive test suite covering unit tests, Saga compensations, and distributed concurrency race conditions:

```bash
# Run all unit and integration tests
uv run pytest -v

# Run the 20-User Flash Sale Concurrency Stress Benchmark
uv run pytest tests/test_inventory_concurrency.py -v -s
```

---

## 📂 Repository Structure

```text
├── contracts/               # Pydantic v2 schemas for all microservices
├── core/                    # Shared libraries (DB engines, Idempotency, Metrics, Logging, Outbox)
├── models/                  # Trained LightGBM artifacts & preprocessor pipelines
├── ops/                     # Docker Compose, Dockerfiles, and PostgreSQL init schemas
├── ops_console/             # FastAPI + Jinja2 + HTMX Admin & Chaos Control Plane
├── services/
│   ├── auth/                # JWT Authentication microservice
│   ├── inventory/           # Concurrency-safe inventory microservice
│   ├── order/               # Order lifecycle & Transactional Outbox service
│   ├── orchestrator/        # Distributed Saga State Machine & HTTP adapters
│   ├── payment/             # Payment Gateway simulator & Chaos engine
│   └── webhook/             # HMAC-signed webhook delivery service
├── streamlit_app.py         # Multi-city interactive map & ML control deck
└── tests/                   # Concurrency, Saga, Outbox, and Service test suite
```

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
