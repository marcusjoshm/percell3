---
status: pending
priority: p3
issue_id: "067"
tags: [code-review, code-simplicity, napari]
dependencies: []
---

# `_default_contrast_limits` Duplicates napari's Built-in Handling

## Problem Statement
The `_default_contrast_limits()` function in `_viewer.py` computes contrast limits based on dtype (e.g., `(0, 65535)` for uint16). napari already does this automatically when adding image layers. The function is only used as a convenience default and duplicates napari's internal logic.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — `_default_contrast_limits()` function
- Flagged by: code-simplicity-reviewer
- napari's `add_image()` computes contrast limits from data if not provided
- Custom limits only needed when user wants percentile-based or custom ranges

## Proposed Solutions
### Option 1 (Recommended): Remove function, let napari auto-compute
Remove `_default_contrast_limits()` and don't pass `contrast_limits` to `add_image()`. napari will compute appropriate limits from the actual data.

### Option 2: Keep but simplify
Reduce to a simple dtype->range lookup without the function overhead.

## Acceptance Criteria
- [ ] napari auto-computes contrast limits
- [ ] Function removed or simplified
- [ ] Visual quality unchanged (napari's defaults are adequate)
