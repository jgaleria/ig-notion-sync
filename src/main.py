"""Entry point for the ig-sync CLI.

Phase 3 — adds media listing on top of the Phase 2 auth check.
"""

from __future__ import annotations

import sys
import textwrap
from collections import Counter

from src.config import Settings, get_settings
from src.instagram import (
    InsightsUnavailableError,
    InstagramAPIError,
    fetch_account_info,
    fetch_insights,
    fetch_media,
)
from src.models import IGInsights, IGMedia, NotionRow
from src.notion import (
    NotionAPIError,
    extract_row,
    normalize_permalink,
    query_data_source,
)


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


def _print_caption(caption: str | None) -> None:
    """Caption on its own indented line(s), wrapped at ~100 cols.

    max_lines caps runaway paragraph captions so the table stays scannable.
    Newlines in the source caption are preserved as paragraph breaks.
    """
    if not caption:
        return
    paragraphs = caption.strip().split("\n")
    wrapper = textwrap.TextWrapper(
        width=100,
        initial_indent="         ",
        subsequent_indent="         ",
        max_lines=8,
        placeholder=" …",
        break_long_words=False,
    )
    for para in paragraphs:
        if not para.strip():
            print()
            continue
        print(wrapper.fill(para))


def _print_media_table(media: list[IGMedia]) -> None:
    counts = Counter(m.media_product_type for m in media)
    breakdown = ", ".join(f"{k}={v}" for k, v in counts.most_common())
    print(f"Fetched {len(media)} media items  ({breakdown})")
    print()

    header = (
        f"  {'#':>3}  {'Date':<10}  {'Product':<7}  "
        f"{'IG Type':<14}  {'Notion':<8}  {'Likes':>5}  {'Comm':>5}  Permalink"
    )
    print(header)
    print("  " + "─" * 90)

    for i, m in enumerate(media, start=1):
        print(
            f"  {i:>3}  {m.timestamp.strftime('%Y-%m-%d'):<10}  "
            f"{m.media_product_type:<7}  {m.media_type:<14}  "
            f"{m.notion_media_type:<8}  {m.like_count:>5}  {m.comments_count:>5}  "
            f"{m.short_permalink}"
        )
        _print_caption(m.caption)


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

    # ─── 4. IG insights — sample one Reel and one carousel ────────────
    print("→ Fetching insights for sample posts (one per metric branch)...")
    samples: list[IGMedia] = []
    newest_reel = next(
        (m for m in media if m.media_product_type == "REELS"), None
    )
    newest_carousel = next(
        (m for m in media if m.media_type == "CAROUSEL_ALBUM"), None
    )
    if newest_reel:
        samples.append(newest_reel)
    if newest_carousel:
        samples.append(newest_carousel)
    if not samples:
        print("  (no eligible media to sample)")

    for m in samples:
        print()
        try:
            insights = fetch_insights(settings, m)
        except InsightsUnavailableError as e:
            print(f"  ⚠ {e}", file=sys.stderr)
            continue
        except InstagramAPIError as e:
            print(f"  ✖ Insights fetch failed for {m.id}: {e}", file=sys.stderr)
            return 1
        _print_combined(m, insights)

    print()

    # ─── 5. Notion read + match ───────────────────────────────────────
    print("→ Querying Notion data source (all rows)...")
    try:
        pages = query_data_source(settings)
    except NotionAPIError as e:
        print(f"✖ Notion query failed:\n  {e}", file=sys.stderr)
        return 1
    rows = [extract_row(p) for p in pages]
    print(f"✓ Fetched {len(rows)} Notion rows")
    _print_match_diff(media, rows)
    print()

    print("Phase 5 complete. Phase 6 will do dry-run upsert.")
    return 0


