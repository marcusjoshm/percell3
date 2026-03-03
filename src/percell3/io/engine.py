"""ImportEngine — reads files, applies transforms, writes to ExperimentStore."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

import numpy as np

from percell3.core import ExperimentStore
from percell3.core.exceptions import DuplicateError
from percell3.io._sanitize import sanitize_name
from percell3.io.models import (
    ChannelMapping,
    DiscoveredFile,
    ImportPlan,
    ImportResult,
    TileConfig,
    ZTransform,
)
from percell3.io.scanner import FileScanner
from percell3.io.tiff import read_tiff
from percell3.io.transforms import apply_z_transform, project_mip, project_mean, project_sum

logger = logging.getLogger(__name__)


class ImportEngine:
    """Executes an ImportPlan against an ExperimentStore."""

    def execute(
        self,
        plan: ImportPlan,
        store: ExperimentStore,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> ImportResult:
        """Execute an import plan, writing images into the store.

        Args:
            plan: The import plan to execute.
            store: Target ExperimentStore.
            progress_callback: Optional callback(current, total, fov_name).

        Returns:
            ImportResult with counts and warnings.

        Raises:
            FileNotFoundError: If source_path does not exist.
            ValueError: If source_path has no TIFF files.
        """
        start = time.monotonic()
        warnings: list[str] = []

        # Validate source path
        if plan.source_files is None and not plan.source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {plan.source_path}")

        # Scan source directory (or explicit file list)
        scanner = FileScanner()
        scan_result = scanner.scan(
            plan.source_path, plan.token_config, files=plan.source_files,
        )

        # Register channels (idempotent)
        channels_registered = 0
        channel_name_map = self._build_channel_name_map(plan.channel_mappings)
        for ch_token in scan_result.channels:
            ch_name = channel_name_map.get(ch_token, sanitize_name(f"ch{ch_token}"))
            mapping = self._find_mapping(plan.channel_mappings, ch_token)
            role = mapping.role if mapping else None
            color = mapping.color if mapping else None
            try:
                store.add_channel(ch_name, role=role, color=color)
                channels_registered += 1
            except DuplicateError:
                pass

        # Register default channel when no channel tokens were discovered
        if not scan_result.channels:
            default_ch_name = channel_name_map.get("0", sanitize_name("ch0"))
            try:
                store.add_channel(default_ch_name)
                channels_registered += 1
            except DuplicateError:
                pass

        # Sanitize default bio_rep (may be overridden per-group below)
        default_bio_rep = sanitize_name(plan.bio_rep)

        # Register conditions (idempotent)
        # Bio reps are created lazily per condition when FOVs are added.
        if plan.condition_map:
            unique_conditions = sorted(set(
                sanitize_name(c) for c in plan.condition_map.values()
            ))
            for cond in unique_conditions:
                try:
                    store.add_condition(cond)
                except DuplicateError:
                    pass
        else:
            unique_conditions = [sanitize_name(plan.condition)]
            try:
                store.add_condition(unique_conditions[0])
            except DuplicateError:
                pass

        # Group files by FOV
        fov_files = _group_by_token(scan_result.files, "fov", "default")

        # Determine pixel size
        pixel_size = plan.pixel_size_um or scan_result.pixel_size_um

        fovs_imported = 0
        images_written = 0
        skipped = 0
        total_fovs = len(fov_files)

        # Cache existing FOVs per condition to avoid repeated queries
        _existing_cache: dict[str, set[str]] = {}

        for idx, (fov_token, files) in enumerate(sorted(fov_files.items())):
            # Skip unassigned groups when condition_map is non-empty
            if plan.condition_map and fov_token not in plan.condition_map:
                skipped += 1
                continue

            fov_name = plan.fov_names.get(fov_token, sanitize_name(fov_token))

            # Determine condition for this FOV
            if plan.condition_map and fov_token in plan.condition_map:
                condition = sanitize_name(plan.condition_map[fov_token])
            else:
                condition = sanitize_name(plan.condition)

            # Determine bio_rep for this FOV (per-group or default)
            if plan.bio_rep_map and fov_token in plan.bio_rep_map:
                bio_rep = sanitize_name(plan.bio_rep_map[fov_token])
            else:
                bio_rep = default_bio_rep

            # Build globally unique display_name
            display_name = f"{condition}_{bio_rep}_{fov_name}"

            if progress_callback:
                progress_callback(idx + 1, total_fovs, display_name)

            # Check existing FOVs (cached globally by display_name)
            if not _existing_cache:
                _existing_cache["_all"] = {
                    f.display_name for f in store.get_fovs()
                }

            if display_name in _existing_cache.get("_all", set()):
                warnings.append(f"FOV '{display_name}' already exists, skipping")
                skipped += 1
                continue

            # Group by channel
            channel_files = _group_by_token(files, "channel", "0")

            # Determine image dimensions from first file
            first_file = files[0]
            h, w = first_file.shape[:2]

            # Tile stitching: compute stitched dimensions
            if plan.tile_config is not None:
                stitched_h = plan.tile_config.grid_rows * h
                stitched_w = plan.tile_config.grid_cols * w
            else:
                stitched_h, stitched_w = h, w

            # Register FOV
            fov_id = store.add_fov(
                condition,
                bio_rep=bio_rep,
                display_name=display_name,
                width=stitched_w,
                height=stitched_h,
                pixel_size_um=pixel_size,
                source_file=str(first_file.path),
            )
            _existing_cache.setdefault("_all", set()).add(display_name)

            # Write each channel
            for ch_token, ch_files in sorted(channel_files.items()):
                ch_name = channel_name_map.get(ch_token, sanitize_name(f"ch{ch_token}"))

                if plan.tile_config is not None:
                    # Tile stitching mode: read all tiles for this channel,
                    # apply Z-transform per tile, then assemble into grid
                    data = self._read_and_stitch_tiles(
                        ch_files, plan.tile_config, plan.z_transform,
                    )
                else:
                    # Normal import: handle Z-stacks or single images
                    z_files_map = self._group_by_z(ch_files)
                    if z_files_map and plan.z_transform.method != "keep":
                        z_paths = [p for _, p in sorted(z_files_map.items())]
                        data = apply_z_transform(z_paths, plan.z_transform)
                    else:
                        # Single 2D image (or keep raw — take first)
                        data = read_tiff(ch_files[0].path)
                        if data.ndim > 2:
                            # Multi-page TIFF — apply projection
                            data = _project_array(data, plan.z_transform)

                store.write_image(fov_id, ch_name, data)
                images_written += 1

            fovs_imported += 1

        elapsed = time.monotonic() - start

        return ImportResult(
            fovs_imported=fovs_imported,
            channels_registered=channels_registered,
            images_written=images_written,
            skipped=skipped,
            warnings=warnings,
            elapsed_seconds=round(elapsed, 3),
        )

    def _build_channel_name_map(
        self, mappings: list[ChannelMapping]
    ) -> dict[str, str]:
        """Build a token_value -> name mapping dict."""
        return {m.token_value: m.name for m in mappings}

    def _find_mapping(
        self, mappings: list[ChannelMapping], token_value: str
    ) -> ChannelMapping | None:
        """Find a channel mapping by token value."""
        for m in mappings:
            if m.token_value == token_value:
                return m
        return None

    def _read_and_stitch_tiles(
        self,
        ch_files: list[DiscoveredFile],
        tile_config: TileConfig,
        z_transform: ZTransform,
    ) -> np.ndarray:
        """Read tile images for one channel and stitch into a single array.

        For each tile (series index), reads the image and applies Z-transform
        if the tile has Z-stacks. Then assembles all tiles into the grid.

        Args:
            ch_files: All files for one (FOV, channel) group (may include
                multiple series and z_slice tokens).
            tile_config: Grid configuration for stitching.
            z_transform: How to handle Z-stacks within each tile.

        Returns:
            Stitched 2D array.

        Raises:
            ValueError: If tile count or dimensions don't match config.
        """
        # Group by series index
        series_files: dict[int, list[DiscoveredFile]] = defaultdict(list)
        for f in ch_files:
            s = f.tokens.get("series")
            if s is not None:
                series_files[int(s)].append(f)
            else:
                # No series token — treat as tile 0
                series_files[0].append(f)

        # Read each tile (applying Z-transform if multi-Z)
        tile_images: list[np.ndarray] = []
        for tile_idx in sorted(series_files.keys()):
            tile_files = series_files[tile_idx]
            z_map = {
                f.tokens["z_slice"]: f.path
                for f in tile_files
                if "z_slice" in f.tokens
            }
            if z_map and z_transform.method != "keep":
                z_paths = [p for _, p in sorted(z_map.items())]
                data = apply_z_transform(z_paths, z_transform)
            else:
                data = read_tiff(tile_files[0].path)
                if data.ndim > 2:
                    data = _project_array(data, z_transform)
            tile_images.append(data)

        return stitch_tiles(tile_images, tile_config)

    def _group_by_z(
        self, files: list[DiscoveredFile]
    ) -> dict[str, Path]:
        """Group files by z_slice token, return z_value -> path mapping."""
        z_map: dict[str, Path] = {}
        for f in files:
            z = f.tokens.get("z_slice")
            if z is not None:
                z_map[z] = f.path
        return z_map


def _group_by_token(
    files: list[DiscoveredFile], key: str, default: str,
) -> dict[str, list[DiscoveredFile]]:
    """Group discovered files by a token key."""
    groups: dict[str, list[DiscoveredFile]] = defaultdict(list)
    for f in files:
        groups[f.tokens.get(key, default)].append(f)
    return dict(groups)


def _project_array(data: "np.ndarray", transform: ZTransform) -> "np.ndarray":
    """Apply Z-transform to an already-loaded 3D array.

    Args:
        data: 3D array (Z, Y, X).
        transform: How to combine the Z-slices.

    Returns:
        2D array (Y, X).

    Raises:
        ValueError: If transform method is unknown or slice_index is invalid.
    """
    if transform.method == "mip":
        return project_mip(data)
    if transform.method == "sum":
        return project_sum(data)
    if transform.method == "mean":
        return project_mean(data)
    if transform.method == "slice":
        if transform.slice_index is None:
            raise ValueError("slice_index is required when method is 'slice'")
        if transform.slice_index < 0 or transform.slice_index >= data.shape[0]:
            raise ValueError(
                f"slice_index {transform.slice_index} out of range "
                f"(0-{data.shape[0] - 1})"
            )
        return data[transform.slice_index]
    raise ValueError(f"Unknown Z-transform method: {transform.method!r}")


# ---------------------------------------------------------------------------
# Tile stitching
# ---------------------------------------------------------------------------

# 2 GB memory guard threshold for stitched canvas
_MAX_CANVAS_BYTES = 2 * 1024 * 1024 * 1024


def build_tile_grid(config: TileConfig) -> list[tuple[int, int]]:
    """Build tile-index-to-grid-position mapping.

    Returns a list where ``positions[tile_index] = (row, col)``.

    The mapping is computed in two steps:
    1. Generate sequential positions in *base* order (row_by_row + right_and_down).
    2. Apply grid_type (column-major or snake) and order (flip rows/cols).

    Args:
        config: Tile grid configuration.

    Returns:
        List of (row, col) tuples, one per tile, indexed by tile number.
    """
    rows, cols = config.grid_rows, config.grid_cols
    total = rows * cols
    positions: list[tuple[int, int]] = [(0, 0)] * total

    # Determine row/col iteration order from the "order" parameter
    flip_rows = "up" in config.order      # up means rows go bottom-to-top
    flip_cols = "left" in config.order     # left means cols go right-to-left

    # Build ordered row and column index sequences
    row_seq = list(range(rows - 1, -1, -1)) if flip_rows else list(range(rows))
    col_seq = list(range(cols - 1, -1, -1)) if flip_cols else list(range(cols))

    tile_idx = 0

    if config.grid_type == "row_by_row":
        for r in row_seq:
            for c in col_seq:
                positions[tile_idx] = (r, c)
                tile_idx += 1

    elif config.grid_type == "snake_by_row":
        for i, r in enumerate(row_seq):
            cs = list(reversed(col_seq)) if i % 2 == 1 else col_seq
            for c in cs:
                positions[tile_idx] = (r, c)
                tile_idx += 1

    elif config.grid_type == "column_by_column":
        for c in col_seq:
            for r in row_seq:
                positions[tile_idx] = (r, c)
                tile_idx += 1

    elif config.grid_type == "snake_by_column":
        for i, c in enumerate(col_seq):
            rs = list(reversed(row_seq)) if i % 2 == 1 else row_seq
            for r in rs:
                positions[tile_idx] = (r, c)
                tile_idx += 1

    return positions


def stitch_tiles(
    tile_images: list[np.ndarray],
    config: TileConfig,
) -> np.ndarray:
    """Assemble tile images into a single stitched 2D array.

    Args:
        tile_images: List of 2D arrays, one per tile, ordered by tile index.
        config: Tile grid configuration.

    Returns:
        Stitched 2D array of shape (grid_rows * tile_h, grid_cols * tile_w).

    Raises:
        ValueError: If tile count doesn't match config, dimensions mismatch,
            or estimated canvas exceeds memory threshold.
    """
    expected = config.total_tiles
    if len(tile_images) != expected:
        raise ValueError(
            f"Expected {expected} tiles ({config.grid_rows}x{config.grid_cols}), "
            f"got {len(tile_images)}"
        )

    tile_h, tile_w = tile_images[0].shape[:2]

    # Validate all tiles have identical dimensions
    for i, tile in enumerate(tile_images):
        if tile.shape[:2] != (tile_h, tile_w):
            raise ValueError(
                f"Tile {i} has shape {tile.shape[:2]}, expected ({tile_h}, {tile_w})"
            )

    # Memory guard
    canvas_h = config.grid_rows * tile_h
    canvas_w = config.grid_cols * tile_w
    estimated_bytes = canvas_h * canvas_w * tile_images[0].itemsize
    if estimated_bytes > _MAX_CANVAS_BYTES:
        raise ValueError(
            f"Stitched canvas would be {estimated_bytes / (1024**3):.1f} GB "
            f"({canvas_h}x{canvas_w}), exceeding 2 GB limit. "
            f"Consider importing tiles separately."
        )

    # Build the stitched canvas
    canvas = np.zeros((canvas_h, canvas_w), dtype=tile_images[0].dtype)
    positions = build_tile_grid(config)

    for tile_idx, (row, col) in enumerate(positions):
        y0 = row * tile_h
        x0 = col * tile_w
        canvas[y0 : y0 + tile_h, x0 : x0 + tile_w] = tile_images[tile_idx]

    return canvas
