@echo off
echo Starting AgentMate Frontend...
cd /d "%~dp0"
streamlit run agentmate\frontend\app.py --server.port 8501
