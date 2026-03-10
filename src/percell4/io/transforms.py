"""Z-projection transforms for image stacks.

Pure numpy operations with no database, Zarr, or domain dependencies.
"""

from __future__ import annotations

import numpy as np


def project_z(stack: np.ndarray, method: str = "max") -> np.ndarray:
    """Project a 3D stack along the Z axis (axis 0).

    Args:
        stack: 3D array with shape (Z, Y, X).
        method: Projection method — one of 'max' (MIP), 'mean', or 'sum'.

    Returns:
        2D array with shape (Y, X).

    Raises:
        ValueError: If *method* is not a recognized projection type.
    """
    if method == "max":
        return np.max(stack, axis=0)
    elif method == "mean":
        return np.mean(stack, axis=0).astype(stack.dtype)
    elif method == "sum":
        if np.issubdtype(stack.dtype, np.integer):
            return np.sum(stack, axis=0, dtype=np.int64)
        return np.sum(stack, axis=0)
    else:
        raise ValueError(f"Unknown projection method: {method}")
