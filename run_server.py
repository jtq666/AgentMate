"""
EduAgent 启动脚本
确保 lifespan 正确执行后再启动 uvicorn
"""
import os
import sys

# 确保工作目录正确
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

# 加载 .env
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(".env"))

# 验证配置
from eduagent.config import settings
print(f"API Key: {settings.llm.api_key[:10]}...")
print(f"Base URL: {settings.llm.base_url}")
print(f"Model: {settings.llm.model}")

# 启动 uvicorn
import uvicorn
uvicorn.run(
    "eduagent.api.main:app",
    host="0.0.0.0",
    port=8000,
    log_level="info",
)
