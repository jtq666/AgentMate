"""
全局配置
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class LLMConfig:
    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "kimi-k3"))
    temperature: float = 0.3
    max_tokens: int = 4096


@dataclass
class EmbeddingConfig:
    use_local: bool = field(default_factory=lambda: os.getenv("USE_LOCAL_EMBEDDING", "true").lower() == "true")
    model_name: str = "all-MiniLM-L6-v2"
    dimension: int = 384


@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    memory_dir: str = str(PROJECT_ROOT / "agentmate" / "data" / "memory")


@dataclass
class Settings:
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    app: AppConfig = field(default_factory=AppConfig)


settings = Settings()
