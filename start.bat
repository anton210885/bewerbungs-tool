@echo off
cd /d "%~dp0"
if not exist .venv (
    echo Erstelle virtuelle Umgebung...
    python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist .env copy .env.example .env
.venv\Scripts\python -m streamlit run app.py
