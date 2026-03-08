---
status: pending
priority: p2
issue_id: 165
tags: [code-review, security, image-calculator, defensive-programming]
dependencies: []
---

# Image Calculator missing defensive input validation

## Problem Statement

Multiple review agents flagged missing defensive validation in the Image Calculator plugin. While none are exploitable in this desktop app context, they produce confusing errors instead of clear domain-specific messages.

## Findings

### 1. No shape validation in `apply_two_channel` (security-sentinel, kieran-python-reviewer)
- **Location**: `src/percell3/plugins/builtin/image_calculator_core.py:99`
- If `image_a` and `image_b` have different shapes, numpy will either broadcast silently or raise an opaque error.

### 2. Non-finite constant values produce confusing FOV names (security-sentinel, learnings-researcher)
- **Location**: `src/percell3/plugins/builtin/image_calculator.py:154`
- `float('inf')` or `float('nan')` would pass validation and produce confusing derived FOV names.

### 3. No fov_id type validation (security-sentinel)
- **Location**: `src/percell3/plugins/builtin/image_calculator.py:115`
- If a caller passes a non-integer fov_id, the error comes from deep in ExperimentStore.

## Proposed Solutions

### Option A: Add guards at entry points (Recommended)

Add three validation checks:

```python
# In apply_two_channel:
if image_a.shape != image_b.shape:
    raise ValueError(f"Shape mismatch: image_a {image_a.shape} vs image_b {image_b.shape}")

# In run():
if constant is not None and not np.isfinite(constant):
    raise RuntimeError(f"'constant' must be a finite number, got {constant!r}")
```

- **Pros**: Clear error messages, minimal code
- **Cons**: None
- **Effort**: Small
- **Risk**: None

## Acceptance Criteria

- [ ] `apply_two_channel` raises ValueError on shape mismatch
- [ ] Plugin raises RuntimeError for non-finite constant values
- [ ] Tests added for each validation

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-03 | Created from code review | Validate at system boundaries per learnings |
