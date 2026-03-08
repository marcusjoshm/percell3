---
status: pending
priority: p1
issue_id: "140"
tags: [code-review, correctness, pandas]
---

# _has_masked_measurements Uses any() on pandas Series

## Problem Statement
`auto_measure._has_masked_measurements()` calls Python's built-in `any()` on a pandas boolean Series. This is ambiguous and will trigger `FutureWarning` in recent pandas versions, eventually becoming an error.

## Findings
- **File:** `src/percell3/measure/auto_measure.py:353-356`
- Found by: kieran-python-reviewer (C2)
- Should use `.any()` method on the Series instead of built-in `any()`

## Proposed Solutions
1. **Use Series.any()** — Change `return any((measurements["scope"] == "mask_inside") & ...)` to `mask = ...; return mask.any()`

## Acceptance Criteria
- [ ] No pandas FutureWarning about ambiguous truth values
- [ ] Function correctly detects existing masked measurements
