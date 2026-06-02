"""Instagram Graph API client.

Three public calls:
  - fetch_account_info — auth/identity probe used at startup
  - fetch_media        — list recent media (Stories filtered client-side)
  - fetch_insights     — per-media metrics with REELS/FEED branching, plus
                         self-healing fallback when the API rejects a metric
                         (see _KNOWN_UNSUPPORTED for the runtime cache).
"""

from __future__ import annotations

import re
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
# These are the *aspirational* lists. The API can reject individual metrics
# with code 100 "does not support the X metric" — this happens when:
#   - The account is below a tier threshold (`follows` per-media)
#   - The graph version is too old (`reels_skip_rate` needs v22.0+, was added
#     Dec 2025; default config is still v21.0)
#   - The token is missing `instagram_manage_insights`
#
# fetch_insights handles rejection gracefully: it strips the offending metric,
# caches the rejection in `_KNOWN_UNSUPPORTED` to avoid re-trying on every
# call this run, and retries. The corresponding Notion column then stays at
# its prior value (per the empty-vs-zero rule).
#
# `breakdown=follow_type` (per-post follower vs non-follower view split) is
# still NOT exposed for media — only at the account level. See models.IGInsights.
_REELS_METRICS: tuple[str, ...] = (
    "reach", "saved", "shares", "total_interactions", "views",
    "follows", "reels_skip_rate",
    "ig_reels_avg_watch_time", "ig_reels_video_view_total_time",
)
_FEED_METRICS: tuple[str, ...] = (
    "reach", "saved", "shares", "total_interactions", "views", "follows",
)

# Metrics the API has rejected this process — used to skip them on subsequent
# calls without re-paying for the error. Reset on each `uv run ig-sync`.
_KNOWN_UNSUPPORTED: set[str] = set()

_UNSUPPORTED_METRIC_RE = re.compile(r"does not support the (\w+) metric", re.IGNORECASE)


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

    Resilient to per-metric rejection: if the API returns code 100 "does not
    support the X metric", X is stripped, cached in `_KNOWN_UNSUPPORTED`, and
    the call is retried. Up to len(metric_list) retries per call. Metrics that
    end up dropped just stay None on the returned IGInsights, which means the
    corresponding Notion column keeps its prior value.

    `breakdown=follow_type` is still not available for media — see
    models.IGInsights. The Notion `Views follower %` / `Views non-follower %`
    columns therefore remain manual.

    Raises:
        InsightsUnavailableError: when IG signals insights aren't ready
            (typical for posts published <30min ago). Caller should skip.
        InstagramAPIError: any other API failure (auth, network, all metrics
            stripped, etc.).
    """
    base = _REELS_METRICS if media.media_product_type == "REELS" else _FEED_METRICS
    metric_list = [m for m in base if m not in _KNOWN_UNSUPPORTED]

    url = f"{settings.ig_graph_base}/{media.id}/insights"
    payload: dict[str, Any] | None = None

    # Worst case we strip every metric one at a time; cap retries at that.
    for _ in range(len(metric_list) + 1):
        if not metric_list:
            raise InstagramAPIError(
                f"All insight metrics rejected for {media.id} "
                f"({media.short_permalink}). Unsupported on this account: "
                f"{sorted(_KNOWN_UNSUPPORTED)}"
            )
        params = {
            "metric": ",".join(metric_list),
            "access_token": settings.IG_ACCESS_TOKEN.get_secret_value(),
        }
        try:
            payload = _get(url, params)
            break
        except InstagramAPIError as e:
            msg = str(e)
            msg_lower = msg.lower()
            if "not available" in msg_lower or "not exist" in msg_lower:
                raise InsightsUnavailableError(
                    f"Insights not ready for {media.id} "
                    f"({media.short_permalink}): {e}"
                ) from e
            m = _UNSUPPORTED_METRIC_RE.search(msg)
            if m and m.group(1) in metric_list:
                bad = m.group(1)
                _KNOWN_UNSUPPORTED.add(bad)
                metric_list = [x for x in metric_list if x != bad]
                continue
            raise

    assert payload is not None  # loop always sets it before break
    metrics = _flatten_metrics(payload.get("data", []))

    return IGInsights(
        media_id=media.id,
        reach=metrics.get("reach"),
        views=metrics.get("views"),
        saved=metrics.get("saved"),
        shares=metrics.get("shares"),
        total_interactions=metrics.get("total_interactions"),
        follows=metrics.get("follows"),
        skip_rate=metrics.get("reels_skip_rate"),
        avg_watch_time_ms=metrics.get("ig_reels_avg_watch_time"),
        total_watch_time_ms=metrics.get("ig_reels_video_view_total_time"),
    )
