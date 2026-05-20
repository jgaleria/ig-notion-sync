"""Unit tests for the field-write rules in src.notion.

Phase 6 will populate this — verifies that:
- existing rows preserve Name, Status (when not blank/Editing/Record), Topics
- Caption, Thumbnail, Media Type, all metrics are overwritten
- Last Synced is always set
- new rows get Status=Done, Mission blank, Topics blank
"""
