---
status: pending
priority: p3
issue_id: "040"
tags: [code-review, segment, simplification]
dependencies: []
---

# `segment_batch()` Is Dead Code (YAGNI)

## Problem Statement

`segment_batch()` is defined on `BaseSegmenter` ABC and implemented in `CellposeAdapter`, but never called by `SegmentationEngine` or any production code. Only test mocks exercise it.

## Findings

- `base_segmenter.py:108-119` — abstract method
- `cellpose_adapter.py:73-97` — implementation
- `conftest.py:30-33, 42-45` — mock implementations
- Engine processes regions one-at-a-time in a for loop

## Proposed Solutions

Remove `segment_batch` from ABC, adapter, and mocks. ~77 LOC removed. Can be trivially re-added when GPU batching is actually needed.

## Acceptance Criteria

- [ ] `segment_batch` removed from ABC, adapter, mocks, and tests
- [ ] All remaining tests pass

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by code-simplicity-reviewer. Classic YAGNI violation.
