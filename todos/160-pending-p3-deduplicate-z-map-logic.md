---
status: pending
priority: p3
issue_id: 160
tags: [code-review, quality, io]
dependencies: []
---

# Deduplicate Z-Map Logic in _read_and_stitch_tiles

## Problem Statement

`_read_and_stitch_tiles` (engine.py:279-283) contains inline Z-grouping logic that duplicates `_group_by_z` (engine.py:295-304). Should reuse existing method.

## Findings

- **Source**: code-simplicity-reviewer
- **Location**: `src/percell3/io/engine.py:279-283`

## Proposed Solutions

Replace inline dict comprehension with `self._group_by_z(tile_files)`. Saves ~4 lines.

## Acceptance Criteria

- [ ] `_read_and_stitch_tiles` calls `self._group_by_z()` instead of inline logic

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | |
