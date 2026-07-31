@echo off
echo Starting EduAgent Frontend...
cd /d "%~dp0"
streamlit run eduagent\frontend\app.py --server.port 8501
