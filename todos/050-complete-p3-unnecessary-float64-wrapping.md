---
status: pending
priority: p3
issue_id: "050"
tags: [code-review, segment, simplification]
dependencies: []
---

# Unnecessary `np.float64()` Wrapping in LabelProcessor

## Problem Statement

`label_processor.py:62-65,72-74` wraps Python floats in `np.float64()` for arithmetic. Since `area_pixels` and `perimeter` are already Python `float` (from `float(prop.area)` and `float(prop.perimeter)`), Python float arithmetic already uses IEEE 754 double precision (equivalent to float64). The wrapping is noise.

## Findings

- `label_processor.py:65`: `float(np.float64(area_pixels) * np.float64(pixel_size_um) ** 2)`
- `label_processor.py:73`: `float(4.0 * math.pi * np.float64(area_pixels) / np.float64(perimeter) ** 2)`
- Comment "Use float64 for arithmetic to avoid integer overflow" is misleading — these are already floats

## Proposed Solutions

Simplify to plain Python arithmetic:
```python
area_um2 = area_pixels * pixel_size_um ** 2
circularity = 4.0 * math.pi * area_pixels / perimeter ** 2
```

## Acceptance Criteria

- [ ] `np.float64()` wrappers removed
- [ ] Misleading comment removed or corrected
- [ ] All tests pass (values unchanged)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by code-simplicity-reviewer.
