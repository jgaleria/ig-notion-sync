"""Shared data models.

Pydantic v2 models for IG API responses and (later) Notion row payloads.
Validation at the API boundary means downstream code can assume well-typed data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class IGInsights(BaseModel):
    """Per-media metrics from /{media_id}/insights.

    All metric fields are optional — IG returns sparse data:
    - just-published posts may have empty insights for ~30min after publishing
    - some metrics only exist for REELS (avg_watch_time, total_watch_time)
    - the breakdown=follow_type call may fail independently of the main call

    Per spec: empty value from IG is treated as None, NOT zero.
    """

    model_config = ConfigDict(extra="ignore")

    media_id: str

    # Both REELS and FEED
    reach: int | None = None
    views: int | None = None  # → Notion "Total views"
    saved: int | None = None  # → Notion "Saves"
    shares: int | None = None  # → Notion "Shares"
    total_interactions: int | None = None  # not written to Notion
    follows: int | None = None  # → Notion "New Followers"

    # REELS only — IG returns milliseconds, we store as-is and convert via property
    avg_watch_time_ms: float | None = None
    total_watch_time_ms: float | None = None

    # NOTE: `breakdown=follow_type` was removed from per-media insights at some
    # point during v21–v22. None of `views`, `reach`, `saved`, `shares`, or
    # `total_interactions` accept it anymore ("Incompatible breakdowns" error).
    # `follow_type` only exists on account-level insights now, which is aggregate
    # across the account and useless for per-post attribution. So `Views follower %`
    # and `Views non-follower %` in Notion stay blank — fill manually if you
    # care about per-post follower split.

    # ─── Derived (convert ms→s) ───────────────────────────────────────

    @property
    def avg_watch_time_s(self) -> float | None:
        if self.avg_watch_time_ms is None:
            return None
        return round(self.avg_watch_time_ms / 1000.0, 2)

    @property
    def total_watch_time_s(self) -> float | None:
        if self.total_watch_time_ms is None:
            return None
        return round(self.total_watch_time_ms / 1000.0, 2)
