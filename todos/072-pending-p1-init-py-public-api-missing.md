---
status: pending
priority: p1
issue_id: "072"
tags: [plan-review, architecture, planning-gap]
dependencies: []
---

# __init__.py Public API Exports Missing From Plan

## Problem Statement

The plan does not mention updating __init__.py for any module. src/percell3/core/__init__.py currently exports RegionInfo and RegionNotFoundError in __all__. Without updating these, every external import breaks.

## Findings

- **Python reviewer**: "from percell3.core import RegionInfo will break. Add __init__.py updates to Phase 1.1 (rename) and Phase 2 (add BioRepInfo)."
- Also applies to io/__init__.py if it exports IO model classes.

## Proposed Solutions

### A) Add __init__.py updates to the plan

Phase 1.1: rename `RegionInfo` -> `FovInfo`, `RegionNotFoundError` -> `FovNotFoundError` in __init__.py imports and __all__. Phase 2: add `BioRepInfo`, `BioRepNotFoundError` to __init__.py.

- **Pros**: Complete.
- **Cons**: None.
- **Effort**: Small.
- **Risk**: None.

## Technical Details

Affected files:
- `src/percell3/core/__init__.py`
- Possibly `src/percell3/io/__init__.py`
- Possibly `src/percell3/segment/__init__.py`

## Acceptance Criteria

- [ ] Plan includes __init__.py updates in Phase 1 and Phase 2
- [ ] FovInfo, FovNotFoundError exported from core __init__.py
- [ ] BioRepInfo, BioRepNotFoundError exported from core __init__.py (Phase 2)

## Work Log

- 2026-02-17 — Identified by Python reviewer during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
