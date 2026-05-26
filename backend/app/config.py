"""
Configuration Module
Handles all application settings using pydantic-settings.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # Application
    APP_NAME: str = "CodeSage"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False)
    API_V1_PREFIX: str = "/api/v1"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Security
    SECRET_KEY: str = Field(..., description="JWT secret key - must be set in production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://codesage:codesage@postgres:5432/codesage",
        description="Async PostgreSQL connection string"
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection string for BullMQ"
    )

    # GitHub OAuth
    GITHUB_CLIENT_ID: str = Field(..., description="GitHub OAuth App Client ID")
    GITHUB_CLIENT_SECRET: str = Field(..., description="GitHub OAuth App Client Secret")
    GITHUB_CALLBACK_URL: str = "http://localhost:8000/api/v1/auth/github/callback"

    # GitHub App (for webhook integration)
    GITHUB_APP_ID: str = Field(..., description="GitHub App ID")
    GITHUB_APP_PRIVATE_KEY: str = Field(..., description="GitHub App private key (PEM)")
    GITHUB_WEBHOOK_SECRET: str = Field(..., description="GitHub webhook secret")

    # Google Gemini AI
    GEMINI_API_KEY: str = Field(..., description="Google Gemini API key")
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_MAX_TOKENS: int = 8192
    GEMINI_TEMPERATURE: float = 0.7
    AGENT_SECURITY_TEMPERATURE: float = 0.2
    AGENT_COMPLEXITY_TEMPERATURE: float = 0.3
    AGENT_PERFORMANCE_TEMPERATURE: float = 0.3
    AGENT_STYLE_TEMPERATURE: float = 0.4
    AGENT_TEST_TEMPERATURE: float = 0.4
    AGENT_ORCHESTRATOR_TEMPERATURE: float = 0.2
    AGENT_ORCHESTRATOR_MAX_TOKENS: int = 8192

    # BullMQ
    BULLMQ_REVIEW_QUEUE: str = "review-requests"
    BULLMQ_CONCURRENCY: int = 5

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:4200",
        "http://localhost:8080",
    ]

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return v

    @field_validator("GITHUB_APP_PRIVATE_KEY")
    @classmethod
    def validate_private_key(cls, v: str) -> str:
        # Remove common PEM formatting issues
        v = v.replace("\\n", "\n").strip()
        if not v.startswith("-----BEGIN"):
            raise ValueError("GITHUB_APP_PRIVATE_KEY must be a valid PEM key")
        return v


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Convenience accessor
settings = get_settings()
