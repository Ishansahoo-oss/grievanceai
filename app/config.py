"""
Application configuration, loaded from environment variables / .env file.
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    GEMINI_API_KEY: str = ""
    WHATSAPP_TOKEN: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """
        Some hosts (Railway, Heroku-style providers) hand out connection
        strings starting with "postgres://", which SQLAlchemy's psycopg2
        dialect doesn't accept — it wants "postgresql://". Normalize here
        so DATABASE_URL works as-is regardless of which host provided it.
        """
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
