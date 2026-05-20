# ig-notion-sync

Local Python script that pulls Instagram post metrics via the Graph API and
upserts them into a Notion `Content` database. Runs on demand from the terminal.

Pillar tagging is handled separately via Claude in the Notion MCP — keeping
this script as a pure data pipeline.

## Stack

- Python 3.11+
- `httpx`, `pydantic`, `pydantic-settings`, `python-dotenv`
- Managed with [uv](https://docs.astral.sh/uv/)

## Setup

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install deps and create venv
cd ig-notion-sync
uv sync

# Copy and fill in the env file (already populated for first run)
cp .env.example .env
```

## Run

```bash
uv run ig-sync
# or, equivalently:
uv run python -m src.main
```

## Project layout

```
ig-notion-sync/
├── .env                  # secrets, gitignored
├── .env.example          # template
├── pyproject.toml
├── README.md
├── src/
│   ├── __init__.py
│   ├── main.py           # CLI entry point
│   ├── config.py         # Pydantic Settings, loads .env
│   ├── instagram.py      # IG Graph API client
│   ├── notion.py         # Notion API client + upsert logic
│   └── models.py         # shared dataclasses / pydantic models
├── tests/
│   └── test_upsert_logic.py
└── logs/
    └── last_run.json     # written each run
```

## Build phases

The script is being built phase by phase, with verification between each.

- [x] **1. Scaffolding** — file layout, deps, config loader
- [ ] **2. Config + IG auth check** — `/me` call to confirm token
- [ ] **3. IG media fetch** — list recent posts
- [ ] **4. IG insights fetch** — per-media metrics with REELS/FEED branching + follower breakdown
- [ ] **5. Notion read** — query data source, match by IG Media ID / permalink
- [ ] **6. Notion write (dry-run)** — upsert logic with `DRY_RUN=true`
- [ ] **7. Notion write — 1 post** — flip dry-run, cap to 1
- [ ] **8. Notion write — all posts** — full run
- [ ] **9. Run summary + last_run.json**

## Token refresh

`IG_ACCESS_TOKEN` is good for 60 days. Re-issue before expiry with:

```bash
curl -sG "https://graph.facebook.com/v21.0/oauth/access_token" \
  -d "grant_type=fb_exchange_token" \
  -d "client_id=${META_APP_ID}" \
  -d "client_secret=${META_APP_SECRET}" \
  -d "fb_exchange_token=${IG_ACCESS_TOKEN}"
```
