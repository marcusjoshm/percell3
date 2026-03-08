---
status: pending
priority: p3
issue_id: 161
tags: [code-review, architecture, io]
dependencies: []
---

# Re-export stitch_tiles and build_tile_grid from percell3.io

## Problem Statement

`stitch_tiles` and `build_tile_grid` are public functions with full docstrings, but they are not exported from `percell3.io.__init__`. Programmatic users must import from `percell3.io.engine` directly.

## Findings

- **Source**: agent-native-reviewer
- **Location**: `src/percell3/io/__init__.py`

## Proposed Solutions

Add both to `__init__.py` imports and `__all__`.

## Acceptance Criteria

- [ ] `from percell3.io import stitch_tiles, build_tile_grid` works

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | |
