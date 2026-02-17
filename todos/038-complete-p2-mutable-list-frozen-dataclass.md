---
status: pending
priority: p2
issue_id: "038"
tags: [code-review, segment, type-safety]
dependencies: []
---

# Mutable `list` in Frozen Dataclass `SegmentationParams`

## Problem Statement

`SegmentationParams` is a frozen dataclass but `channels_cellpose: list[int] | None` allows mutation of the list contents even though field reassignment is blocked.

## Findings

- **File:** `src/percell3/segment/base_segmenter.py:37`
- `params.channels_cellpose.append(3)` would succeed on a "frozen" object
- Inconsistent with the immutability guarantee

## Proposed Solutions

Change to `tuple[int, ...] | None`:

```python
channels_cellpose: tuple[int, ...] | None = None
```

Callsite `params.channels_cellpose or [0, 0]` in cellpose_adapter.py still works (tuple is truthy when non-empty).

## Acceptance Criteria

- [ ] `channels_cellpose` typed as `tuple[int, ...] | None`
- [ ] All tests pass

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by kieran-python-reviewer.
