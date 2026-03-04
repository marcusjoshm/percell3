"""TIFF export for FOV layers (channels, labels, masks)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tifffile

if TYPE_CHECKING:
    from percell3.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    """Result of exporting a single FOV."""

    written: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _sanitize(name: str) -> str:
    """Sanitize a name for use in filenames."""
    return name.replace(" ", "_").replace("(", "").replace(")", "")


def _unique_path(path: Path, used: set[Path]) -> Path:
    """Return *path* if unused, otherwise append _2, _3, ... until unique."""
    if path not in used:
        return path
    stem = path.stem
    suffix = path.suffix
    n = 2
    while True:
        candidate = path.with_name(f"{stem}_{n}{suffix}")
        if candidate not in used:
            return candidate
        n += 1


def export_fov_as_tiff(
    store: ExperimentStore,
    fov_id: int,
    output_dir: Path,
    overwrite: bool = False,
) -> ExportResult:
    """Export all configured layers for a FOV as individual TIFF files.

    Writes:
    - {fov_name}_{channel}.tiff for each channel
    - {fov_name}_{seg_name}_labels.tiff for each cellular segmentation in config
    - {fov_name}_{thr_name}_mask.tiff for each threshold in config (source_fov only)

    Args:
        store: The experiment store.
        fov_id: FOV to export.
        output_dir: Directory for output TIFF files.
        overwrite: If False, raise FileExistsError when a file already exists.

    Returns:
        ExportResult with written paths and skipped items.

    Raises:
        FileExistsError: If any output file exists and overwrite is False.
    """
    result = ExportResult()
    used_paths: set[Path] = set()

    fov_info = store.get_fov_by_id(fov_id)
    fov_stem = _sanitize(fov_info.display_name)

    # Build resolution kwargs for pixel size metadata
    resolution_kwargs: dict = {}
    if fov_info.pixel_size_um:
        res = 1.0 / fov_info.pixel_size_um
        resolution_kwargs["resolution"] = (res, res)
        resolution_kwargs["metadata"] = {"unit": "um"}

    # ImageJ format only supports uint8, uint16, float32
    _IMAGEJ_DTYPES = {"uint8", "uint16", "float32"}

    def _write(path: Path, data) -> None:
        """Write data to a TIFF, respecting overwrite flag."""
        if not overwrite and path.exists():
            raise FileExistsError(f"File exists: {path}")
        kwargs = dict(resolution_kwargs)
        if str(data.dtype) in _IMAGEJ_DTYPES:
            kwargs["imagej"] = True
        tifffile.imwrite(str(path), data, **kwargs)
        result.written.append(path)

    # --- 1. Channel images ---
    channels = store.get_channels()
    for ch in channels:
        try:
            img = store.read_image_numpy(fov_id, ch.name)
        except Exception as exc:
            result.skipped.append(f"channel {ch.name}: {exc}")
            continue
        path = _unique_path(output_dir / f"{fov_stem}_{_sanitize(ch.name)}.tiff", used_paths)
        _write(path, img)
        used_paths.add(path)

    # --- 2. Segmentation labels + 3. Threshold masks (from config) ---
    try:
        config_entries = store.get_fov_config(fov_id)
    except Exception:
        config_entries = []

    # Deduplicate segmentation IDs (cellular only)
    seen_seg_ids: set[int] = set()
    for entry in config_entries:
        seg_id = entry.segmentation_id
        if seg_id in seen_seg_ids:
            continue
        seen_seg_ids.add(seg_id)

        try:
            seg_info = store.get_segmentation(seg_id)
        except Exception as exc:
            result.skipped.append(f"segmentation {seg_id}: {exc}")
            continue

        if seg_info.seg_type != "cellular":
            continue

        try:
            labels = store.read_labels(seg_id)
        except Exception as exc:
            result.skipped.append(f"labels for {seg_info.name}: {exc}")
            continue

        path = _unique_path(
            output_dir / f"{fov_stem}_{_sanitize(seg_info.name)}_labels.tiff",
            used_paths,
        )
        _write(path, labels)
        used_paths.add(path)

    # Deduplicate threshold IDs (non-null, source_fov must match)
    seen_thr_ids: set[int] = set()
    for entry in config_entries:
        thr_id = entry.threshold_id
        if thr_id is None or thr_id in seen_thr_ids:
            continue
        seen_thr_ids.add(thr_id)

        try:
            thr_info = store.get_threshold(thr_id)
        except Exception as exc:
            result.skipped.append(f"threshold {thr_id}: {exc}")
            continue

        if thr_info.source_fov_id != fov_id:
            continue

        try:
            mask = store.read_mask(thr_id)
        except Exception as exc:
            result.skipped.append(f"mask for {thr_info.name}: {exc}")
            continue

        path = _unique_path(
            output_dir / f"{fov_stem}_{_sanitize(thr_info.name)}_mask.tiff",
            used_paths,
        )
        _write(path, mask)
        used_paths.add(path)

    return result
