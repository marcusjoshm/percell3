"""Z-projection transforms for image stacks."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from percell3.io.models import ZTransform
from percell3.io.tiff import read_tiff


def project_mip(stack: np.ndarray) -> np.ndarray:
    """Maximum intensity projection along axis 0.

    Args:
        stack: 3D array (Z, Y, X).

    Returns:
        2D array (Y, X).
    """
    return np.max(stack, axis=0)


def project_sum(stack: np.ndarray) -> np.ndarray:
    """Sum projection along axis 0.

    Args:
        stack: 3D array (Z, Y, X).

    Returns:
        2D array (Y, X). Uses int64 for integer inputs to prevent overflow.
    """
    if np.issubdtype(stack.dtype, np.integer):
        return np.sum(stack, axis=0, dtype=np.int64)
    return np.sum(stack, axis=0)


def project_mean(stack: np.ndarray) -> np.ndarray:
    """Mean projection along axis 0, preserving dtype.

    Args:
        stack: 3D array (Z, Y, X).

    Returns:
        2D array (Y, X) with same dtype as input.
    """
    return np.mean(stack, axis=0).astype(stack.dtype)


def apply_z_transform(
    z_files: list[Path],
    transform: ZTransform,
) -> np.ndarray:
    """Load Z-slice files and apply the specified transform.

    Args:
        z_files: Paths to Z-slice files, sorted by Z index.
        transform: How to combine the Z-slices.

    Returns:
        2D array (Y, X).

    Raises:
        ValueError: If transform method is unknown or slice_index is out of range.
    """
    if transform.method == "slice":
        if transform.slice_index is None:
            raise ValueError("slice_index is required when method is 'slice'")
        if transform.slice_index < 0 or transform.slice_index >= len(z_files):
            raise ValueError(
                f"slice_index {transform.slice_index} out of range "
                f"(0-{len(z_files) - 1})"
            )
        return read_tiff(z_files[transform.slice_index])

    # Streaming accumulation: only one slice in memory at a time
    first = read_tiff(z_files[0])

    if transform.method == "mip":
        result = first.copy()
        for p in z_files[1:]:
            np.maximum(result, read_tiff(p), out=result)
        return result

    if transform.method == "sum":
        acc = first.astype(np.int64) if np.issubdtype(first.dtype, np.integer) else first.astype(np.float64)
        for p in z_files[1:]:
            acc += read_tiff(p)
        return acc

    if transform.method == "mean":
        acc = first.astype(np.float64)
        for p in z_files[1:]:
            acc += read_tiff(p)
        return (acc / len(z_files)).astype(first.dtype)

    raise ValueError(f"Unknown Z-transform method: {transform.method!r}")
