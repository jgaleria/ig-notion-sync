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
from src.models import IGMedia


HTTP_TIMEOUT = 30.0

# Fields requested from /{ig_user_id}/media per the spec.
# like_count / comments_count come from here, NOT from /insights.
_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,"
    "thumbnail_url,media_url,timestamp,like_count,comments_count"
)


class InstagramAPIError(Exception):
    """Raised when the IG Graph API returns an error or is unreachable."""


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
