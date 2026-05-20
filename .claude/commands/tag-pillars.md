---
description: Tag blank Topics in the IG Content Notion database (requires Notion MCP)
argument-hint: [optional extra guidance for ambiguous cases]
---

# Pillar tagging for IG Content database

Read the user's Instagram Content database in Notion and tag any rows where
the `Topics` field is blank. Requires the Notion MCP server to be connected.

## Notion target

Use these exact IDs. **Do NOT call any Notion search tool** — fuzzy search
routinely picks the wrong database under the 2025-09-03 API split, and it
wastes turns. Hit the data source directly.

- **Data source ID:** `36a0f072-32ce-83c8-b0b8-07ef840059e5`
- **Database parent ID:** `ead0f072-32ce-821f-b351-81e7b6c0436d`
- **Workspace:** Personal Workspace (`joshbutjim`)

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
| `Topics` | select | **← THIS IS YOUR TARGET** | Options: Skills / Mindset / Passion / Lifestyle |
| `Status` | status | manual | Do not touch |
| `Mission` | select | manual | Do not touch |
| `Intensity` | select | manual | Do not touch |
| `Platform`, `Media Type`, etc. | various | auto | Do not touch |

## Pillar definitions

Classify each caption into EXACTLY ONE of these four options.
**The exact spelling matters** — Notion select options are case-sensitive.

- **Skills** — software engineering, AI, agentic workflows, Claude Code,
  BMAD, landing a job, navigating corporate, coaching athletics. The OS
  applied to craft and career.

- **Mindset** — multi-genre living, productivity, ethos-aligned action,
  finite energy, finance at 23, parallels across passions. The OS itself,
  named and taught.

- **Lifestyle** — hybrid athlete (lifting, running, sports), building in
  public, launching product, snowboarding, cooking, self-care. The OS
  applied to body and lived experience.

- **Passion** — faith (following Christ, church, prayer, Bible),
  relationships (girlfriend, family, teammates, friends). The OS applied
  to what matters most.

When a caption is ambiguous between two pillars, pick the primary frame
the caption leans into — the OS being demonstrated, not just the surface
topic. (e.g. a gym video that's really about "consistency beats waiting"
is **Mindset**, not Lifestyle.)

## Procedure

1. **Query** the data source. Filter for rows where `Topics` is empty
   AND `Caption` is non-empty. Quietly skip the rest.

2. **Classify** each filtered row. Build the proposed list in memory.

3. **Show the user the full proposal** as a table before writing anything:

   ```
   #   caption snippet (60 chars)                  → proposed pillar
   ────────────────────────────────────────────────────────────────
   1   product details coming soon                 → Skills
   2   we've come full circle                      → Mindset
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
