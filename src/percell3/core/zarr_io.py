"""OME-Zarr read/write utilities for PerCell 3.

Handles image, label, and mask storage with NGFF 0.4 metadata.
"""

from __future__ import annotations

from pathlib import Path

import dask.array as da
import numpy as np
import zarr
from numcodecs import Blosc, Zstd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_COMPRESSOR = Blosc(cname="lz4", clevel=5, shuffle=Blosc.BITSHUFFLE)
IMAGE_CHUNKS_YX = (512, 512)
IMAGE_CHUNKS_CYX = (1, 512, 512)

LABEL_COMPRESSOR = Blosc(cname="lz4", clevel=5, shuffle=Blosc.BITSHUFFLE)
LABEL_CHUNKS = (512, 512)

MASK_COMPRESSOR = Zstd(level=3)
MASK_CHUNKS = (512, 512)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _region_group_path(
    condition: str,
    region: str,
    timepoint: str | None = None,
) -> str:
    """Build the zarr group path for a condition/region (shared by images and labels)."""
    if timepoint:
        return f"{condition}/{timepoint}/{region}"
    return f"{condition}/{region}"


def image_group_path(
    condition: str,
    region: str,
    timepoint: str | None = None,
) -> str:
    """Build the zarr group path for an image region."""
    return _region_group_path(condition, region, timepoint)


def label_group_path(
    condition: str,
    region: str,
    timepoint: str | None = None,
) -> str:
    """Build the zarr group path for a label region."""
    return _region_group_path(condition, region, timepoint)


def mask_group_path(
    condition: str,
    region: str,
    channel: str,
    timepoint: str | None = None,
) -> str:
    """Build the zarr group path for a mask."""
    if timepoint:
        return f"{condition}/{timepoint}/{region}/threshold_{channel}"
    return f"{condition}/{region}/threshold_{channel}"


# ---------------------------------------------------------------------------
# NGFF 0.4 metadata builders
# ---------------------------------------------------------------------------


def _build_multiscales_image(
    name: str,
    channels: list[dict],
    pixel_size_um: float | None = None,
) -> dict:
    """Build NGFF 0.4 multiscales + omero metadata for an image group."""
    scale_c = 1.0
    scale_yx = pixel_size_um if pixel_size_um else 1.0
    return {
        "multiscales": [
            {
                "version": "0.4",
                "name": name,
                "axes": [
                    {"name": "c", "type": "channel"},
                    {"name": "y", "type": "space", "unit": "micrometer"},
                    {"name": "x", "type": "space", "unit": "micrometer"},
                ],
                "datasets": [
                    {
                        "path": "0",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [scale_c, scale_yx, scale_yx]}
                        ],
                    }
                ],
                "coordinateTransformations": [{"type": "identity"}],
            }
        ],
        "omero": {
            "channels": [
                {
                    "label": ch.get("name", ""),
                    "color": (ch.get("color") or "FFFFFF").lstrip("#"),
                    "active": True,
                    "window": {"start": 0, "end": 65535},
                }
                for ch in channels
            ],
        },
    }


def _build_2d_multiscales(pixel_size_um: float | None = None) -> list:
    """Build NGFF 0.4 multiscales metadata for a 2D (Y, X) dataset."""
    scale_yx = pixel_size_um if pixel_size_um else 1.0
    return [
        {
            "version": "0.4",
            "axes": [
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": [
                {
                    "path": "0",
                    "coordinateTransformations": [
                        {"type": "scale", "scale": [scale_yx, scale_yx]}
                    ],
                }
            ],
        }
    ]


def _build_multiscales_label(
    name: str,
    source_image_path: str | None = None,
    pixel_size_um: float | None = None,
) -> dict:
    """Build NGFF 0.4 metadata for a label group."""
    attrs: dict = {"multiscales": _build_2d_multiscales(pixel_size_um)}
    label_meta: dict = {"version": "0.4"}
    if source_image_path:
        label_meta["source"] = {"image": source_image_path}
    attrs["image-label"] = label_meta
    return attrs


def _build_multiscales_mask(
    pixel_size_um: float | None = None,
) -> dict:
    """Build NGFF 0.4 metadata for a mask group."""
    return {"multiscales": _build_2d_multiscales(pixel_size_um)}


# ---------------------------------------------------------------------------
# Image I/O
# ---------------------------------------------------------------------------


