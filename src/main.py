"""Entry point for the ig-sync CLI.

Phase 1 stub — only verifies that config loads cleanly. Subsequent phases
will wire in IG fetch, Notion read/write, and the run summary.
"""

from __future__ import annotations

import sys

from src.config import get_settings


def main() -> int:
    try:
        settings = get_settings()
    except Exception as e:  # ValidationError or file-not-found
        print(f"❌ Config load failed:\n   {e}", file=sys.stderr)
        return 1

    print("✅ Config loaded")
    print(f"   IG_USER_ID:            {settings.IG_USER_ID}")
    print(f"   IG_GRAPH_API_VERSION:  {settings.IG_GRAPH_API_VERSION}")
    print(f"   NOTION_DATA_SOURCE_ID: {settings.NOTION_DATA_SOURCE_ID}")
    print(f"   NOTION_VERSION:        {settings.NOTION_VERSION}")
    print(f"   DRY_RUN:               {settings.DRY_RUN}")
    print(f"   MAX_POSTS:             {settings.MAX_POSTS}")
    print()
    print("Phase 1 (scaffolding) complete. Phase 2 will add the IG auth check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
