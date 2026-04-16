from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    audit_db_url: str = "sqlite+aiosqlite:///./aiops_audit.db"
    environment: str = "dev"
    allowed_runbooks: str = "restart_service,clear_tmp,restart_agent"
    ingest_rate_limit_per_minute: int = 600
    dedup_window_seconds: int = 300
    suppression_score_threshold: float = 0.60
    recommendation_min_confidence: float = 0.70
    slack_signing_secret: str = ""
    slack_bot_token: str = ""
    slack_approval_channel: str = "#ops-approvals"

    @property
    def allowed_runbook_set(self) -> set[str]:
        return {item.strip() for item in self.allowed_runbooks.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