def _print_match_diff(media: list[IGMedia], rows: list[NotionRow]) -> None:
    """Build match indexes from Notion rows, then report what would happen
    per IG post in Phase 6+. No writes here."""
    # Build indexes
    by_ig_id: dict[str, NotionRow] = {}
    by_link: dict[str, NotionRow] = {}
    for r in rows:
        if r.ig_media_id:
            by_ig_id[r.ig_media_id] = r
        norm = normalize_permalink(r.permalink)
        if norm:
            by_link[norm] = r

    print(
        f"  Indexes: {len(by_ig_id)} rows have IG Media ID, "
        f"{len(by_link)} rows have a permalink"
    )
    print()

    # Status breakdown for situational awareness
    status_counts = Counter(r.status or "(blank)" for r in rows)
    print(f"  Status breakdown across all {len(rows)} rows:")
    for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"    {c:>4}  {s}")
    print()

    # Per-IG-post match
    header = (
        f"  {'#':>3}  {'Match':<18}  {'IG Date':<10}  "
        f"{'Permalink':<30}  Notion row → status / topics"
    )
    print(header)
    print("  " + "─" * (len(header) - 2))

    outcomes: Counter[str] = Counter()
    for i, m in enumerate(media, start=1):
        row: NotionRow | None = None
        outcome: str
        if m.id in by_ig_id:
            row = by_ig_id[m.id]
            outcome = "MATCH (id)"
        else:
            norm = normalize_permalink(m.permalink)
            if norm and norm in by_link:
                row = by_link[norm]
                outcome = "MATCH (link+backfill)" if not row.ig_media_id else "MATCH (link)"
            else:
                outcome = "NEW (would create)"
        outcomes[outcome] += 1

        if row:
            row_summary = (
                f"{row.name or '(unnamed)'}  →  "
                f"status={row.status or '∅'}, topics={row.topics or '∅'}"
            )
        else:
            row_summary = "(no existing row)"

        print(
            f"  {i:>3}  {outcome:<18}  "
            f"{m.timestamp.strftime('%Y-%m-%d'):<10}  "
            f"{m.short_permalink:<30}  {row_summary}"
        )

    print()
    print("  Match summary:")
    for outcome, c in outcomes.most_common():
        print(f"    {c:>3}  {outcome}")


def _fmt_num(n: int | float | None, percent: bool = False) -> str:
    if n is None:
        return "—"
    if percent:
        return f"{n * 100:.1f}%"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _print_combined(media: IGMedia, ins: IGInsights) -> None:
    """One post end-to-end: identity from /media, metrics from /insights."""
    print(f"  ┌─ {media.notion_media_type.upper():9} {media.short_permalink}")
    print(f"  │  Posted:    {media.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"  │  Caption:   {(media.caption or '').splitlines()[0][:80] if media.caption else '—'}")
    print(f"  │")
    print(f"  │  ── Identity (from /media) ──")
    print(f"  │    Likes:        {_fmt_num(media.like_count)}")
    print(f"  │    Comments:     {_fmt_num(media.comments_count)}")
    print(f"  │")
    print(f"  │  ── Insights (from /insights) ──")
    print(f"  │    Reach:                  {_fmt_num(ins.reach)}")
    print(f"  │    Total views:            {_fmt_num(ins.views)}")
    print(f"  │    Saves:                  {_fmt_num(ins.saved)}")
    print(f"  │    Shares:                 {_fmt_num(ins.shares)}")
    print(f"  │    Total interactions:     {_fmt_num(ins.total_interactions)}  (not written to Notion)")
    if media.media_product_type == "REELS":
        print(f"  │    Avg watch time (s):    {_fmt_num(ins.avg_watch_time_s)}")
        print(f"  │    Total watch time (s):  {_fmt_num(ins.total_watch_time_s)}")
    print(f"  │")
    print(f"  │  ── Not written (Meta deprecated) ──")
    print(f"  │    New followers:           per-media `follows` removed → leave Notion col blank")
    print(f"  │    Views follower %:        per-media follow_type breakdown removed → leave blank")
    print(f"  └─")


if __name__ == "__main__":
    sys.exit(main())
