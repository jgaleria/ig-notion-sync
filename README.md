# ig-notion-sync

Local Python script that pulls Instagram post metrics via the Graph API and
upserts them into a Notion `Content` database. Run on demand from the terminal.

Pillar tagging is handled separately via Claude in the Notion MCP — the script
stays a pure data pipeline.

## Setting this up for yourself?

See **[SETUP.md](./SETUP.md)** — a single standalone guide (also distributed
as a PDF) covering prerequisites, Meta dev app, Notion schema, env config,
first sync, and scheduling. Has two paths at each step: paste-in Claude Code
prompts (for non-technical users) and equivalent terminal commands.

Need someone to do it for you? Consult: `<CONSULT_BOOKING_URL_GOES_HERE>`.

The rest of this README is the day-to-day operating reference for the script.

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

### Aspirational — requested, may be dropped if your account/API version rejects
`New Followers` (IG `follows` metric — many accounts get code 100),
`Skip Rate (%)` (IG `reels_skip_rate`, REELS only — needs Graph API v22.0+;
the default `v21.0` will reject it). `fetch_insights` strips any metric the
API refuses and continues, so a rejection just leaves the column at its
prior value. The end-of-run summary prints "Metrics auto-dropped: …" when
this happens. To try skip rate, set `IG_GRAPH_API_VERSION=v22.0` in `.env`.

### Never overwritten (manual fields)
`Name` (your title — set during planning), `Topics` (Claude-tag via MCP),
`Mission`, `Intensity`, `Inspo`.

### Stays blank — IG Graph API still won't expose
`Views follower %`, `Views non-follower %` — per-media `breakdown=follow_type`
is not available (Instagram dashboard computes this server-side from data the
API doesn't return).
`Video Duration (s)` — not in IG Graph API; would need `ffprobe`.

See commit `b0fdd62` for the original Phase-4 deprecation context.

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
