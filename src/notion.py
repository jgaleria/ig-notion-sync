"""Notion API client + upsert logic.

Phase 5 — data source query and row extraction for matching.
Phase 6 — build_upsert() (pure intent computation) + apply_upsert()
(side-effecting write, gated by Settings.DRY_RUN).
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from src.config import Settings
from src.models import IGInsights, IGMedia, NotionRow, UpsertIntent


HTTP_TIMEOUT = 30.0


class NotionAPIError(Exception):
    """Raised when the Notion API returns an error or is unreachable."""


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.NOTION_TOKEN.get_secret_value()}",
        "Notion-Version": settings.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _raise_from_response(response: httpx.Response) -> None:
    """Convert a non-2xx Notion response into a clear NotionAPIError."""
    try:
        body = response.json()
    except ValueError:
        raise NotionAPIError(
            f"HTTP {response.status_code} (non-JSON body): {response.text[:200]}"
        )

    code = body.get("code", "unknown")
    msg = body.get("message", "<no message>")

    if code == "unauthorized":
        raise NotionAPIError(
            f"Unauthorized: {msg}\n"
            f"  → NOTION_TOKEN may be invalid, revoked, or from another workspace."
        )
    if code == "object_not_found":
        raise NotionAPIError(
            f"Object not found: {msg}\n"
            f"  → Confirm NOTION_DATA_SOURCE_ID, and that the integration is "
            f"connected to the database (Notion → DB → ⋯ → Connections → Add)."
        )
    if code == "restricted_resource":
        raise NotionAPIError(
            f"Restricted resource: {msg}\n"
            f"  → Integration is not authorized for this resource."
        )
    if code == "validation_error":
        raise NotionAPIError(f"Validation error: {msg}")
    if code == "rate_limited":
        raise NotionAPIError(f"Rate limited: {msg}  (back off and retry)")

    raise NotionAPIError(f"HTTP {response.status_code} ({code}): {msg}")


# ─── Query ────────────────────────────────────────────────────────────


def query_data_source(
    settings: Settings,
    *,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch all pages from the configured data source, paginated.

    Returns the raw page objects (Notion's wire format). Caller extracts
    properties via `extract_row()`.

    Per spec, we fetch *all* rows (not just Status=Done) — in-progress or
    draft rows may already have a permalink set by manual planning, and
    we need to match against those to avoid duplicate creation.
    """
    url = f"{settings.notion_api_base}/data_sources/{settings.NOTION_DATA_SOURCE_ID}/query"
    headers = _headers(settings)

    pages: list[dict[str, Any]] = []
    start_cursor: str | None = None

    while True:
        body: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            body["start_cursor"] = start_cursor

        try:
            response = httpx.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT)
        except httpx.RequestError as e:
            raise NotionAPIError(f"Network error reaching Notion: {e}") from e

        if response.is_error:
            _raise_from_response(response)

        payload = response.json()
        pages.extend(payload.get("results", []))

        if not payload.get("has_more"):
            break
        start_cursor = payload.get("next_cursor")
        if not start_cursor:
            break

    return pages


# ─── Property extractors ──────────────────────────────────────────────


def _rich_text_str(prop: dict[str, Any]) -> str | None:
    """Flatten a rich_text property into a plain string, or None if empty."""
    parts = prop.get("rich_text", []) if prop else []
    text = "".join(t.get("plain_text", "") for t in parts).strip()
    return text or None


def _title_str(prop: dict[str, Any]) -> str | None:
    parts = prop.get("title", []) if prop else []
    text = "".join(t.get("plain_text", "") for t in parts).strip()
    return text or None


def _url_str(prop: dict[str, Any]) -> str | None:
    val = prop.get("url") if prop else None
    return val.strip() if val else None


def _select_name(prop: dict[str, Any]) -> str | None:
    sel = (prop or {}).get("select")
    return sel.get("name") if sel else None


def _status_name(prop: dict[str, Any]) -> str | None:
    sel = (prop or {}).get("status")
    return sel.get("name") if sel else None


def _date_start(prop: dict[str, Any]) -> str | None:
    d = (prop or {}).get("date")
    return d.get("start") if d else None


