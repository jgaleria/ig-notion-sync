---
description: Tag blank Topics in the IG Content Notion database (requires Notion MCP)
argument-hint: [optional extra guidance for ambiguous cases]
---

# Pillar tagging for IG Content database

Template for a Claude Code slash command that classifies Instagram posts into
your own content pillars via the Notion MCP. **This file is a placeholder** —
fill in the bracketed sections before using.

The pattern: after `uv run ig-sync` populates Notion rows with captions, run
this command in the Claude app to auto-tag the `Topics` column. The sync
script intentionally does no LLM work; classification lives here so the script
stays dependency-free.

## Notion target

Replace these with your own IDs from the Notion API or your database URL.
**Do NOT call any Notion search tool** — fuzzy search routinely picks the
wrong database under the 2025-09-03 API split. Hit the data source directly.

- **Data source ID:** `<YOUR_DATA_SOURCE_ID>`
- **Database parent ID:** `<YOUR_DATABASE_PARENT_ID>`

Use the Notion MCP fetch tool with the data source ID directly. If your MCP
exposes a `notion-fetch` or equivalent that takes a URL, you can also pass:
`https://www.notion.so/<data-source-id>`.

## Schema cheat-sheet (so you don't guess column names)

| Column | Type | Auto? | Notes |
|---|---|---|---|
| `Name` | title | manual | Never overwrite |
| `IG Media ID` | text | auto (sync script) | Unique key |
| `Caption` | text | auto (sync script) | **Read this to classify** |
| `Last Synced` | date | auto | |
| `Topics` | select | **← THIS IS YOUR TARGET** | Define your own options below |
| `Status` | status | manual | Do not touch |
| `Mission` | select | manual | Do not touch |
| `Intensity` | select | manual | Do not touch |
| `Platform`, `Media Type`, etc. | various | auto | Do not touch |

## Pillar definitions

Replace this section with your own pillar taxonomy. Each post should fit
EXACTLY ONE option. **Exact spelling matters** — Notion select options are
case-sensitive, so match what you've configured in the database.

- **`<PILLAR_1>`** — short description of what this pillar covers.
- **`<PILLAR_2>`** — short description.
- **`<PILLAR_3>`** — short description.
- **`<PILLAR_4>`** — short description.

When a caption is ambiguous, prefer the primary frame the caption leans into
rather than the surface topic.

## Procedure

1. **Query** the data source. Filter for rows where `Topics` is empty
   AND `Caption` is non-empty. Quietly skip the rest.

2. **Classify** each filtered row. Build the proposed list in memory.

3. **Show the user the full proposal** as a table before writing anything:

   ```
   #   caption snippet (60 chars)                  → proposed pillar
   ────────────────────────────────────────────────────────────────
   1   product details coming soon                 → <PILLAR_1>
   2   we've come full circle                      → <PILLAR_2>
   ...
   ```

   Flag any ambiguous calls with a `?` so the user can review those first.

4. **Wait for confirmation**, or for the user to call out specific rows
   to change.

5. **Write** by updating each row's `Topics` property via the Notion MCP
   update tool. Touch ONLY that field.

## Hard rules

- **Never** touch `Name`, `Status`, `Mission`, `Intensity`, `Caption`,
  or any auto-populated field. The sync script owns those.
- **Never** overwrite an existing non-empty `Topics` value. Even if you'd
  classify it differently, the user already decided.
- **Never** tag a row with no caption.
- **Always** show the plan before writing. Tagging is mostly subjective and
  the user will want to override at least a few.

## Extra guidance from user

$ARGUMENTS
