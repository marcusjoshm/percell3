---
status: complete
priority: p2
issue_id: "111"
tags: [code-review, measure, dry, refactor]
dependencies: []
---

# Gaussian smoothing guard pattern duplicated 3 times

## Problem Statement

The identical Gaussian smoothing pattern appears in 3 places:
1. `thresholding.py:77` (threshold_fov)
2. `thresholding.py:157` (threshold_group)
3. `threshold_viewer.py:54` (compute_masked_otsu)

Each has the same guard check, lazy import, float64 cast, and filter application. If the smoothing strategy changes, 3 places must be updated.

Additionally, `float64` is unnecessary — `float32` is sufficient for Otsu thresholding and halves memory (72MB → 40MB for 2048x2048 images).

## Findings

- **Found by:** kieran-python-reviewer, code-simplicity-reviewer, performance-oracle
- **Locations:** `src/percell3/measure/thresholding.py:77,157`, `src/percell3/measure/threshold_viewer.py:54`

## Proposed Solutions

### Solution A: Extract helper + use float32 (Recommended)
```python
def _apply_gaussian_smoothing(image: np.ndarray, sigma: float | None) -> np.ndarray:
    if sigma is None or sigma <= 0:
        return image
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(image.astype(np.float32), sigma=sigma)
```
Replace all 3 call sites with `image = _apply_gaussian_smoothing(image, gaussian_sigma)`.
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] Single helper function for Gaussian smoothing
- [ ] Uses float32 instead of float64
- [ ] All 3 call sites use the helper
- [ ] Existing tests still pass

## Work Log

- 2026-02-25: Identified during code review
