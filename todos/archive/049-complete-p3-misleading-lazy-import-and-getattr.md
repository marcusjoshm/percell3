---
status: pending
priority: p3
issue_id: "049"
tags: [code-review, cli, segment, simplification]
dependencies: []
---

# Misleading Lazy Import Comment + `__getattr__` Overkill

## Problem Statement

Two related issues: (1) `cli/main.py:16` comment says "lazy imports kept inside to speed up --help" but all 6 subcommand imports are eager at module level. (2) `segment/__init__.py:19-33` uses `__getattr__` lazy-loading for `SegmentationEngine`, `CellposeAdapter`, and `RoiImporter` — modules that import in microseconds. The only slow dependency (cellpose) is already lazy-imported inside `CellposeAdapter._get_model()`.

## Findings

- `cli/main.py:17-22`: Module-level imports, not lazy despite the comment
- `segment/__init__.py:19-33`: `__getattr__` pattern breaks IDE autocomplete and confuses stack traces
- The `segment/__init__.py` also eagerly imports `BaseSegmenter` (which imports numpy) while lazily importing `SegmentationEngine` (which doesn't) — inconsistent
- Real heavy deps (cellpose, torch) are already lazily imported where used

## Proposed Solutions

1. Fix the comment in `main.py` to "Heavy library imports are deferred to command execution"
2. Replace `__getattr__` with standard imports in `segment/__init__.py`

## Acceptance Criteria

- [ ] Comment accurately describes import strategy
- [ ] Standard imports in segment/__init__.py
- [ ] IDE autocomplete works for segment module symbols

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by kieran-python-reviewer, code-simplicity-reviewer, and performance-oracle.
