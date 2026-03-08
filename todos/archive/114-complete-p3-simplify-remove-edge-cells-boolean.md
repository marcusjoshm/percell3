---
status: pending
priority: p3
issue_id: "114"
tags: [code-review, segment, simplification, yagni]
dependencies: []
---

# remove_edge_cells boolean is redundant with edge_margin

## Problem Statement

`SegmentationParams` has two fields for edge cell removal: `remove_edge_cells: bool` and `edge_margin: int`. The boolean is redundant — `edge_margin is not None` (if changed to `int | None = None`) already signals intent. This is a YAGNI violation that adds complexity to every call site.

## Findings

- **Found by:** code-simplicity-reviewer
- **Location:** `src/percell3/segment/base_segmenter.py:38-39`
- Every call site does `remove_edge_cells=True, edge_margin=N` — the bool never differs from `edge_margin is not None`

## Proposed Solutions

### Solution A: Change edge_margin to Optional
- `edge_margin: int | None = None` (drop `remove_edge_cells`)
- Engine checks `if params.edge_margin is not None`
- CLI builds kwargs with just `edge_margin=N`
- **Effort:** Small | **Risk:** Low | **Saves:** ~7 LOC

## Acceptance Criteria

- [ ] `remove_edge_cells` field removed from SegmentationParams
- [ ] `edge_margin: int | None = None` used instead
- [ ] Engine, CLI, and menu updated
- [ ] Tests still pass

## Work Log

- 2026-02-25: Identified during code review
