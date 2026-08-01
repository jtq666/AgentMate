"""AgentMate 全局配置。"""
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
    host: str = field(default_factory=lambda: os.getenv("AGENTMATE_HOST", "127.0.0.1"))
    port: int = 8000
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    memory_dir: str = field(default_factory=lambda: os.getenv(
        "AGENTMATE_MEMORY_DIR",
        str(PROJECT_ROOT / "agentmate" / "data" / "memory"),
    ))
    kb_persist_dir: str = field(default_factory=lambda: os.getenv(
        "AGENTMATE_KB_PERSIST_DIR",
        str(PROJECT_ROOT / "agentmate" / "data"),
    ))
    evaluation_path: str = field(default_factory=lambda: os.getenv(
        "AGENTMATE_EVALUATION_PATH",
        str(PROJECT_ROOT / "agentmate" / "data" / "evaluation.json"),
    ))
    study_db_path: str = field(default_factory=lambda: os.getenv(
        "AGENTMATE_STUDY_DB_PATH",
        str(PROJECT_ROOT / "agentmate" / "data" / "agentmate.db"),
    ))
    stage_timeout_seconds: int = field(default_factory=lambda: int(
        os.getenv("AGENTMATE_STAGE_TIMEOUT_SECONDS", "90")
    ))
    stage_max_retries: int = field(default_factory=lambda: int(
        os.getenv("AGENTMATE_STAGE_MAX_RETRIES", "1")
    ))
    import_roots: tuple[str, ...] = field(default_factory=lambda: tuple(
        p.strip() for p in os.getenv(
            "AGENTMATE_IMPORT_ROOTS",
            str(PROJECT_ROOT / "agentmate" / "data" / "imports"),
        ).split(os.pathsep) if p.strip()
    ))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        p.strip() for p in os.getenv(
            "AGENTMATE_CORS_ORIGINS",
            "http://localhost:8501,http://127.0.0.1:8501",
        ).split(",") if p.strip()
    ))


@dataclass
class Settings:
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    app: AppConfig = field(default_factory=AppConfig)


settings = Settings()
