---
status: complete
priority: p2
issue_id: "116"
tags: [code-review, segment, viewer, bug]
dependencies: []
---

# Threshold viewer does not display Gaussian-blurred image

## Problem Statement

During grouped intensity thresholding, the Gaussian blur IS applied internally when computing the Otsu threshold value, but the napari threshold viewer displays the **unsmoothed** image. This creates a visual mismatch: the threshold line was computed on a blurred image, but the user sees the original sharp image with that threshold overlaid.

## Findings

- **Found by:** user report + code investigation
- **Gaussian smoothing IS applied** in `measure/thresholding.py:96` and `measure/threshold_viewer.py:56` for threshold computation
- **But the viewer displays the unblurred image** at `measure/threshold_viewer.py:154`
- `launch_threshold_viewer()` signature does not accept a `gaussian_sigma` parameter
- The CLI collects `gaussian_sigma` at `menu.py:1965-1978` and passes it to `compute_masked_otsu()` but not to the viewer

**Call flow:**
1. CLI collects `gaussian_sigma` from user
2. `compute_masked_otsu(group_image, cell_mask, gaussian_sigma)` → blurs internally, returns threshold
3. `launch_threshold_viewer(group_image, cell_mask, initial_threshold)` → displays UNBLURRED image
4. After accept: `engine.threshold_group(..., gaussian_sigma)` → blurs and applies threshold correctly

## Proposed Solutions

### Solution A: Pass gaussian_sigma to the viewer and display blurred image (Recommended)

1. Add `gaussian_sigma` parameter to `launch_threshold_viewer()`
2. Apply `apply_gaussian_smoothing()` to `group_image` before displaying in napari
3. When ROI changes, re-apply smoothing to the new crop
4. Display the smoothed image so the threshold preview visually matches what was computed

- **Pros:** User sees exactly what the algorithm sees, accurate visual feedback
- **Cons:** Slightly more complex viewer code
- **Effort:** Small
- **Risk:** Low

### Solution B: Show both images side-by-side

Display both the original and smoothed images as separate layers in napari.

- **Pros:** User can compare both
- **Cons:** More complex UI, potentially confusing
- **Effort:** Medium
- **Risk:** Low

## Technical Details

**Affected files:**
- `src/percell3/measure/threshold_viewer.py` — add `gaussian_sigma` param, apply smoothing to displayed image
- `src/percell3/cli/menu.py` — pass `gaussian_sigma` to `launch_threshold_viewer()`

## Acceptance Criteria

- [ ] Threshold viewer displays the Gaussian-blurred image when sigma > 0
- [ ] Threshold preview overlay matches the actual computed threshold
- [ ] Sigma=0 or None behaves identically to current behavior
