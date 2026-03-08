---
status: pending
priority: p3
issue_id: "106"
tags: [code-review, cli, ux, naming]
dependencies: []
---

# Rename "Apply threshold" to "Grouped intensity thresholding"

## Problem Statement

The menu item "Apply threshold" (in the Analyze sub-menu) is misleading. The operation is much more than simple thresholding — it performs GMM-based cell grouping, interactive threshold QC per group in napari, and particle analysis. "Grouped intensity thresholding" better describes what the operation actually does.

## Findings

- **Found by:** User testing
- **Location:** `src/percell3/cli/menu.py:254`
  ```python
  MenuItem("2", "Apply threshold", "Otsu thresholding and particle detection", _apply_threshold),
  ```
- Also referenced in error messages: line 1338: `"Run 'Apply threshold' (menu 6) first."`
- Also referenced in plugin handler: line 383: `"Run 'Apply threshold' first to generate particle masks."`

## Proposed Solutions

### Solution A: Rename menu item and update references (Recommended)
1. Change label to "Grouped intensity thresholding"
2. Update description to "GMM grouping, Otsu thresholding, and particle analysis"
3. Update all string references that mention "Apply threshold"
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] Analyze menu shows "Grouped intensity thresholding" instead of "Apply threshold"
- [ ] Description updated to reflect the full operation
- [ ] All string references updated

## Work Log

- 2026-02-25: Identified during user interface testing
