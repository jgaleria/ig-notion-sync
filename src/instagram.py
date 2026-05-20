"""Instagram Graph API client.

Phase 2 — auth check (fetch_account_info).
Phase 3 — media listing (fetch_media).
Phase 4 will add per-media insights with REELS vs FEED metric branching
and the `breakdown=follow_type` call for follower/non-follower split.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.config import Settings
from src.models import IGInsights, IGMedia


HTTP_TIMEOUT = 30.0

# Fields requested from /{ig_user_id}/media per the spec.
# like_count / comments_count come from here, NOT from /insights.
_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,"
    "thumbnail_url,media_url,timestamp,like_count,comments_count"
)

# Per-media insights metric lists, by media_product_type.
#
# NOTE: `follows` (new followers attributed to a post) used to be available
# per-media but Meta moved it to the account-level Insights endpoint only.
# Requesting it here returns code 100 "does not support the follows metric
# for this media product type." We leave the Notion "New Followers" column
# blank — fill manually if you track per-post follow attribution another way.
_REELS_METRICS = (
    "reach,saved,shares,total_interactions,views,"
    "ig_reels_avg_watch_time,ig_reels_video_view_total_time"
)
_FEED_METRICS = "reach,saved,shares,total_interactions,views"


class InstagramAPIError(Exception):
    """Raised when the IG Graph API returns an error or is unreachable."""


class InsightsUnavailableError(InstagramAPIError):
    """Insights not ready or unavailable for a specific media item.

    Common cause: media was published less than ~30 minutes ago, so Meta
    hasn't computed metrics yet. Caller should skip and let the next run
    pick it up.
    """


def _raise_from_response(response: httpx.Response) -> None:
    """Convert a non-2xx response into a clear InstagramAPIError.

    Maps the common Meta error codes to actionable messages — saves us from
    debugging cryptic OAuthException dumps later.
    """
    try:
        err = response.json().get("error", {})
    except ValueError:
        raise InstagramAPIError(
            f"HTTP {response.status_code} (non-JSON body): {response.text[:200]}"
        )

    code = err.get("code")
    msg = err.get("message", "<no message>")
    err_type = err.get("type", "<unknown>")

    if code == 190:
        raise InstagramAPIError(
            f"Access token rejected (code 190): {msg}\n"
            f"  → Token may be expired or revoked. Re-issue via the FB token "
            f"exchange (see README → Token refresh)."
        )
    if code == 200:
        raise InstagramAPIError(
            f"Permission denied (code 200): {msg}\n"
            f"  → The token is missing `instagram_manage_insights` or another "
            f"required scope. Re-authorize in Graph API Explorer."
        )
    if code == 100:
        raise InstagramAPIError(
            f"Bad request (code 100): {msg}\n"
            f"  → Likely an invalid field name or ID. Check IG_USER_ID in .env."
        )

    raise InstagramAPIError(
        f"HTTP {response.status_code}: {err_type} (code {code}) — {msg}"
    )


def _get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET with shared error handling. Returns the parsed JSON body on success."""
    try:
        response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
    except httpx.RequestError as e:
        raise InstagramAPIError(f"Network error reaching Graph API: {e}") from e

    if response.is_error:
        _raise_from_response(response)

    return response.json()


def fetch_account_info(settings: Settings) -> dict[str, Any]:
    """Fetch the IG Business/Creator account profile.

    Used as the auth check at startup: a successful return means the token
    is valid, has at least `instagram_basic` scope, and IG_USER_ID is correct.
    """
    url = f"{settings.ig_graph_base}/{settings.IG_USER_ID}"
    params = {
        "fields": "id,ig_id,username,name,followers_count,follows_count,"
        "media_count,profile_picture_url",
        "access_token": settings.IG_ACCESS_TOKEN.get_secret_value(),
    }
    return _get(url, params)


def fetch_media(settings: Settings) -> list[IGMedia]:
    """List recent media items (newest first), excluding Stories.

    Honors `Settings.MAX_POSTS` as the page size. Doesn't paginate further —
    if you've posted more than MAX_POSTS items, increase the env var. For the
    typical use (daily sync of recent activity), the most recent 50 covers it.

    Stories are filtered client-side per spec: their lifecycle (24h) and metric
    shape don't fit the Content database model.
    """
    url = f"{settings.ig_graph_base}/{settings.IG_USER_ID}/media"
    params = {
        "fields": _MEDIA_FIELDS,
        "limit": settings.MAX_POSTS,
        "access_token": settings.IG_ACCESS_TOKEN.get_secret_value(),
    }
    payload = _get(url, params)
    items = payload.get("data", [])
    media = [IGMedia.model_validate(item) for item in items]
    return [m for m in media if m.media_product_type != "STORY"]


# ─── Insights ──────────────────────────────────────────────────────────


def _flatten_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    """IG returns each metric as its own object — flatten to {name: value}.

    Shape: [{name: 'reach', period: 'lifetime', values: [{value: 1234}], ...}]
    A few metrics use `total_value: {value: N}` instead of `values`.
    Empty / missing values pass through as None per spec.
    """
    out: dict[str, Any] = {}
    for item in items:
        name = item.get("name")
        if not name:
            continue
        values = item.get("values")
        if values and isinstance(values, list) and values[0]:
            out[name] = values[0].get("value")
            continue
        total = item.get("total_value") or {}
        if "value" in total:
            out[name] = total["value"]
    return out


def fetch_insights(settings: Settings, media: IGMedia) -> IGInsights:
    """Fetch per-media insights for a single post.

    One API call — the spec originally called for a second `breakdown=follow_type`
    request to compute "Views follower %", but Meta removed that breakdown from
    per-media insights (see models.IGInsights for the full note). The Notion
    follower% columns are now manual.

    Raises:
        InsightsUnavailableError: when IG signals insights aren't ready
            (typical for posts published <30min ago). Caller should skip.
        InstagramAPIError: any other API failure (auth, network, etc.).
    """
    metric_list = _REELS_METRICS if media.media_product_type == "REELS" else _FEED_METRICS

    url = f"{settings.ig_graph_base}/{media.id}/insights"
    params = {
        "metric": metric_list,
        "access_token": settings.IG_ACCESS_TOKEN.get_secret_value(),
    }

    try:
        payload = _get(url, params)
    except InstagramAPIError as e:
        msg = str(e).lower()
        if "not available" in msg or "not exist" in msg:
            raise InsightsUnavailableError(
                f"Insights not ready for {media.id} ({media.short_permalink}): {e}"
            ) from e
        raise
    metrics = _flatten_metrics(payload.get("data", []))

    return IGInsights(
        media_id=media.id,
        reach=metrics.get("reach"),
        views=metrics.get("views"),
        saved=metrics.get("saved"),
        shares=metrics.get("shares"),
        total_interactions=metrics.get("total_interactions"),
        follows=metrics.get("follows"),  # always None — kept for shape
        avg_watch_time_ms=metrics.get("ig_reels_avg_watch_time"),
        total_watch_time_ms=metrics.get("ig_reels_video_view_total_time"),
    )
