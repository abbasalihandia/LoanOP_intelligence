"""Application settings.

All environment-specific configuration is read from environment variables
(or a local .env file) with the LOANOPS_ prefix. Nothing environment-specific
is hard-coded elsewhere in the application.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ folder, resolved from this file so defaults do not depend on the
# current working directory.
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LOANOPS_",
        extra="ignore",
    )

    app_name: str = "LoanOps Intelligence"
    environment: str = "local"

    # Stored as a comma-separated string so it is easy to set in .env.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # SQLite file under backend/data/ by default. Tests override this with
    # an in-memory database ("sqlite://").
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'loanops.db').as_posix()}"

    # Folder holding the synthetic source feeds and reference data.
    seed_data_dir: Path = BACKEND_DIR / "seed_data"

    # Tolerances, status vocabularies and severity rules for validation.
    validation_config_path: Path = BACKEND_DIR / "config" / "validation_rules.json"

    # --- AI investigation (Phase 4) ---------------------------------------
    # Ollama runs locally; only the backend ever calls it.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    # Local models on CPU can be slow; a single report may take minutes.
    ollama_timeout_seconds: float = Field(default=180.0, gt=0, le=1800)
    # Total attempts per investigation. Extra attempts are used only for
    # invalid output (with the validation errors fed back), never for
    # timeouts or an unreachable Ollama.
    ollama_max_attempts: int = Field(default=2, ge=1, le=4)
    ollama_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=131072)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (used as a FastAPI dependency)."""
    return Settings()
