# 🛵 Swiggy Delivery Time Predictor

An ML-powered food delivery ETA (Estimated Time of Arrival) prediction system using a Stacking Regressor and an interactive map-based Streamlit UI.

[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-orange)](https://huggingface.co/spaces/Maverick006/delivery-time-prediction)

---

## 🚀 Live Demo
Check out the live interactive application on Hugging Face Spaces:
👉 **[Hugging Face Space Demo](https://huggingface.co/spaces/Maverick006/delivery-time-prediction)**

*Drop a pin on the map for the restaurant, drop another for the delivery location, customize rider and weather details in the sidebar, and get an instant delivery time prediction.*

---

## 🛠️ Tech Stack
*   **Modeling:** Stacking Regressor (Random Forest + LightGBM → Ridge/Linear Regression meta-model).
*   **Pipeline & Versioning:** DVC (Data Version Control) for structured reproducibility.
*   **Experiment Tracking:** MLflow integrated with DagsHub.
*   **Deployment & UI:** Streamlit, Docker, Hugging Face Spaces.
*   **Key Libraries:** Scikit-Learn, LightGBM, Pandas, Folium, joblib.

---

## 📂 Project Structure
```text
├── models/                  # Trained models & preprocessors
├── notebooks/               # Jupyter notebooks for EDA, data cleaning, and tuning
├── scripts/                 # Core preprocessing and utility scripts
├── src/                     # Source code pipeline (DVC stages)
├── streamlit_app.py         # Main map-based interactive UI
├── Dockerfile.streamlit     # Docker container config for the web application
├── dvc.yaml                 # DVC pipeline stages
└── prepare_hf_deploy.py     # Deployment prep script
```

---

## 💻 Running Locally

### 1. Clone & Set Up environment
Make sure you have `uv` installed, then run:
```bash
# Clone the repository
git clone https://github.com/MaverickDev-J/Delivery-Time-Prediction.git
cd Delivery-Time-Prediction

# Install dependencies
uv sync
```

### 2. Run the Streamlit UI
```bash
uv run streamlit run streamlit_app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.
