---
status: pending
priority: p3
issue_id: 162
tags: [code-review, quality, cli]
dependencies: []
---

# Tile-Count Mismatch Warning Missing from CLI Path

## Problem Statement

The interactive menu warns when `grid_rows * grid_cols != num_tiles` (menu.py:1128-1133), but the CLI path does not. An agent/script using `--tile-grid` gets no warning before the engine raises a hard ValueError at stitch time.

## Findings

- **Source**: agent-native-reviewer
- **Location**: `src/percell3/cli/import_cmd.py` (missing), `src/percell3/cli/menu.py:1128-1133` (present)

## Proposed Solutions

Add pre-flight validation in `_run_import` after scanning but before plan execution.

## Acceptance Criteria

- [ ] CLI import with mismatched tile count shows warning before execution
- [ ] Warning matches interactive menu behavior

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | |
