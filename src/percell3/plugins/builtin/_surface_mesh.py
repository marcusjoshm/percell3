"""Pure-numpy mesh construction for 3D surface plots.

Converts two 2D arrays (height channel + color channel) into a triangle mesh
suitable for napari's Surface layer. No napari or Qt dependency — testable
without a display server.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


def build_surface(
    height: np.ndarray,
    color: np.ndarray,
    z_scale: float = 50.0,
    sigma: float = 0.0,
    log_z: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build napari Surface tuple from two 2D arrays.

    Args:
        height: (H, W) array whose intensity defines Z elevation.
        color: (H, W) array whose intensity defines vertex color values.
        z_scale: Vertical exaggeration factor applied to normalized height.
        sigma: Gaussian smoothing sigma for the height channel (0 = none).
        log_z: If True, apply log1p transform to height before normalization.

    Returns:
        Tuple of (vertices, faces, values) for ``viewer.add_surface()``:
        - vertices: (H*W, 3) float32, columns are (row, col, z)
        - faces: (2*(H-1)*(W-1), 3) int32, triangle indices
        - values: (H*W,) float32, color channel intensities

    Raises:
        ValueError: If arrays are not 2D, shapes don't match, or ROI < 2x2.
    """
    if height.ndim != 2:
        raise ValueError(f"height must be 2D, got {height.ndim}D")
    if color.ndim != 2:
        raise ValueError(f"color must be 2D, got {color.ndim}D")
    if height.shape != color.shape:
        raise ValueError(
            f"height shape {height.shape} != color shape {color.shape}"
        )

    H, W = height.shape
    if H < 2 or W < 2:
        raise ValueError(f"ROI must be at least 2x2, got {H}x{W}")

    # Work in float32
    h = height.astype(np.float32)

    # Replace NaN/Inf with 0
    mask = ~np.isfinite(h)
    if mask.any():
        h[mask] = 0.0

    # Smooth before mesh construction
    if sigma > 0:
        h = gaussian_filter(h, sigma=sigma)

    # Log transform (log1p handles zeros gracefully)
    if log_z:
        h = np.log1p(h)

    # Normalize to [0, 1]
    h_min, h_max = h.min(), h.max()
    h_range = h_max - h_min
    if h_range > 0:
        h = (h - h_min) / h_range
        h *= z_scale
    else:
        # Uniform height — flat surface at Z=0
        h = np.zeros_like(h)

    # --- Vertices: (H*W, 3) float32 ---
    rows, cols = np.meshgrid(
        np.arange(H, dtype=np.float32),
        np.arange(W, dtype=np.float32),
        indexing="ij",
    )
    vertices = np.stack([rows.ravel(), cols.ravel(), h.ravel()], axis=1)

    # --- Faces: two triangles per 2x2 quad ---
    rr, cc = np.meshgrid(
        np.arange(H - 1, dtype=np.int32),
        np.arange(W - 1, dtype=np.int32),
        indexing="ij",
    )
    tl = (rr * W + cc).ravel()
    tr = tl + 1
    bl = tl + W
    br = tl + W + 1

    tri1 = np.stack([tl, tr, bl], axis=1)
    tri2 = np.stack([tr, br, bl], axis=1)
    faces = np.vstack([tri1, tri2])

    # --- Vertex values from color channel ---
    values = color.astype(np.float32).ravel()

    return vertices, faces, values
