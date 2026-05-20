"""Instagram Graph API client.

Phase 2 — auth check (fetch_account_info).
Phase 3 will add media listing.
Phase 4 will add per-media insights with REELS vs FEED metric branching
and the `breakdown=follow_type` call for follower/non-follower split.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.config import Settings


HTTP_TIMEOUT = 30.0


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


def fetch_account_info(settings: Settings) -> dict[str, Any]:
    """Fetch the IG Business/Creator account profile.

    Used as the auth check at startup: a successful return means the token
    is valid, has at least `instagram_basic` scope, and IG_USER_ID is correct.

    Raises:
        InstagramAPIError: on any auth, permission, or network failure.
    """
    url = f"{settings.ig_graph_base}/{settings.IG_USER_ID}"
    params = {
        "fields": "id,ig_id,username,name,followers_count,follows_count,"
        "media_count,profile_picture_url",
        "access_token": settings.IG_ACCESS_TOKEN.get_secret_value(),
    }

    try:
        response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
    except httpx.RequestError as e:
        raise InstagramAPIError(f"Network error reaching Graph API: {e}") from e

    if response.is_error:
        _raise_from_response(response)

    return response.json()
