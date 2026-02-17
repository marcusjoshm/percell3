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

        # Sanitize bio_rep once and use consistently
        bio_rep = sanitize_name(plan.bio_rep)

        # Register bio rep (idempotent)
        existing_bio_reps = store.get_bio_reps()
        if bio_rep not in existing_bio_reps:
            store.add_bio_rep(bio_rep)

        # Register conditions (idempotent)
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
            fov_name = plan.fov_names.get(fov_token, sanitize_name(fov_token))

            # Determine condition for this FOV
            if plan.condition_map and fov_token in plan.condition_map:
                condition = sanitize_name(plan.condition_map[fov_token])
            else:
                condition = sanitize_name(plan.condition)

            if progress_callback:
                progress_callback(idx + 1, total_fovs, fov_name)

            # Check existing FOVs (cached per condition)
            if condition not in _existing_cache:
                _existing_cache[condition] = {
                    f.name for f in store.get_fovs(
                        condition=condition, bio_rep=bio_rep,
                    )
                }

            if fov_name in _existing_cache[condition]:
                warnings.append(f"FOV '{fov_name}' already exists in '{condition}', skipping")
                skipped += 1
                continue

            # Group by channel
            channel_files = _group_by_token(files, "channel", "0")

            # Determine image dimensions from first file
            first_file = files[0]
            h, w = first_file.shape[:2]

            # Register FOV
            store.add_fov(
                fov_name,
                condition,
                bio_rep=bio_rep,
                width=w,
                height=h,
                pixel_size_um=pixel_size,
                source_file=str(first_file.path),
            )
            _existing_cache[condition].add(fov_name)

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

                store.write_image(fov_name, condition, ch_name, data, bio_rep=bio_rep)
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
