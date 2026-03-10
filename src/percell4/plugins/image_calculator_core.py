"""Image Calculator core operations — pure numpy, no store dependencies.

Provides pixel-level arithmetic for single-channel (with constant) and
two-channel (between images) operations, mirroring ImageJ's Process > Math
and Process > Image Calculator functionality.

Ported from percell3 with no changes to computational logic.
"""

from __future__ import annotations

import numpy as np

OPERATIONS = (
    "add", "subtract", "multiply", "divide",
    "and", "or", "xor",
    "min", "max", "abs_diff",
)


def _get_dtype_range(dtype: np.dtype) -> tuple[float, float]:
    """Return (min, max) for an integer or float numpy dtype."""
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return float(info.min), float(info.max)
    if not np.issubdtype(dtype, np.floating):
        raise TypeError(f"Unsupported dtype: {dtype}")
    info = np.finfo(dtype)
    return float(info.min), float(info.max)


def _apply_op(a: np.ndarray, b: np.ndarray | float, operation: str) -> np.ndarray:
    """Apply a named operation between array *a* and scalar/array *b* in float64.

    Returns float64 result (caller is responsible for clipping and casting).
    """
    # Bitwise ops — work on int64, no float64 allocation needed
    if operation in ("and", "or", "xor"):
        ai = a.astype(np.int64)
        bi = np.int64(b) if np.isscalar(b) else b.astype(np.int64)
        if operation == "and":
            return (ai & bi).astype(np.float64)
        if operation == "or":
            return (ai | bi).astype(np.float64)
        return (ai ^ bi).astype(np.float64)

    # Arithmetic ops — float64
    af = a.astype(np.float64)
    bf = np.float64(b) if np.isscalar(b) else b.astype(np.float64)

    if operation == "add":
        np.add(af, bf, out=af)
        return af
    if operation == "subtract":
        np.subtract(af, bf, out=af)
        return af
    if operation == "multiply":
        np.multiply(af, bf, out=af)
        return af
    if operation == "divide":
        out = np.zeros_like(af)
        mask = bf != 0
        np.divide(af, bf, out=out, where=mask)
        return out
    if operation == "min":
        return np.minimum(af, bf)
    if operation == "max":
        return np.maximum(af, bf)
    if operation == "abs_diff":
        np.subtract(af, bf, out=af)
        np.abs(af, out=af)
        return af

    raise ValueError(f"Unknown operation: {operation!r}. Must be one of {OPERATIONS}")


def _clip_and_cast(result: np.ndarray, target_dtype: np.dtype) -> np.ndarray:
    """Clip *result* to the valid range of *target_dtype* and cast."""
    lo, hi = _get_dtype_range(target_dtype)
    return np.clip(result, lo, hi).astype(target_dtype)


def apply_single_channel(
    image: np.ndarray,
    operation: str,
    constant: float,
) -> np.ndarray:
    """Apply *operation* between every pixel in *image* and *constant*.

    Computation is performed in float64 to avoid overflow. The result is
    clipped to the original dtype range and cast back.

    Args:
        image: 2D numpy array (any numeric dtype).
        operation: One of :data:`OPERATIONS`.
        constant: Scalar operand.

    Returns:
        2D numpy array with the same dtype as *image*.
    """
    result = _apply_op(image, constant, operation)
    return _clip_and_cast(result, image.dtype)


def apply_two_channel(
    image_a: np.ndarray,
    image_b: np.ndarray,
    operation: str,
) -> np.ndarray:
    """Apply *operation* pixel-wise between *image_a* and *image_b*.

    Computation is performed in float64 to avoid overflow. The result is
    clipped to the dtype range of *image_a* and cast back.

    Args:
        image_a: 2D numpy array (any numeric dtype). Determines output dtype.
        image_b: 2D numpy array (same shape as *image_a*).
        operation: One of :data:`OPERATIONS`.

    Returns:
        2D numpy array with the same dtype as *image_a*.
    """
    if image_a.shape != image_b.shape:
        raise ValueError(
            f"Shape mismatch: image_a {image_a.shape} vs image_b {image_b.shape}"
        )
    result = _apply_op(image_a, image_b, operation)
    return _clip_and_cast(result, image_a.dtype)
