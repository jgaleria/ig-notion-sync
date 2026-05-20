# CLAUDE.md

Context for Claude Code working in this repo. Read this before editing.

## What this is

A local Python CLI (`ig-sync`) that pulls Instagram post metrics via the Graph
API and upserts them into a Notion `Content` database. Personal tool, single user
(joshbutjim), runs on demand from the terminal.

No scheduling, no web service, no AI/LLM dependency in the script itself.
Pillar tagging is done separately via the Notion MCP from the Claude app.

## How to use it

```bash
cd /Users/jgaleria/Documents/GitHub/social-media/ig-notion-sync

uv run ig-sync                 # live sync — fetch + upsert all
uv run ig-sync --dry-run       # compute plan + print diff, no writes
uv run ig-sync --limit 3       # cap writes to N posts (testing)
```

After every run:
- Console shows the full plan, per-post action, and a summary
- `logs/last_run.json` is overwritten with the structured stats
- Exit code 0 = success, 1 = any failure (token expired, network, etc.)

## What it can be used for

1. **Daily metric refresh** — re-run any time you want fresh `Reach`, `Total views`,
   `Saves`, `Shares`, `Avg Watch Time` etc. on existing rows. Idempotent.
2. **Backfilling IG Media IDs** — first run after manual planning links Notion rows
   to IG posts by permalink and stamps the IG Media ID for O(1) future lookups.
3. **Picking up new posts** — anything you posted on IG that isn't in Notion yet
   gets created with `Status=Done`, `Platform=Instagram`, all metrics populated,
   `Topics`/`Mission`/`Intensity` left blank for manual tagging.
4. **Token health check** — config + auth check runs first. If the IG token is
   expired (code 190) the script exits 1 before doing anything.
5. **Dry-run diffs** — `--dry-run` previews what would change without touching
   Notion. Useful before bulk runs or after schema/spec changes.
6. **Pillar tagging follow-up** — after a sync, ask Claude (this app) to read the
   Notion DB via MCP and tag any rows with blank `Topics` based on the captions.

## Architecture map

| File | Responsibility |
|---|---|
| `src/main.py` | CLI entrypoint. Orchestrates the 6-step pipeline + finalize. |
| `src/config.py` | Pydantic Settings, loads `.env`, exposes `get_settings()` singleton. |
| `src/instagram.py` | IG Graph API client: `fetch_account_info`, `fetch_media`, `fetch_insights`. Raises `InstagramAPIError` / `InsightsUnavailableError`. |
| `src/notion.py` | Notion API client + upsert logic. Pure `build_upsert()`, side-effecting `apply_upsert()`. Property serializers (`_title`, `_rich_text`, etc.) and `normalize_permalink()`. |
| `src/models.py` | Pydantic models: `IGMedia`, `IGInsights`, `NotionRow`, `UpsertIntent`. Property helpers like `notion_media_type`, `avg_watch_time_s`. |
| `tests/test_upsert_logic.py` | Stub (not yet populated). Should cover `build_upsert()` field-write rules. |
| `logs/last_run.json` | Latest run's stats. Sorted keys, diff-friendly. |

## Things to keep in mind

### Hard constraints

1. **`Name`, `Topics`, `Mission`, `Intensity`, `Inspo` are NEVER written by this
   script.** Manual planning data. If you "fix" anything here to make the script
   set them, you're breaking the contract.

2. **`Status` only auto-bumps from `{blank, Editing, Record}` → `Done`.**
   `Idea`, `Ideas for later`, `Draft` are protected — the script will not touch
   them even if the row matches an IG post. The protected statuses are listed
   in `notion._STATUS_OVERWRITABLE`.

3. **`build_upsert()` is a pure function.** No I/O, no global state. This is
   intentional so the field-write rules are testable in isolation. Don't put
   `httpx` calls or `datetime.now()` (wait, it has datetime.now — for
   `Last Synced`, that's fine — but no API calls) inside it.

4. **`apply_upsert()` is the only side-effecting half.** It checks
   `settings.DRY_RUN` and short-circuits if true. Sleeps 0.4s after each write
   to stay under Notion's 3 req/sec limit.

5. **Empty IG metric ≠ zero.** When IG returns no value for a metric, we treat
   it as `None` (Notion column stays at whatever it was). When IG returns `0`,
   we write `0`. The `if insights.X is not None` guards in `build_upsert` enforce
   this.

### Meta-deprecated columns (stay blank, fill manually)

Already documented in README + commit `b0fdd62`:

- `New Followers` — IG removed per-media `follows` metric
- `Views follower %` / `Views non-follower %` — IG removed `breakdown=follow_type`
  from per-media insights
- `Video Duration (s)` / `Skip Rate (%)` — not in IG Graph API; would need
  `ffprobe` on `media_url` (out of scope)

If a future Meta API change restores any of these, the place to add them is
`fetch_insights()` and the corresponding `build_upsert` block.

### Operational gotchas

- **IG token expires every 60 days.** `META_APP_ID` + `META_APP_SECRET` in `.env`
  are kept specifically to re-issue. The refresh curl is in README. The script
  exits 1 with "Access token rejected (code 190)" when the token is dead.
- **Thumbnail URLs are signed CDN links that expire in a few days.** Each run
  refreshes them — no problem if you sync regularly. If you stop syncing for
  a week, thumbnails will 404.
- **Insights for a just-published post (~30min) aren't ready yet.** Script
  catches `InsightsUnavailableError` and degrades that one post to identity-only
  write. Next run picks up the metrics.
- **Stories are filtered client-side.** They have a 24h lifecycle and don't fit
  the Content DB model.
- **The script does NOT delete Notion rows.** If you delete an IG post but the
  Notion row exists, the row is left alone (no match → no action). Hand-clean
  if needed.
- **`uv run ig-sync` after editing `pyproject.toml`** may need
  `uv sync --reinstall-package ig-notion-sync` to refresh the console script
  entry point. Pure code edits inside `src/` don't need it.

### Environment

- Python 3.14.4 installed via Homebrew; `requires-python = ">=3.11"` in pyproject
  so it stays portable.
- All deps locked in `uv.lock`. To upgrade: `uv lock --upgrade` then `uv sync`.
- Single workspace, single user — no auth/multitenancy concerns.
- `.env` contains live secrets (IG token, Notion token, App secret). Gitignored.

## Common asks (likely future tasks)

- **"Write tests for `build_upsert`"** — populate `tests/test_upsert_logic.py`.
  Stub each field-write rule from the spec, drive with synthetic `IGMedia`,
  `IGInsights`, `NotionRow` fixtures, assert on `intent.properties` shape.
- **"Add ffprobe for Video Duration"** — add system dep, shell out to `ffprobe`
  on `media.media_url`, populate `Video Duration (s)` and derive `Skip Rate (%)`.
  ~30 min of work, fairly contained to `instagram.py` or a new `media_probe.py`.
- **"Add TikTok / YouTube"** — the Notion schema already has `Platform` select
  options for both. Each would need its own API client + a per-platform
  `build_upsert` adapter. Probably want to refactor `main.py` first into
  per-platform pipelines.
- **"Auto-tag Topics inside the script"** — would add back the `tagger.py` we
  intentionally cut. Adds `anthropic` dep and an API key. Generally don't —
  doing it via the Claude app + Notion MCP is the chosen architecture.
