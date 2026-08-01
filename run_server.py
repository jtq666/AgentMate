"""AgentMate FastAPI 启动入口。"""

from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from agentmate.config import settings  # noqa: E402


if __name__ == "__main__":
    print(f"AgentMate model: {settings.llm.model}")
    uvicorn.run("agentmate.api.main:app", host=settings.app.host,
                port=settings.app.port, log_level="info")
