"""Entry point for the ig-sync CLI.

Phase 3 — adds media listing on top of the Phase 2 auth check.
"""

from __future__ import annotations

import sys
from collections import Counter

from src.config import Settings, get_settings
from src.instagram import InstagramAPIError, fetch_account_info, fetch_media
from src.models import IGMedia


def _print_config(settings: Settings) -> None:
    print("Config:")
    print(f"  IG_USER_ID            = {settings.IG_USER_ID}")
    print(f"  IG_GRAPH_API_VERSION  = {settings.IG_GRAPH_API_VERSION}")
    print(f"  NOTION_DATA_SOURCE_ID = {settings.NOTION_DATA_SOURCE_ID}")
    print(f"  NOTION_VERSION        = {settings.NOTION_VERSION}")
    print(f"  DRY_RUN               = {settings.DRY_RUN}")
    print(f"  MAX_POSTS             = {settings.MAX_POSTS}")


def _print_ig_account(account: dict) -> None:
    print("Instagram account:")
    print(f"  @{account.get('username')}  ({account.get('name')})")
    print(f"  IG Business ID: {account.get('id')}")
    print(f"  Legacy IG ID:   {account.get('ig_id')}")
    print(f"  Followers:      {account.get('followers_count')}")
    print(f"  Following:      {account.get('follows_count')}")
    print(f"  Grid count:     {account.get('media_count')} "
          "(may be lower than /media — counts grid-visible only)")


def _truncate(s: str | None, n: int) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _print_media_table(media: list[IGMedia]) -> None:
    counts = Counter(m.media_product_type for m in media)
    breakdown = ", ".join(f"{k}={v}" for k, v in counts.most_common())
    print(f"Fetched {len(media)} media items  ({breakdown})")
    print()

    # Header
    header = (
        f"  {'#':>3}  {'Date':<10}  {'Product':<7}  "
        f"{'IG Type':<14}  {'Notion':<8}  {'Likes':>5}  {'Comm':>5}  "
        f"{'Permalink':<28}  Caption"
    )
    print(header)
    print("  " + "─" * (len(header) - 2))

    for i, m in enumerate(media, start=1):
        print(
            f"  {i:>3}  {m.timestamp.strftime('%Y-%m-%d'):<10}  "
            f"{m.media_product_type:<7}  {m.media_type:<14}  "
            f"{m.notion_media_type:<8}  {m.like_count:>5}  {m.comments_count:>5}  "
            f"{m.short_permalink:<28}  {_truncate(m.caption, 50)}"
        )


def main() -> int:
    # ─── 1. Config ────────────────────────────────────────────────────
    try:
        settings = get_settings()
    except Exception as e:
        print(f"✖ Config load failed:\n  {e}", file=sys.stderr)
        return 1
    print("✓ Config loaded")
    _print_config(settings)
    print()

    # ─── 2. IG auth check ─────────────────────────────────────────────
    print("→ Checking IG access token...")
    try:
        account = fetch_account_info(settings)
    except InstagramAPIError as e:
        print(f"✖ IG auth check failed:\n  {e}", file=sys.stderr)
        return 1
    print("✓ IG token valid")
    _print_ig_account(account)
    print()

    # ─── 3. IG media fetch ────────────────────────────────────────────
    print(f"→ Fetching recent media (limit={settings.MAX_POSTS})...")
    try:
        media = fetch_media(settings)
    except InstagramAPIError as e:
        print(f"✖ Media fetch failed:\n  {e}", file=sys.stderr)
        return 1
    _print_media_table(media)
    print()

    print("Phase 3 complete. Phase 4 will fetch per-media insights.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
