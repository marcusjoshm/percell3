"""ImportEngine — reads files, applies transforms, writes to ExperimentStore."""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

from percell3.core import ExperimentStore
from percell3.core.exceptions import DuplicateError
from percell3.io._sanitize import sanitize_name
from percell3.io.models import (
    ChannelMapping,
    DiscoveredFile,
    ImportPlan,
    ImportResult,
    ZTransform,
)
from percell3.io.scanner import FileScanner
from percell3.io.tiff import read_tiff
from percell3.io.transforms import apply_z_transform, project_mip, project_mean, project_sum


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
            progress_callback: Optional callback(current, total, region_name).

        Returns:
            ImportResult with counts and warnings.

        Raises:
            FileNotFoundError: If source_path does not exist.
            ValueError: If source_path has no TIFF files.
        """
        start = time.monotonic()
        warnings: list[str] = []

        # Validate source path
        if not plan.source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {plan.source_path}")

        # Scan source directory
        scanner = FileScanner()
        scan_result = scanner.scan(plan.source_path, plan.token_config)

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

        # Register condition (idempotent)
        condition = sanitize_name(plan.condition)
        try:
            store.add_condition(condition)
        except DuplicateError:
            pass

        # Group files by region
        region_files = _group_by_token(scan_result.files, "region", "default")

        # Determine pixel size
        pixel_size = plan.pixel_size_um or scan_result.pixel_size_um

        regions_imported = 0
        images_written = 0
        skipped = 0
        total_regions = len(region_files)

        # Check existing regions
        existing_regions = {r.name for r in store.get_regions(condition=condition)}

        for idx, (region_token, files) in enumerate(sorted(region_files.items())):
            region_name = plan.region_names.get(region_token, sanitize_name(region_token))

            if progress_callback:
                progress_callback(idx + 1, total_regions, region_name)

            # Skip existing regions
            if region_name in existing_regions:
                warnings.append(f"Region '{region_name}' already exists, skipping")
                skipped += 1
                continue

            # Group by channel
            channel_files = _group_by_token(files, "channel", "0")

            # Determine image dimensions from first file
            first_file = files[0]
            h, w = first_file.shape[:2]

            # Register region
            store.add_region(
                region_name,
                condition,
                width=w,
                height=h,
                pixel_size_um=pixel_size,
                source_file=str(first_file.path),
            )

            # Write each channel
            for ch_token, ch_files in sorted(channel_files.items()):
                ch_name = channel_name_map.get(ch_token, sanitize_name(f"ch{ch_token}"))

                # Handle Z-stacks
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

                store.write_image(region_name, condition, ch_name, data)
                images_written += 1

            regions_imported += 1

        elapsed = time.monotonic() - start

        return ImportResult(
            regions_imported=regions_imported,
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
