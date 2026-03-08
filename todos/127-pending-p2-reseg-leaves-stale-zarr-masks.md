---
status: resolved-by-refactor
priority: p2
issue_id: "127"
tags: [code-review, schema, data-integrity, zarr]
dependencies: []
---

> **Resolved by layer-based architecture redesign (2026-03-02).** The segmentation model was changed to global entities. Stale zarr cleanup is now handled through the redesigned layer lifecycle.

# Re-segmentation leaves stale zarr label images and threshold masks

## Problem Statement

When a FOV is re-segmented, old label images in `labels.zarr` are overwritten, but if the re-segmentation produces a label image for a different channel or the old threshold masks in `masks.zarr` reference the old cell IDs, those zarr arrays become stale. There is no mechanism to clean up zarr arrays when their corresponding SQLite records are deleted.

## Findings

- **Found by:** architecture-strategist, data-integrity-guardian
- `labels.zarr` stores label images keyed by `fov_id/channel_name`
- `masks.zarr` stores threshold masks keyed by `fov_id/channel_name`
- Re-segmentation overwrites the label image for the same FOV+channel
- But threshold masks from previous segmentation cycles reference old cell IDs
- If a user re-segments then exports without re-thresholding, the mask pixel values won't match new cell IDs
- `delete_fov()` removes zarr groups but re-segmentation does not

## Proposed Solutions

### Solution A: Clear threshold masks on re-segmentation (Recommended)

When re-segmenting a FOV, delete all threshold masks for that FOV since old cell IDs are invalid.

**Pros:** Prevents stale mask data
**Cons:** User must re-threshold after re-segmenting (which they should anyway)
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] Re-segmentation clears stale threshold masks
- [ ] Related particles/measurements cleaned up
- [ ] Warning logged when masks are cleared

## Technical Details

- **File:** `src/percell3/core/experiment_store.py` — segmentation path
- **File:** `src/percell3/core/zarr_io.py` — mask/label group management
