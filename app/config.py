"""
Cấu hình tập trung.
Đọc từ .env hoặc environment variables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Zalo OA ──────────────────────────────────────────────────
    zalo_app_id: str = ""
    zalo_app_secret: str = ""
    zalo_oa_id: str = ""
    zalo_oa_access_token: str = ""
    zalo_oa_refresh_token: str = ""
    zalo_webhook_url: str = ""

    # ── LLM ──────────────────────────────────────────────────────
    llm_provider: str = "viettel"
    llm_base_url: str = "https://netmind.viettel.vn/codev"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: int = 15
    llm_max_tokens: int = 500
    llm_temperature: float = 0.1

    # ── Google ────────────────────────────────────────────────────
    google_service_account_json: str = "/secrets/google-service-account.json"
    google_sheet_template_id: str = ""
    google_sheet_parent_folder_id: str = ""
    backup_drive_folder_id: str = ""

    # ── DB ───────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:////data/agent.db"

    # ── Agent ────────────────────────────────────────────────────
    admin_member_ids: str = "M001"  # comma-separated
    timezone: str = "Asia/Ho_Chi_Minh"
    pending_expiry_minutes: int = 30
    max_input_length: int = 500

    # ── Rate limiting ─────────────────────────────────────────────
    rate_limit_per_user_per_min: int = 30
    rate_limit_per_user_per_day: int = 500
    rate_limit_llm_per_oa_per_hour: int = 100

    # ── Circuit breaker ───────────────────────────────────────────
    cb_llm_threshold: int = 5
    cb_llm_cooldown_seconds: int = 120
    cb_sheets_threshold: int = 5
    cb_sheets_cooldown_seconds: int = 300
    cb_zalo_threshold: int = 10
    cb_zalo_cooldown_seconds: int = 60

    # ── Observability ─────────────────────────────────────────────
    log_level: str = "INFO"
    otel_exporter: Literal["console", "jaeger", "none"] = "console"
    otel_endpoint: str = "http://localhost:4317"
    prometheus_port: int = 9090

    # ── Backup ───────────────────────────────────────────────────
    backup_local_path: str = "/data/backups"
    backup_encryption_key_path: str = "/secrets/backup-gpg.key"
    backup_retention_daily: int = 7
    backup_retention_weekly: int = 4
    backup_retention_monthly: int = 12

    # ── Telegram Bot ─────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""      # https://your-server.com/webhook/telegram
    telegram_webhook_secret: str = ""   # chuỗi tự chọn để verify header

    # ── Dev / Test ────────────────────────────────────────────────
    mock_channel_enabled: bool = False
    test_mode: bool = False

    # ── Derived properties ────────────────────────────────────────
    @property
    def admin_member_id_list(self) -> list[str]:
        return [x.strip() for x in self.admin_member_ids.split(",") if x.strip()]

    @field_validator("log_level")
    @classmethod
    def log_level_upper(cls, v: str) -> str:
        return v.upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings. Cache sau lần đọc đầu."""
    return Settings()
