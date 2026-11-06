"""Typed runtime configuration loaded from the environment and the repository `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env",),
        env_prefix="RELAYOPS_",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    # operational: real records only, no seeding, real model required. demo: seeded sample world, labeled.
    # test: isolated test/evaluation databases.
    data_mode: Literal["operational", "demo", "test"] = "operational"
    database_url: str = "postgresql+psycopg://relayops:relayops@127.0.0.1:5440/relayops"
    # Used instead of database_url when data_mode is "demo", so the demo instance never shares the operational DB.
    demo_database_url: str | None = None
    session_secret: str = Field(default="dev-only-change-me", min_length=16)
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    web_origin: str = "http://localhost:3020"
    api_origin: str = "http://localhost:8020"

    # Model provider. `ollama` is real local inference; `fixture` is a deterministic
    # scripted provider that exists only for offline tests and is labeled everywhere.
    llm_provider: Literal["ollama", "fixture"] = "ollama"
    fixture_script: str = ""  # e.g. "generic" for offline browser tests; ignored unless llm_provider=fixture
    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3:4b-instruct"
    embed_model: str = "embeddinggemma"
    embed_dim: int = 768
    num_ctx: int = 8192
    max_output_tokens: int = 700
    llm_timeout_seconds: float = 90.0
    embed_max_chars: int = 2000

    # Investigation budgets, enforced in code.
    max_investigation_turns: int = 4
    max_tool_calls: int = 6
    max_repair_attempts: int = 1
    run_deadline_seconds: float = 420.0
    tool_result_limit: int = 5

    # Worker leases.
    job_lease_seconds: int = 60
    worker_poll_seconds: float = 1.0

    action_mode: Literal["local"] = "local"
    # Synthetic world anchor for seeded timestamps: "now" (rounded down to the hour) or an ISO-8601 UTC time.
    # Empty means the fixed anchor recorded in data/fixtures/world.json.
    world_anchor: str = "now"
    login_max_failures: int = 5
    login_window_minutes: int = 15

    @model_validator(mode="after")
    def _demo_database(self) -> Settings:
        if self.data_mode == "demo" and self.demo_database_url:
            self.database_url = self.demo_database_url
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
