---
status: pending
priority: p3
issue_id: 169
tags: [code-review, quality, image-calculator]
dependencies: []
---

# Image Calculator type safety and dispatch improvements

## Problem Statement

The operation parameter is a bare `str` throughout the codebase. Using Python 3.10+ StrEnum or Literal types would catch invalid operations at type-check time rather than runtime.

## Findings

### 1. No type constraint on operation parameter (kieran-python-reviewer #1)
- **Location**: `src/percell3/plugins/builtin/image_calculator_core.py:12-16`
- `OPERATIONS` is a plain tuple of strings. Nothing prevents passing a misspelled operation.
- Fix: Use `StrEnum` or `typing.Literal` for the operation type.

### 2. If/elif dispatch chain could be dict-based (kieran-python-reviewer #2, code-simplicity-reviewer)
- **Location**: `src/percell3/plugins/builtin/image_calculator_core.py:36-68`
- 11-branch if/elif chain could be a dict lookup for the simple arithmetic ops.

### 3. _get_dtype_range doesn't handle bool dtype (kieran-python-reviewer #7)
- **Location**: `src/percell3/plugins/builtin/image_calculator_core.py:19-25`
- Would fall through to `np.finfo(np.bool_)` which raises. Add explicit float subtype check.

## Proposed Solutions

### Option A: StrEnum + dict dispatch (Recommended)

```python
class Operation(StrEnum):
    ADD = "add"
    SUBTRACT = "subtract"
    # ...
```

- **Effort**: Small
- **Risk**: None (backward compatible since StrEnum values are strings)

## Acceptance Criteria

- [ ] Operation type uses StrEnum or Literal
- [ ] Simple arithmetic ops use dict-based dispatch
- [ ] `_get_dtype_range` guards against non-numeric dtypes

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-03 | Created from code review | StrEnum available in Python 3.10+ |
