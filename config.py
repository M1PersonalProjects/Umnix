from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: SecretStr
    openai_api_key: SecretStr
    database_url: str
    admin_ids: set[int] = Field(default_factory=set)
    webapp_base_url: str = "http://127.0.0.1:8000"
    bot_username: str = "EduAI_platform_bot"
    attachments_dir: str = "backend/files/attachments"
    openai_model: str = "gpt-4o"
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_timeout_seconds: float = Field(default=600.0, gt=0, le=600)
    openai_max_retries: int = Field(default=2, ge=0, le=10)
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: Any) -> Any:
        if isinstance(value, str):
            clean = value.strip("[]'\" ")
            return {int(item.strip()) for item in clean.split(",") if item.strip()}
        if isinstance(value, int):
            return {value}
        return value

    def absolute_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else BASE_DIR / path


settings = Settings()
