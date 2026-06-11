@echo off
REM Avvia PerixMonitor Price (richiede Python installato)
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
python -m streamlit run app.py
pause
