"""Entry point for the ig-sync CLI.

Phase 2 — wires in the IG auth check.
Subsequent phases will add Notion read, write (dry-run), write (real),
and the run summary.
"""

from __future__ import annotations

import sys

from src.config import Settings, get_settings
from src.instagram import InstagramAPIError, fetch_account_info


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
    print(f"  Media count:    {account.get('media_count')}")


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

    print("Phase 2 complete. Phase 3 will list recent media.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
