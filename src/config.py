"""Environment configuration.

Single source of truth for all secrets and behavior flags. Loaded once
at startup and passed (or imported) by other modules. Pydantic validates
on load so misconfiguration fails loud, not at the API call site.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Instagram
    IG_USER_ID: str = Field(..., min_length=10)
    IG_ACCESS_TOKEN: SecretStr
    IG_GRAPH_API_VERSION: str = "v21.0"
    META_APP_ID: str | None = None
    META_APP_SECRET: SecretStr | None = None

    # Notion
    NOTION_TOKEN: SecretStr
    NOTION_DATA_SOURCE_ID: str = Field(..., min_length=32)
    NOTION_VERSION: str = "2025-09-03"

    # Behavior
    DRY_RUN: bool = False
    MAX_POSTS: int = Field(50, ge=1, le=200)

    @property
    def ig_graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.IG_GRAPH_API_VERSION}"

    @property
    def notion_api_base(self) -> str:
        return "https://api.notion.com/v1"


@lru_cache
def get_settings() -> Settings:
    """Returns the validated settings singleton. Raises ValidationError on bad config."""
    return Settings()  # type: ignore[call-arg]
