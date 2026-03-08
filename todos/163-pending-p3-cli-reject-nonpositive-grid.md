---
status: pending
priority: p3
issue_id: 163
tags: [code-review, quality, cli]
dependencies: []
---

# CLI _parse_tile_options Should Reject Non-Positive Integers Early

## Problem Statement

`_parse_tile_options` in import_cmd.py accepts negative or zero grid values via `int()` parsing. These are caught downstream by `TileConfig.__post_init__`, but the error message is confusing since it comes from the model layer rather than the CLI layer.

## Findings

- **Source**: security-sentinel
- **Location**: `src/percell3/cli/import_cmd.py:508-525`

## Proposed Solutions

Add early `if grid_cols < 1 or grid_rows < 1` check in `_parse_tile_options` with a clear CLI error message.

## Acceptance Criteria

- [ ] `--tile-grid 0x2` shows CLI-level error message
- [ ] `--tile-grid -3x2` shows CLI-level error message

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | |
