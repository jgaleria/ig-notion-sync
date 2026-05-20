# ig-notion-sync

Local Python script that pulls Instagram post metrics via the Graph API and
upserts them into a Notion `Content` database. Run on demand from the terminal.

Pillar tagging is handled separately via Claude in the Notion MCP — the script
stays a pure data pipeline.

## Stack

- Python 3.11+ (developed on 3.14)
- `httpx`, `pydantic`, `pydantic-settings`, `python-dotenv`
- Managed with [uv](https://docs.astral.sh/uv/)

## Setup

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone, sync, and configure
cd ig-notion-sync
uv sync
cp .env.example .env   # then fill in the values
```

## Day-to-day use

```bash
# Sync (writes to Notion, respects DRY_RUN in .env)
uv run ig-sync

# Dry-run override — compute plan, print diff, no writes
uv run ig-sync --dry-run

# Test write capped to N posts
uv run ig-sync --limit 3
```

After each run:
- Console prints the per-post diff + a final run summary
- `logs/last_run.json` is overwritten with structured stats from the run

## Project layout

```
ig-notion-sync/
├── .env                  # secrets, gitignored
├── .env.example          # template
├── pyproject.toml        # uv + hatchling, `ig-sync` console script
├── README.md
├── src/
│   ├── __init__.py
│   ├── main.py           # CLI entry, orchestrates the pipeline
│   ├── config.py         # Pydantic Settings, loads .env
│   ├── instagram.py      # IG Graph API client (auth, media, insights)
│   ├── notion.py         # Notion API client + upsert logic
│   └── models.py         # IGMedia, IGInsights, NotionRow, UpsertIntent
├── tests/
│   └── test_upsert_logic.py
└── logs/
    └── last_run.json     # latest run's structured summary
```

## Build phases (all complete)

- [x] **1. Scaffolding** — file layout, deps, config loader
- [x] **2. Config + IG auth check** — `/me` call confirms token
- [x] **3. IG media fetch** — list recent posts (newest first, stories filtered)
- [x] **4. IG insights fetch** — per-media metrics with REELS/FEED branching
- [x] **5. Notion read** — query data source, match by ID + permalink
- [x] **6. Notion write (dry-run)** — upsert logic with `DRY_RUN=true`
- [x] **7. Notion write — 1 post** — `--limit 1` real write, verified
- [x] **8. Notion write — full** — all 31 posts, idempotent on re-run
- [x] **9. Run summary + last_run.json**

## What gets written, what stays manual

### Auto-populated from IG every run
`IG Media ID`, `Caption`, `Last Synced`, `Publication Date` (if blank),
`Link to post` (if blank), `Thumbnail`, `Platform` (if blank),
`Media Type`, `Status` (→ Done only if currently blank / Editing / Record),
`Total views`, `Reach`, `Likes`, `Comments`, `Saves`, `Shares`,
`Average Watch Time (s)` (reels only), `Total Watch Time (s)` (reels only).

### Never overwritten (manual fields)
`Name` (your title — set during planning), `Topics` (Claude-tag via MCP),
`Mission`, `Intensity`, `Inspo`.

### Stays blank — IG Graph API limitations (Meta deprecated)
`New Followers`, `Views follower %`, `Views non-follower %` (formula),
`Video Duration (s)`, `Skip Rate (%)` (derived).

Details on these in commit `b0fdd62` (Phase 4).

## Token refresh

`IG_ACCESS_TOKEN` is good for ~60 days. Re-issue before expiry:

```bash
curl -sG "https://graph.facebook.com/v21.0/oauth/access_token" \
  -d "grant_type=fb_exchange_token" \
  -d "client_id=${META_APP_ID}" \
  -d "client_secret=${META_APP_SECRET}" \
  -d "fb_exchange_token=${IG_ACCESS_TOKEN}"
```

The script exits 1 with a clear "code 190" message when the token is rejected,
so you'll know when it's time to refresh.