def write_image_channel(
    zarr_path: Path,
    group_path: str,
    channel_index: int,
    num_channels: int,
    data: np.ndarray,
    channels_meta: list[dict],
    pixel_size_um: float | None = None,
) -> None:
    """Write a single channel's 2D data into a (C, Y, X) zarr array.

    Args:
        zarr_path: Path to the images.zarr store.
        group_path: Group path within the store (e.g. "control/r1").
        channel_index: Index along the C dimension.
        num_channels: Total number of channels (for pre-allocation).
        data: 2D numpy array (Y, X).
        channels_meta: List of dicts with 'name' and 'color' for NGFF omero metadata.
        pixel_size_um: Pixel size in micrometers.
    """
    if data.ndim != 2:
        raise ValueError(f"Expected 2D array (Y, X), got {data.ndim}D with shape {data.shape}")
    root = zarr.open(str(zarr_path), mode="a")
    group = root.require_group(group_path)

    h, w = data.shape
    arr_path = f"{group_path}/0"

    if arr_path in root:
        arr = root[arr_path]
        # Resize C dimension if needed
        if arr.shape[0] < num_channels:
            arr.resize(num_channels, h, w)
    else:
        arr = root.zeros(
            arr_path,
            shape=(num_channels, h, w),
            chunks=IMAGE_CHUNKS_CYX,
            dtype=data.dtype,
            compressor=IMAGE_COMPRESSOR,
        )

    arr[channel_index] = data

    # Update NGFF metadata
    region_name = group_path.rsplit("/", 1)[-1]
    attrs = _build_multiscales_image(region_name, channels_meta, pixel_size_um)
    group.attrs.update(attrs)


def read_image_channel(
    zarr_path: Path,
    group_path: str,
    channel_index: int,
) -> da.Array:
    """Read a single channel as a lazy dask array.

    Returns:
        2D dask array (Y, X).
    """
    root = zarr.open(str(zarr_path), mode="r")
    arr = root[f"{group_path}/0"]
    z = da.from_zarr(arr)
    return z[channel_index]


def read_image_channel_numpy(
    zarr_path: Path,
    group_path: str,
    channel_index: int,
) -> np.ndarray:
    """Read a single channel fully into memory.

    Returns:
        2D numpy array (Y, X).
    """
    root = zarr.open(str(zarr_path), mode="r")
    arr = root[f"{group_path}/0"]
    return np.array(arr[channel_index])


# ---------------------------------------------------------------------------
# Label I/O
# ---------------------------------------------------------------------------


def write_labels(
    zarr_path: Path,
    group_path: str,
    data: np.ndarray,
    source_image_path: str | None = None,
    pixel_size_um: float | None = None,
) -> None:
    """Write a 2D label image (Y, X) as int32."""
    if data.ndim != 2:
        raise ValueError(f"Expected 2D array (Y, X), got {data.ndim}D with shape {data.shape}")
    root = zarr.open(str(zarr_path), mode="a")
    group = root.require_group(group_path)

    arr_path = f"{group_path}/0"
    label_data = data.astype(np.int32)

    if arr_path in root:
        arr = root[arr_path]
        arr[:] = label_data
    else:
        root.array(
            arr_path,
            data=label_data,
            chunks=LABEL_CHUNKS,
            compressor=LABEL_COMPRESSOR,
            overwrite=True,
        )

    region_name = group_path.rsplit("/", 1)[-1]
    attrs = _build_multiscales_label(region_name, source_image_path, pixel_size_um)
    group.attrs.update(attrs)


def read_labels(
    zarr_path: Path,
    group_path: str,
) -> np.ndarray:
    """Read a label image as numpy array."""
    root = zarr.open(str(zarr_path), mode="r")
    return np.array(root[f"{group_path}/0"])


# ---------------------------------------------------------------------------
# Mask I/O
# ---------------------------------------------------------------------------


def write_mask(
    zarr_path: Path,
    group_path: str,
    data: np.ndarray,
    pixel_size_um: float | None = None,
) -> None:
    """Write a binary mask as uint8 (0/255)."""
    if data.ndim != 2:
        raise ValueError(f"Expected 2D array (Y, X), got {data.ndim}D with shape {data.shape}")
    root = zarr.open(str(zarr_path), mode="a")
    group = root.require_group(group_path)

    mask_data = np.where(data, np.uint8(255), np.uint8(0))

    arr_path = f"{group_path}/0"
    if arr_path in root:
        arr = root[arr_path]
        arr[:] = mask_data
    else:
        root.array(
            arr_path,
            data=mask_data,
            chunks=MASK_CHUNKS,
            dtype=np.uint8,
            compressor=MASK_COMPRESSOR,
            overwrite=True,
        )

    attrs = _build_multiscales_mask(pixel_size_um)
    group.attrs.update(attrs)


def read_mask(
    zarr_path: Path,
    group_path: str,
) -> np.ndarray:
    """Read a binary mask as numpy array (uint8 0/255)."""
    root = zarr.open(str(zarr_path), mode="r")
    return np.array(root[f"{group_path}/0"])


# ---------------------------------------------------------------------------
# Store initialization
# ---------------------------------------------------------------------------


def init_zarr_store(zarr_path: Path) -> None:
    """Create an empty zarr group at the given path."""
    root = zarr.open(str(zarr_path), mode="w")
    root.attrs["percell_version"] = "3.0.0"
