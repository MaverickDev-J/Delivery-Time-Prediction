"""
Run this script from the project root AFTER cloning the HF Space repo.
It copies all needed files into the hf_deploy/ folder ready to push.

Usage:
    uv run python prepare_hf_deploy.py
"""
import shutil
from pathlib import Path

ROOT   = Path(__file__).parent
DEPLOY = ROOT / "hf_deploy"

DEPLOY.mkdir(exist_ok=True)
(DEPLOY / "scripts").mkdir(exist_ok=True)
(DEPLOY / "models").mkdir(exist_ok=True)

files = [
    (ROOT / "streamlit_app.py",                  DEPLOY / "streamlit_app.py"),
    (ROOT / "requirements.txt",                  DEPLOY / "requirements.txt"),
    (ROOT / "scripts" / "data_clean_utils.py",   DEPLOY / "scripts" / "data_clean_utils.py"),
    (ROOT / "models"  / "preprocessor.joblib",   DEPLOY / "models"  / "preprocessor.joblib"),
    (ROOT / "models"  / "model.joblib",           DEPLOY / "models"  / "model.joblib"),
]

print("Copying files into hf_deploy/...\n")
for src, dst in files:
    if src.exists():
        shutil.copy2(src, dst)
        size = src.stat().st_size / 1_000_000
        print(f"  ✅  {src.name:35s} ({size:.1f} MB)")
    else:
        print(f"  ❌  MISSING: {src}")

print("\nAll files ready in hf_deploy/")
print("Next steps printed below:\n")
print("─" * 55)
print("cd hf_deploy")
print('git lfs track "*.joblib"')
print("git add .gitattributes")
print("git add .")
print('git commit -m "Deploy Swiggy Delivery Time Predictor"')
print("git push")
print("─" * 55)
