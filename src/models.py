"""Shared data models.

Pydantic v2 models for IG API responses and (later) Notion row payloads.
Validation at the API boundary means downstream code can assume well-typed data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# IG response enums (string-only; we don't enforce, just document)
MediaType = Literal["IMAGE", "VIDEO", "CAROUSEL_ALBUM"]
MediaProductType = Literal["FEED", "REELS", "STORY", "AD"]

# Notion select options for the Media Type column (per spec)
NotionMediaType = Literal["Reel", "Image", "Carousel"]


class IGMedia(BaseModel):
    """A single media item from /{ig_user_id}/media."""

    model_config = ConfigDict(extra="ignore")

    id: str
    caption: str | None = None
    media_type: str  # IMAGE | VIDEO | CAROUSEL_ALBUM
    media_product_type: str  # FEED | REELS | STORY | AD
    permalink: str
    thumbnail_url: str | None = None  # videos only
    media_url: str | None = None  # often a signed CDN URL that expires
    timestamp: datetime
    like_count: int = 0
    comments_count: int = 0

    @property
    def notion_media_type(self) -> NotionMediaType:
        """Map IG type fields to the Notion `Media Type` select option."""
        if self.media_product_type == "REELS":
            return "Reel"
        if self.media_type == "CAROUSEL_ALBUM":
            return "Carousel"
        if self.media_type == "IMAGE":
            return "Image"
        # Non-Reel feed video — closest Notion option is Reel
        return "Reel"

    @property
    def short_permalink(self) -> str:
        """Short form for log lines: /reel/DYieyN0PrFG/ instead of full URL."""
        return self.permalink.replace("https://www.instagram.com", "").rstrip("/") + "/"
