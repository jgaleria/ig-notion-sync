"""Notion API client + upsert logic.

Phase 5 — data source query and row extraction for matching.
Phase 6 will implement the upsert with the spec's field-write rules,
gated by Settings.DRY_RUN.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from src.config import Settings
from src.models import NotionRow


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


def normalize_permalink(url: str | None) -> str | None:
    """Canonicalize a permalink for equality matching.

    People type permalinks in Notion any number of ways:
      https://www.instagram.com/reel/ABC/   ← what IG returns
      https://instagram.com/reel/ABC
      instagram.com/reel/ABC/
      www.instagram.com/reel/ABC

    Normalize to host+path, lowercased, no protocol, no `www.`, no trailing slash.
    """
    if not url:
        return None
    s = url.strip().lower()
    parsed = urlparse(s if "://" in s else f"https://{s}")
    host = (parsed.netloc or "").removeprefix("www.")
    path = parsed.path.rstrip("/")
    if not host:
        return None
    return f"{host}{path}"