def extract_row(page: dict[str, Any]) -> NotionRow:
    """Pull the fields we care about out of a Notion page object."""
    props = page.get("properties", {})
    return NotionRow(
        page_id=page["id"],
        ig_media_id=_rich_text_str(props.get("IG Media ID", {})),
        permalink=_url_str(props.get("Link to post", {})),
        name=_title_str(props.get("Name", {})),
        status=_status_name(props.get("Status", {})),
        topics=_select_name(props.get("Topics", {})),
        platform=_select_name(props.get("Platform", {})),
        publication_date=_date_start(props.get("Publication Date", {})),
    )


# ─── Permalink normalization (for matching) ───────────────────────────


# IG uses different path prefixes for the same content:
#   /p/SHORTCODE     — generic post path (what users often paste)
#   /reel/SHORTCODE  — what the Graph API returns for Reels
#   /reels/SHORTCODE — older variant
#   /tv/SHORTCODE    — IGTV (deprecated but URLs still resolve)
# All point to the same media when the shortcode matches. Canonicalize
# to just the shortcode so matching is robust against the prefix.
# Case-sensitive in the capture: shortcodes are case-sensitive on IG.
_IG_SHORTCODE_RE = re.compile(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")


def normalize_permalink(url: str | None) -> str | None:
    """Canonicalize a permalink for equality matching.

    Returns `instagram.com/<shortcode>` for any IG post URL regardless of
    path prefix or formatting. Examples that all collapse to the same key:

      https://www.instagram.com/reel/DXvVyMoPbyP/   ← what IG returns
      https://instagram.com/p/DXvVyMoPbyP            ← what users often paste
      instagram.com/reels/DXvVyMoPbyP/
      www.instagram.com/tv/DXvVyMoPbyP

    Non-IG URLs (or anything without a recognizable shortcode) fall back
    to host+path, lowercased and trimmed.
    """
    if not url:
        return None
    s = url.strip()
    parsed = urlparse(s if "://" in s else f"https://{s}")
    host = (parsed.netloc or "").removeprefix("www.").lower()
    if not host:
        return None
    # Try to extract a shortcode (case-sensitive — IG shortcodes are mixed-case)
    m = _IG_SHORTCODE_RE.search(parsed.path)
    if m:
        return f"{host}/{m.group(1)}"
    # Fallback: lowercased host + path, no trailing slash
    return f"{host}{parsed.path.rstrip('/').lower()}"


# ─── Property serializers ─────────────────────────────────────────────
# Notion expects a specific JSON shape for each property type. These helpers
# centralize that so build_upsert reads as a plain field map.


def _title(text: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": text or ""}}]}


def _rich_text(text: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": text or ""}}]}


def _url(url: str | None) -> dict[str, Any]:
    return {"url": url or None}


def _date_iso(iso: str) -> dict[str, Any]:
    return {"date": {"start": iso}}


def _number(n: float | int) -> dict[str, Any]:
    return {"number": n}


def _select(name: str) -> dict[str, Any]:
    return {"select": {"name": name}}


def _status(name: str) -> dict[str, Any]:
    return {"status": {"name": name}}


# ─── Upsert intent builder (pure) ─────────────────────────────────────


# Statuses where the script is allowed to set Status → Done.
# Per spec: blank, Editing, Record, or already Done.
_STATUS_OVERWRITABLE = {None, "", "Editing", "Record", "Done"}


def _name_for_new_row(media: IGMedia) -> str:
    """Default title for a CREATE — first line of caption, capped at 80 chars,
    or a fallback if no caption."""
    if media.caption:
        first_line = media.caption.splitlines()[0].strip()
        if first_line:
            return first_line[:80]
    return f"IG {media.short_permalink}"


def build_upsert(
    media: IGMedia,
    insights: IGInsights | None,
    existing: NotionRow | None,
) -> UpsertIntent:
    """Compute what to write for one IG post. No I/O.

    insights=None means InsightsUnavailableError fired (post too fresh).
    Identity fields still get written; metric fields are skipped.
    """
    props: dict[str, dict] = {}
    notes: list[str] = []

    # ─── Identity fields (always overwrite) ───────────────────────────
    props["Caption"] = _rich_text(media.caption or "")
    if media.thumbnail_url or media.media_url:
        props["Thumbnail"] = _url(media.thumbnail_url or media.media_url)
    props["Media Type"] = _select(media.notion_media_type)
    props["Last Synced"] = _date_iso(
        datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    # ─── Identity fields (write-if-blank) ─────────────────────────────
    if existing is None or not existing.ig_media_id:
        props["IG Media ID"] = _rich_text(media.id)
        if existing is not None and not existing.ig_media_id:
            notes.append("backfilling IG Media ID")
    if existing is None or not existing.publication_date:
        # IG timestamps include tz offset; Notion accepts the ISO datetime as-is
        props["Publication Date"] = _date_iso(media.timestamp.isoformat())
    if existing is None or not existing.permalink:
        props["Link to post"] = _url(media.permalink)
    if existing is None or not existing.platform:
        props["Platform"] = _select("Instagram")

    # ─── Status — Done if currently in {blank, Editing, Record, Done} ──
    if existing is None:
        props["Status"] = _status("Done")  # new row → Done
    elif existing.status in _STATUS_OVERWRITABLE and existing.status != "Done":
        props["Status"] = _status("Done")
        notes.append(f"status: {existing.status or '∅'} → Done")
    elif existing.status not in _STATUS_OVERWRITABLE:
        notes.append(f"status: {existing.status} (protected — left alone)")

    # ─── Metric fields (always overwrite when insights present) ───────
    if insights is not None:
        # likes/comments from /media, not /insights
        props["Likes"] = _number(media.like_count)
        props["Comments"] = _number(media.comments_count)
        if insights.reach is not None:
            props["Reach"] = _number(insights.reach)
        if insights.views is not None:
            props["Total views"] = _number(insights.views)
        if insights.saved is not None:
            props["Saves"] = _number(insights.saved)
        if insights.shares is not None:
            props["Shares"] = _number(insights.shares)
        if insights.avg_watch_time_s is not None:
            props["Average Watch Time (s)"] = _number(insights.avg_watch_time_s)
        if insights.total_watch_time_s is not None:
            props["Total Watch Time (s)"] = _number(insights.total_watch_time_s)
    else:
        notes.append("insights unavailable — identity-only write")

    # ─── New-row only: derive a title ─────────────────────────────────
    if existing is None:
        props["Name"] = _title(_name_for_new_row(media))

    return UpsertIntent(
        media_id=media.id,
        short_permalink=media.short_permalink,
        action="CREATE" if existing is None else "UPDATE",
        page_id=existing.page_id if existing else None,
        properties=props,
        notes=notes,
    )


# ─── Upsert apply (side-effecting) ────────────────────────────────────


# Notion rate limit is ~3 req/sec; spec says sleep 0.4s between writes.
NOTION_WRITE_SLEEP = 0.4


def apply_upsert(settings: Settings, intent: UpsertIntent) -> str | None:
    """Execute an upsert against the Notion API.

    Honors settings.DRY_RUN — when true, returns None without making any calls.
    Otherwise PATCHes for UPDATE or POSTs for CREATE.

    Returns the page_id on success, None on dry-run or skip.

    Sleeps NOTION_WRITE_SLEEP after a successful write to stay under the
    3 req/sec Notion limit.
    """
    if settings.DRY_RUN or intent.action == "SKIP":
        return None

    headers = _headers(settings)

    if intent.action == "UPDATE":
        assert intent.page_id, "UPDATE intent must have a page_id"
        url = f"{settings.notion_api_base}/pages/{intent.page_id}"
        body = {"properties": intent.properties}
        try:
            response = httpx.patch(url, headers=headers, json=body, timeout=HTTP_TIMEOUT)
        except httpx.RequestError as e:
            raise NotionAPIError(f"Network error on PATCH: {e}") from e
        if response.is_error:
            _raise_from_response(response)
        time.sleep(NOTION_WRITE_SLEEP)
        return response.json().get("id")

    if intent.action == "CREATE":
        url = f"{settings.notion_api_base}/pages"
        body = {
            # 2025-09-03 API: parent uses data_source_id for new rows in a data source
            "parent": {"data_source_id": settings.NOTION_DATA_SOURCE_ID},
            "properties": intent.properties,
        }
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT)
        except httpx.RequestError as e:
            raise NotionAPIError(f"Network error on POST: {e}") from e
        if response.is_error:
            _raise_from_response(response)
        time.sleep(NOTION_WRITE_SLEEP)
        return response.json().get("id")

    return None
