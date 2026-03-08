---
status: pending
priority: p2
issue_id: "008"
tags: [code-review, quality]
dependencies: []
---

# No Input Dimension Validation in Zarr Writes

## Problem Statement

The zarr write functions (`write_image_channel`, `write_labels`, `write_mask`) all expect 2D numpy arrays but do not validate the dimensionality of the input data. Passing a 3D array (e.g., a z-stack or an array with an accidentally retained singleton dimension) would produce cryptic zarr errors, silently corrupt the stored data, or write data that is unreadable by downstream consumers expecting 2D arrays. Similarly, `zarr_io.py`'s resize logic does not validate that spatial dimensions match before resizing.

## Findings

- `write_image_channel`, `write_labels`, and `write_mask` in `experiment_store.py` all expect 2D `(H, W)` data but contain no `ndim` check.
- A 3D array like `(1, H, W)` or `(H, W, 3)` would either:
  - Cause a shape mismatch error deep in zarr internals (cryptic traceback)
  - Be silently stored with wrong dimensions, corrupting the dataset
  - Produce data that fails when read back as 2D
- `zarr_io.py:210-212` performs `resize` without validating that `arr.shape[1:]` matches `(h, w)`, so a shape mismatch could produce corrupted multiscale pyramids.
- None of the write paths have early validation, making debugging difficult when the error surfaces later during reads.

## Proposed Solutions

### Option 1

Add explicit dimension validation at the entry point of each write function:

```python
def write_image_channel(self, region_id: int, channel: str, data: np.ndarray) -> None:
    if data.ndim != 2:
        raise ValueError(
            f"Expected 2D array (H, W), got {data.ndim}D array with shape {data.shape}"
        )
    # ... existing logic
```

Apply the same pattern to `write_labels` and `write_mask`.

### Option 2

In addition to Option 1, add a validation helper in `zarr_io.py` that checks spatial dimensions before resize:

```python
def _validate_spatial_dims(arr: zarr.Array, height: int, width: int) -> None:
    if arr.shape[1:] != (height, width):
        raise ValueError(
            f"Spatial dimensions mismatch: array has {arr.shape[1:]}, "
            f"expected ({height}, {width})"
        )
```

This catches mismatches during multiscale pyramid construction.

## Technical Details

- Files affected:
  - `src/percell3/core/experiment_store.py` (write_image_channel, write_labels, write_mask)
  - `src/percell3/core/zarr_io.py` (resize at line 210-212, plus _build_multiscales_label and _build_multiscales_mask)
- The validation should happen as early as possible (fail-fast principle) before any data is written to disk.
- Consider also validating dtype (e.g., label images should be integer, masks should be boolean or uint8).

## Acceptance Criteria

- [ ] `write_image_channel` raises `ValueError` for non-2D input with a clear message including the actual shape
- [ ] `write_labels` raises `ValueError` for non-2D input
- [ ] `write_mask` raises `ValueError` for non-2D input
- [ ] `zarr_io.py` resize validates spatial dimensions before resizing
- [ ] Tests cover: 1D input, 3D input, correct 2D input, and shape-mismatched resize
- [ ] Error messages include the actual shape for easy debugging

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during code review of `percell3.core`. Missing dimension validation allows garbage-in/garbage-out, which is especially dangerous in scientific imaging where corrupted data may not be noticed until much later in the analysis pipeline.
