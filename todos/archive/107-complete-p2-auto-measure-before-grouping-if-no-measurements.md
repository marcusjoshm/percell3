---
status: complete
priority: p2
issue_id: "107"
tags: [code-review, cli, ux, measure, threshold]
dependencies: []
---

# Auto-measure whole cells when thresholding without measurements

## Problem Statement

When running "Apply threshold" (grouped intensity thresholding), the process requires whole-cell measurements for the grouping metric (e.g., `mean_intensity` on GFP). If no measurements exist, the grouper fails with an error. The user must manually go back to the Measure menu, measure whole cells, then return to thresholding.

Instead, the thresholding handler should detect missing measurements and automatically run whole-cell measurement for all available channels before proceeding to grouping.

## Findings

- **Found by:** User testing
- **Location:** `src/percell3/cli/menu.py:1635` — `_apply_threshold()`
- **Failure point:** `_threshold_fov()` line 1468-1475 — `grouper.group_cells()` raises `ValueError` when measurements are missing, caught and printed as "Skipping: {e}"
- **Precedent:** `_segment_cells()` already auto-measures after segmentation (lines 1145-1181)
- **Note:** The particle workflow (`_particle_workflow()`) already measures all channels in Stage 2 (line 2477-2503), so this only affects standalone threshold usage

## Proposed Solutions

### Solution A: Check and auto-measure in `_apply_threshold()` (Recommended)
1. After prerequisites check, query for existing measurements on the grouping channel
2. If no measurements exist for any FOV, auto-measure all channels for all selected FOVs
3. Use the same pattern as `_segment_cells()` auto-measure (lines 1145-1181)
4. Show a message: "No measurements found. Measuring all channels first..."
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] `_apply_threshold()` detects missing measurements before grouping
- [ ] Auto-measures all channels for selected FOVs when measurements missing
- [ ] Shows progress during auto-measurement
- [ ] Proceeds to grouping after measurement completes
- [ ] No change when measurements already exist

## Work Log

- 2026-02-25: Identified during user interface testing
