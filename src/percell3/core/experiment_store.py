"""ExperimentStore — central interface for a PerCell 3 experiment."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)
_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.+()-]{0,254}$")


def _validate_name(value: str, field: str = "name") -> str:
    """Validate that a name is safe for use in file system paths.

    Raises:
        ValueError: If the name is empty, too long, or contains unsafe characters.
    """
    if not value:
        raise ValueError(f"{field} must not be empty")
    if ".." in value:
        raise ValueError(f"{field} must not contain '..': {value!r}")
    if not _VALID_NAME_RE.match(value):
        raise ValueError(
            f"{field} contains invalid characters: {value!r}. "
            "Allowed: alphanumeric, spaces, dots, hyphens, underscores, +, parentheses."
        )
    return value

import dask.array as da
import numpy as np
import pandas as pd

from percell3.core import queries, zarr_io
from percell3.core.exceptions import (
    BioRepNotFoundError,
    ChannelNotFoundError,
    ExperimentError,
    ExperimentNotFoundError,
    MeasurementConfigNotFoundError,
    RunNameError,
    SegmentationRunNotFoundError,
    ThresholdRunNotFoundError,
)
from percell3.core.models import (
    CellRecord,
    ChannelConfig,
    FovInfo,
    MeasurementConfigEntry,
    MeasurementConfigInfo,
    MeasurementRecord,
    ParticleRecord,
    SegmentationRunInfo,
    ThresholdRunInfo,
)
from percell3.core.schema import create_schema, open_database


def _rename_mask_groups(
    masks_path: Path,
    old_channel: str,
    new_channel: str,
) -> None:
    """Rename channel-level groups in the masks store.

    With run-scoped paths, the layout is:
        fov_<id>/<channel>/run_<id>/mask/
        fov_<id>/<channel>/run_<id>/particles/

    Renaming a channel means renaming the <channel> group under each fov.
    """
    import shutil

    if not masks_path.exists():
        return

    # Walk FOV directories and rename channel groups
    for fov_dir in masks_path.iterdir():
        if not fov_dir.is_dir() or not fov_dir.name.startswith("fov_"):
            continue
        old_ch_dir = fov_dir / old_channel
        new_ch_dir = fov_dir / new_channel
        if old_ch_dir.exists():
            old_ch_dir.rename(new_ch_dir)


class ExperimentStore:
    """Central interface for a PerCell 3 experiment.

    An experiment is a .percell directory containing:
    - experiment.db (SQLite metadata)
    - images.zarr (raw images in OME-Zarr)
    - labels.zarr (segmentation label images)
    - masks.zarr (binary analysis masks)
    - exports/ (CSV and other exports)
    """

    def __init__(self, path: Path, conn: sqlite3.Connection) -> None:
        self._path = path
        self._conn = conn

    # --- Lifecycle ---

    @classmethod
    def create(
        cls,
        path: Path,
        name: str = "",
        description: str = "",
        overwrite: bool = False,
    ) -> ExperimentStore:
        """Create a new .percell experiment directory.

        Args:
            path: Directory for the new experiment.
            name: Human-readable experiment name.
            description: Experiment description.
            overwrite: If True, delete existing non-empty directory contents
                before creating. Empty directories are always accepted.
        """
        import shutil

        path = Path(path)
        if path.exists():
            if any(path.iterdir()):
                if not overwrite:
                    raise ExperimentError(
                        f"Directory is not empty: {path}  "
                        "(use overwrite=True to replace)"
                    )
                # Remove old contents before re-creating
                shutil.rmtree(path)
                path.mkdir(parents=True)
            # else: empty directory — proceed without error
        else:
            path.mkdir(parents=True)

        # Create SQLite database
        db_path = path / "experiment.db"
        conn = create_schema(db_path, name=name, description=description)

        # Create zarr stores
        zarr_io.init_zarr_store(path / "images.zarr")
        zarr_io.init_zarr_store(path / "labels.zarr")
        zarr_io.init_zarr_store(path / "masks.zarr")

        # Create exports directory
        (path / "exports").mkdir(exist_ok=True)

        return cls(path, conn)

    @classmethod
    def open(cls, path: Path) -> ExperimentStore:
        """Open an existing .percell experiment directory."""
        path = Path(path)
        if not path.exists():
            raise ExperimentNotFoundError(str(path))
        db_path = path / "experiment.db"
        if not db_path.exists():
            raise ExperimentNotFoundError(str(path))
        conn = open_database(db_path)
        return cls(path, conn)

    def close(self) -> None:
        """Close database connections."""
        if self._conn:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> ExperimentStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ExperimentStore({self._path!r})"

    # --- Properties ---

    @property
    def path(self) -> Path:
        return self._path

    @property
    def name(self) -> str:
        return queries.get_experiment_name(self._conn)

    @property
    def db_path(self) -> Path:
        return self._path / "experiment.db"

    @property
    def images_zarr_path(self) -> Path:
        return self._path / "images.zarr"

    @property
    def labels_zarr_path(self) -> Path:
        return self._path / "labels.zarr"

    @property
    def masks_zarr_path(self) -> Path:
        return self._path / "masks.zarr"

    # --- Channel Management ---

    def add_channel(
        self,
        name: str,
        role: str | None = None,
        color: str | None = None,
        excitation_nm: float | None = None,
        emission_nm: float | None = None,
        is_segmentation: bool = False,
    ) -> int:
        _validate_name(name, "channel name")
        return queries.insert_channel(
            self._conn, name, role=role, color=color,
            excitation_nm=excitation_nm, emission_nm=emission_nm,
            is_segmentation=is_segmentation,
        )

    def get_channels(self) -> list[ChannelConfig]:
        return queries.select_channels(self._conn)

    def get_channel(self, name: str) -> ChannelConfig:
        return queries.select_channel_by_name(self._conn, name)

    # --- Biological Replicate Management ---

    def add_bio_rep(self, name: str) -> int:
        """Add an experiment-global biological replicate."""
        _validate_name(name, "bio_rep name")
        return queries.insert_bio_rep(self._conn, name)

    def get_bio_reps(self) -> list[str]:
        """Return all bio rep names."""
        return queries.select_bio_reps(self._conn)

    def get_bio_rep(self, name: str) -> str:
        row = queries.select_bio_rep_by_name(self._conn, name)
        return row["name"]

    # --- Condition/Timepoint/FOV Management ---

    def add_condition(self, name: str, description: str = "") -> int:
        _validate_name(name, "condition name")
        return queries.insert_condition(self._conn, name, description)

    def add_timepoint(self, name: str, time_seconds: float | None = None) -> int:
        _validate_name(name, "timepoint name")
        return queries.insert_timepoint(self._conn, name, time_seconds)

    def add_fov(
        self,
        condition: str,
        bio_rep: str | None = None,
        display_name: str | None = None,
        timepoint: str | None = None,
        width: int | None = None,
        height: int | None = None,
        pixel_size_um: float | None = None,
        source_file: str | None = None,
    ) -> int:
        """Add a FOV. Auto-generates display_name and creates bio_rep 'N1' if needed.

        Returns the new FOV ID.
        """
        cond_id = queries.select_condition_id(self._conn, condition)

        # Lazy creation: ensure a default bio rep exists
        br_name = bio_rep or "N1"
        try:
            br_row = queries.select_bio_rep_by_name(self._conn, br_name)
            bio_rep_id = br_row["id"]
        except BioRepNotFoundError:
            _validate_name(br_name, "bio_rep name")
            bio_rep_id = queries.insert_bio_rep(self._conn, br_name)

        # Auto-generate display_name if not provided
        if display_name is None:
            display_name = queries.generate_display_name(
                self._conn, condition, br_name,
            )
        _validate_name(display_name, "fov display_name")

        tp_id = queries.select_timepoint_id(self._conn, timepoint) if timepoint else None
        return queries.insert_fov(
            self._conn, display_name=display_name,
            condition_id=cond_id, bio_rep_id=bio_rep_id,
            timepoint_id=tp_id, width=width, height=height,
            pixel_size_um=pixel_size_um, source_file=source_file,
        )

    def get_conditions(self) -> list[str]:
        return queries.select_conditions(self._conn)

    def get_timepoints(self) -> list[str]:
        return queries.select_timepoints(self._conn)

    def get_fovs(
        self,
        condition: str | None = None,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> list[FovInfo]:
        cond_id = queries.select_condition_id(self._conn, condition) if condition else None
        br_id = None
        if bio_rep:
            try:
                br_row = queries.select_bio_rep_by_name(self._conn, bio_rep)
                br_id = br_row["id"]
            except BioRepNotFoundError:
                return []
        tp_id = queries.select_timepoint_id(self._conn, timepoint) if timepoint else None
        return queries.select_fovs(
            self._conn, condition_id=cond_id, bio_rep_id=br_id, timepoint_id=tp_id,
        )

    def get_fov_by_id(self, fov_id: int) -> FovInfo:
        """Get a single FOV by ID."""
        return queries.select_fov_by_id(self._conn, fov_id)

    # --- Rename operations ---

    def rename_experiment(self, new_name: str) -> None:
        """Rename the experiment (metadata only, does not rename directory)."""
        queries.rename_experiment(self._conn, new_name)

    def rename_condition(self, old_name: str, new_name: str) -> None:
        """Rename a condition. DB-only — zarr paths use fov_id, not names."""
        _validate_name(new_name, "condition name")
        queries.rename_condition(self._conn, old_name, new_name)

    def rename_channel(self, old_name: str, new_name: str) -> None:
        """Rename a channel. Updates SQLite and NGFF metadata."""
        _validate_name(new_name, "channel name")
        queries.rename_channel(self._conn, old_name, new_name)
        zarr_io.rename_channel_in_ngff(self.images_zarr_path, old_name, new_name)
        _rename_mask_groups(self.masks_zarr_path, old_name, new_name)

    def rename_bio_rep(self, old_name: str, new_name: str) -> None:
        """Rename a biological replicate. DB-only."""
        _validate_name(new_name, "bio_rep name")
        queries.rename_bio_rep(self._conn, old_name, new_name)

    def rename_fov(self, fov_id: int, new_display_name: str) -> None:
        """Rename a FOV by ID. DB-only — zarr paths use fov_id."""
        _validate_name(new_display_name, "fov display_name")
        queries.rename_fov(self._conn, fov_id, new_display_name)

    # --- Image I/O ---

    def _channels_meta(self) -> list[dict]:
        """Build channel metadata list for NGFF."""
        channels = self.get_channels()
        return [{"name": ch.name, "color": ch.color or "FFFFFF"} for ch in channels]

    def write_image(self, fov_id: int, channel: str, data: np.ndarray) -> None:
        fov_info = self.get_fov_by_id(fov_id)
        gp = zarr_io.image_group_path(fov_id)
        ch = self.get_channel(channel)
        channels = self.get_channels()

        zarr_io.write_image_channel(
            self.images_zarr_path,
            gp,
            channel_index=ch.display_order,
            num_channels=len(channels),
            data=data,
            channels_meta=self._channels_meta(),
            pixel_size_um=fov_info.pixel_size_um,
        )

    def read_image(self, fov_id: int, channel: str) -> da.Array:
        gp = zarr_io.image_group_path(fov_id)
        ch = self.get_channel(channel)
        return zarr_io.read_image_channel(self.images_zarr_path, gp, ch.display_order)

    def read_image_numpy(self, fov_id: int, channel: str) -> np.ndarray:
        gp = zarr_io.image_group_path(fov_id)
        ch = self.get_channel(channel)
        return zarr_io.read_image_channel_numpy(
            self.images_zarr_path, gp, ch.display_order
        )

    # --- Label Images ---

    def write_labels(self, fov_id: int, labels: np.ndarray, segmentation_run_id: int) -> None:
        fov_info = self.get_fov_by_id(fov_id)
        gp = zarr_io.label_group_path(fov_id, segmentation_run_id)
        img_gp = zarr_io.image_group_path(fov_id)
        source_path = f"../../images.zarr/{img_gp}"
        zarr_io.write_labels(
            self.labels_zarr_path, gp, labels,
            source_image_path=source_path,
            pixel_size_um=fov_info.pixel_size_um,
        )

    def read_labels(self, fov_id: int, segmentation_run_id: int) -> np.ndarray:
        gp = zarr_io.label_group_path(fov_id, segmentation_run_id)
        return zarr_io.read_labels(self.labels_zarr_path, gp)

    # --- Cell Records ---

    def add_cells(self, cells: list[CellRecord]) -> list[int]:
        ids = queries.insert_cells(self._conn, cells)
        # Update status cache for affected FOVs
        fov_ids = {c.fov_id for c in cells}
        for fov_id in fov_ids:
            self.update_fov_status_cache(fov_id)
        return ids

    def get_cells(
        self,
        fov_id: int | None = None,
        condition: str | None = None,
        bio_rep: str | None = None,
        is_valid: bool = True,
        min_area: float | None = None,
        max_area: float | None = None,
        tags: list[str] | None = None,
    ) -> pd.DataFrame:
        cond_id = queries.select_condition_id(self._conn, condition) if condition else None
        br_id = None
        if bio_rep:
            br_row = queries.select_bio_rep_by_name(self._conn, bio_rep)
            br_id = br_row["id"]

        tag_ids = None
        if tags:
            tag_ids = []
            for tag_name in tags:
                tid = queries.select_tag_id(self._conn, tag_name)
                if tid is not None:
                    tag_ids.append(tid)

        rows = queries.select_cells(
            self._conn,
            condition_id=cond_id,
            bio_rep_id=br_id,
            fov_id=fov_id,
            is_valid=is_valid,
            min_area=min_area,
            max_area=max_area,
            tag_ids=tag_ids or None,
        )
        return pd.DataFrame(rows)

    def get_cell_count(
        self,
        fov_id: int | None = None,
        condition: str | None = None,
        is_valid: bool = True,
    ) -> int:
        cond_id = queries.select_condition_id(self._conn, condition) if condition else None
        return queries.count_cells(
            self._conn, condition_id=cond_id, fov_id=fov_id, is_valid=is_valid,
        )

    def delete_cells_for_fov(self, fov_id: int) -> int:
        """Delete all cells (and measurements/tags) for a FOV.

        Returns:
            Number of cells deleted.
        """
        count = queries.delete_cells_for_fov(self._conn, fov_id)
        self.update_fov_status_cache(fov_id)
        return count

    def delete_fov(self, fov_id: int) -> None:
        """Delete a FOV and all its data.

        SQLite CASCADE handles: segmentation_runs, threshold_runs, cells,
        measurements, particles, config_entries, fov_status_cache, fov_tags.

        Zarr groups are cleaned up manually after the SQLite delete.

        Args:
            fov_id: Database ID of the FOV to delete.

        Raises:
            ExperimentError: If the FOV does not exist.
        """
        import shutil

        # Validate FOV exists
        self.get_fov_by_id(fov_id)  # raises ExperimentError if not found

        # 1. SQLite CASCADE delete (removes all dependent rows)
        queries.delete_fov_row(self._conn, fov_id)

        # 2. Remove zarr groups (best-effort cleanup after SQLite commit)
        fov_group = zarr_io.fov_group_path(fov_id)
        for zarr_root in (self.images_zarr_path, self.labels_zarr_path, self.masks_zarr_path):
            group_dir = zarr_root / fov_group
            if group_dir.exists():
                shutil.rmtree(group_dir)

    def get_fov_segmentation_summary(self) -> dict[int, tuple[int, str | None]]:
        """Return segmentation status for all FOVs.

        Returns:
            Dict mapping fov_id -> (cell_count, last_model_name).
            FOVs with no cells return (0, None).
        """
        return queries.select_fov_segmentation_summary(self._conn)

    # --- Measurements ---

    def add_measurements(self, measurements: list[MeasurementRecord]) -> None:
        queries.insert_measurements(self._conn, measurements)
        # Update status cache for affected FOVs
        cell_ids = {m.cell_id for m in measurements}
        if cell_ids:
            placeholders = ",".join("?" * len(cell_ids))
            rows = self._conn.execute(
                f"SELECT DISTINCT fov_id FROM cells WHERE id IN ({placeholders})",
                list(cell_ids),
            ).fetchall()
            for r in rows:
                self.update_fov_status_cache(r["fov_id"])

    def list_measured_channels(self) -> list[str]:
        """Return sorted channel names that have at least one measurement."""
        return queries.select_distinct_measured_channels(self._conn)

    def list_measured_metrics(self) -> list[str]:
        """Return sorted metric names that have at least one measurement."""
        return queries.select_distinct_measured_metrics(self._conn)

    def get_measurements(
        self,
        cell_ids: list[int] | None = None,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        scope: str | None = None,
    ) -> pd.DataFrame:
        channel_ids = None
        if channels:
            channel_ids = [self.get_channel(ch).id for ch in channels]
        rows = queries.select_measurements(
            self._conn, cell_ids=cell_ids, channel_ids=channel_ids,
            metrics=metrics, scope=scope,
        )
        return pd.DataFrame(rows)

    def get_measurement_pivot(
        self,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        scope: str | None = None,
        include_cell_info: bool = True,
    ) -> pd.DataFrame:
        from percell3.core.constants import PARTICLE_AREA_METRICS

        df = self.get_measurements(channels=channels, metrics=metrics, scope=scope)
        if df.empty:
            return df

        # Convert particle area metrics from pixels to um2
        area_mask = df["metric"].isin(PARTICLE_AREA_METRICS)
        if area_mask.any():
            cells_ps = self.get_cells(is_valid=False)
            if not cells_ps.empty and "pixel_size_um" in cells_ps.columns:
                ps_map = cells_ps.set_index("id")["pixel_size_um"]
                ps = df.loc[area_mask, "cell_id"].map(ps_map)
                df.loc[area_mask, "value"] = df.loc[area_mask, "value"] * ps * ps

        # Build pivot column name: channel_metric for whole_cell,
        # channel_metric_scope for mask scopes
        has_mask_scopes = (df["scope"] != "whole_cell").any()
        if has_mask_scopes:
            df["col"] = df.apply(
                lambda r: (
                    f"{r['channel']}_{r['metric']}"
                    if r["scope"] == "whole_cell"
                    else f"{r['channel']}_{r['metric']}_{r['scope']}"
                ),
                axis=1,
            )
        else:
            df["col"] = df["channel"] + "_" + df["metric"]
        pivot = df.pivot_table(
            index="cell_id", columns="col", values="value", aggfunc="first",
        )
        pivot = pivot.reset_index()

        if include_cell_info:
            cells_df = self.get_cells(is_valid=False)
            if not cells_df.empty:
                # Merge cell info
                cell_cols = ["id", "fov_name", "condition_name", "bio_rep_name",
                             "area_um2", "centroid_x", "centroid_y"]
                available = [c for c in cell_cols if c in cells_df.columns]
                if available:
                    merge_df = cells_df[available].rename(columns={"id": "cell_id"})
                    pivot = pivot.merge(merge_df, on="cell_id", how="left")

        # Merge group tags if any exist
        if "cell_id" in pivot.columns:
            pivot, _ = self._merge_group_tags(pivot)

        return pivot

    # --- Masks ---

    def write_mask(self, fov_id: int, channel: str, mask: np.ndarray, threshold_run_id: int) -> None:
        fov_info = self.get_fov_by_id(fov_id)
        gp = zarr_io.mask_group_path(fov_id, channel, threshold_run_id)
        zarr_io.write_mask(
            self.masks_zarr_path, gp, mask,
            pixel_size_um=fov_info.pixel_size_um,
        )

    def read_mask(self, fov_id: int, channel: str, threshold_run_id: int) -> np.ndarray:
        gp = zarr_io.mask_group_path(fov_id, channel, threshold_run_id)
        return zarr_io.read_mask(self.masks_zarr_path, gp)

    # --- Segmentation Runs ---

    def add_segmentation_run(
        self,
        fov_id: int,
        channel: str,
        model_name: str,
        parameters: dict[str, object] | None = None,
        name: str | None = None,
    ) -> int:
        """Create a named segmentation run for a FOV.

        Args:
            fov_id: FOV to attach the run to.
            channel: Channel name used for segmentation.
            model_name: Model name (e.g. "cyto3").
            parameters: Optional dict of segmentation parameters.
            name: Run name. Auto-generated from model_name if not provided.

        Returns:
            The segmentation run ID.
        """
        ch = self.get_channel(channel)
        if name is None:
            name = self._generate_run_name(
                model_name, fov_id, "segmentation_runs",
            )
        else:
            _validate_name(name, "run name")
        try:
            run_id = queries.insert_segmentation_run(
                self._conn, fov_id, ch.id, name, model_name, parameters,
            )
        except sqlite3.IntegrityError:
            raise RunNameError(name, f"a segmentation run named {name!r} already exists on this FOV")
        self.update_fov_status_cache(fov_id)
        return run_id

    def list_segmentation_runs(self, fov_id: int) -> list[SegmentationRunInfo]:
        """List all segmentation runs for a FOV."""
        return queries.select_segmentation_runs_for_fov(self._conn, fov_id)

    def get_segmentation_run(self, run_id: int) -> SegmentationRunInfo:
        """Get a single segmentation run by ID."""
        return queries.select_segmentation_run(self._conn, run_id)

    def rename_segmentation_run(self, run_id: int, new_name: str) -> None:
        """Rename a segmentation run."""
        _validate_name(new_name, "run name")
        try:
            queries.rename_segmentation_run(self._conn, run_id, new_name)
        except sqlite3.IntegrityError:
            raise RunNameError(new_name, f"a segmentation run named {new_name!r} already exists on this FOV")

    def delete_segmentation_run(self, run_id: int) -> None:
        """Delete a segmentation run, its cells, measurements, particles, and Zarr data."""
        run = self.get_segmentation_run(run_id)
        fov_id = run.fov_id

        # CASCADE handles cells, measurements, particles, config entries in SQLite
        queries.delete_segmentation_run(self._conn, run_id)

        # Clean up Zarr data
        gp = zarr_io.label_group_path(fov_id, run_id)
        zarr_io.delete_zarr_group(self.labels_zarr_path, gp)

        self.update_fov_status_cache(fov_id)

    def update_segmentation_run_cell_count(
        self, run_id: int, cell_count: int
    ) -> None:
        """Update the cell count for a segmentation run."""
        queries.update_segmentation_run_cell_count(self._conn, run_id, cell_count)

    # --- Threshold Runs ---

    def add_threshold_run(
        self,
        fov_id: int,
        channel: str,
        method: str,
        parameters: dict[str, object] | None = None,
        name: str | None = None,
    ) -> int:
        """Create a named threshold run for a FOV.

        Args:
            fov_id: FOV to attach the run to.
            channel: Channel name used for thresholding.
            method: Thresholding method name (e.g. "otsu").
            parameters: Optional dict of threshold parameters.
            name: Run name. Auto-generated from method if not provided.

        Returns:
            The threshold run ID.
        """
        ch = self.get_channel(channel)
        if name is None:
            name = self._generate_run_name(
                method, fov_id, "threshold_runs", channel_id=ch.id,
            )
        else:
            _validate_name(name, "run name")
        try:
            run_id = queries.insert_threshold_run(
                self._conn, fov_id, ch.id, name, method, parameters,
            )
        except sqlite3.IntegrityError:
            raise RunNameError(name, f"a threshold run named {name!r} already exists on this FOV+channel")
        self.update_fov_status_cache(fov_id)
        return run_id

    def list_threshold_runs(
        self, fov_id: int, channel: str | None = None,
    ) -> list[ThresholdRunInfo]:
        """List threshold runs for a FOV, optionally filtered by channel."""
        return queries.select_threshold_runs_for_fov(
            self._conn, fov_id, channel_name=channel,
        )

    def get_threshold_run(self, run_id: int) -> ThresholdRunInfo:
        """Get a single threshold run by ID."""
        return queries.select_threshold_run(self._conn, run_id)

    def rename_threshold_run(self, run_id: int, new_name: str) -> None:
        """Rename a threshold run."""
        _validate_name(new_name, "run name")
        try:
            queries.rename_threshold_run(self._conn, run_id, new_name)
        except sqlite3.IntegrityError:
            raise RunNameError(new_name, f"a threshold run named {new_name!r} already exists on this FOV+channel")

    def delete_threshold_run(self, run_id: int) -> None:
        """Delete a threshold run, its particles, measurements, and Zarr data."""
        run = self.get_threshold_run(run_id)
        fov_id = run.fov_id

        # CASCADE handles particles, measurements, config entries in SQLite
        queries.delete_threshold_run(self._conn, run_id)

        # Clean up Zarr data (mask + particle labels)
        mask_gp = zarr_io.mask_group_path(fov_id, run.channel, run_id)
        zarr_io.delete_zarr_group(self.masks_zarr_path, mask_gp)
        particle_gp = zarr_io.particle_label_group_path(fov_id, run.channel, run_id)
        zarr_io.delete_zarr_group(self.masks_zarr_path, particle_gp)

        self.update_fov_status_cache(fov_id)

    def update_threshold_run_value(self, run_id: int, threshold_value: float) -> None:
        """Update the computed threshold value for a run."""
        queries.update_threshold_run_value(self._conn, run_id, threshold_value)

    # --- Analysis Runs ---

    def start_analysis_run(
        self,
        plugin_name: str,
        parameters: dict | None = None,
    ) -> int:
        return queries.insert_analysis_run(self._conn, plugin_name, parameters)

    def complete_analysis_run(
        self,
        run_id: int,
        status: str = "completed",
        cell_count: int | None = None,
    ) -> None:
        queries.complete_analysis_run(self._conn, run_id, status, cell_count)

    # --- Introspection ---

    def get_tags(self) -> list[str]:
        """Return all tag names."""
        return queries.select_tags(self._conn)

    def get_segmentation_runs(self, fov_id: int | None = None) -> list[SegmentationRunInfo]:
        """Return segmentation runs, optionally filtered by FOV."""
        if fov_id is not None:
            return queries.select_segmentation_runs_for_fov(self._conn, fov_id)
        # All runs across all FOVs
        rows = self._conn.execute(
            "SELECT sr.id, sr.fov_id, ch.name AS channel, sr.name, sr.model_name, "
            "sr.parameters, sr.cell_count, sr.created_at "
            "FROM segmentation_runs sr "
            "JOIN channels ch ON sr.channel_id = ch.id "
            "ORDER BY sr.id",
        ).fetchall()
        return [queries._row_to_segmentation_run(r) for r in rows]

    def get_analysis_runs(self) -> list[dict]:
        """Return all analysis runs."""
        return queries.select_analysis_runs(self._conn)

    # --- Tags ---

    def add_tag(self, name: str, color: str | None = None) -> int:
        return queries.insert_tag(self._conn, name, color)

    def tag_cells(self, cell_ids: list[int], tag: str) -> None:
        tag_id = queries.select_tag_id(self._conn, tag)
        if tag_id is None:
            raise ExperimentError(f"Tag not found: {tag}")
        queries.insert_cell_tags(self._conn, cell_ids, tag_id)

    def untag_cells(self, cell_ids: list[int], tag: str) -> None:
        tag_id = queries.select_tag_id(self._conn, tag)
        if tag_id is None:
            raise ExperimentError(f"Tag not found: {tag}")
        queries.delete_cell_tags(self._conn, cell_ids, tag_id)

    def delete_tags_by_prefix(
        self,
        prefix: str,
        cell_ids: list[int] | None = None,
    ) -> int:
        """Delete cell_tags (and optionally tags) matching a name prefix.

        Args:
            prefix: Tag name prefix (e.g., "group:GFP:mean_intensity:").
            cell_ids: If provided, only remove cell_tags for these cells.
                If None, removes tags entirely.

        Returns:
            Number of cell_tag rows deleted.
        """
        return queries.delete_tags_by_prefix(self._conn, prefix, cell_ids)

    def get_cell_group_tags(
        self,
        cell_ids: list[int],
    ) -> dict[int, dict[str, str]]:
        """Get group tag columns for cells.

        Parses tags like ``group:GFP:mean_intensity:g1`` into column-value pairs.
        If only one (channel, metric) grouping exists, uses column name ``group``.
        Otherwise uses ``group_{channel}_{metric}``.

        Args:
            cell_ids: Cell IDs to look up.

        Returns:
            Dict mapping cell_id -> {column_name: group_value}.
        """
        rows = queries.select_group_tags_for_cells(self._conn, cell_ids)
        if not rows:
            return {}

        # Parse tag names: group:{channel}:{metric}:{value}
        parsed: list[tuple[int, str, str, str]] = []  # (cell_id, channel, metric, value)
        for cell_id, tag_name in rows:
            parts = tag_name.split(":")
            if len(parts) == 4:
                _, channel, metric, value = parts
                parsed.append((cell_id, channel, metric, value))

        if not parsed:
            return {}

        # Determine unique (channel, metric) combinations
        grouping_keys = {(ch, m) for _, ch, m, _ in parsed}
        use_simple = len(grouping_keys) == 1

        result: dict[int, dict[str, str]] = {}
        for cell_id, channel, metric, value in parsed:
            col_name = "group" if use_simple else f"group_{channel}_{metric}"
            result.setdefault(cell_id, {})[col_name] = value

        return result

    def _merge_group_tags(
        self,
        df: pd.DataFrame,
        cell_id_column: str = "cell_id",
    ) -> tuple[pd.DataFrame, list[str]]:
        """Merge group tag columns into a DataFrame.

        Args:
            df: DataFrame with a cell_id column.
            cell_id_column: Name of the cell ID column.

        Returns:
            Tuple of (merged_df, group_column_names).
        """
        cell_ids = df[cell_id_column].unique().tolist()
        group_tags = self.get_cell_group_tags(cell_ids)
        if not group_tags:
            return df, []
        group_df = pd.DataFrame.from_dict(group_tags, orient="index")
        group_df.index.name = cell_id_column
        group_df = group_df.reset_index()
        df = df.merge(group_df, on=cell_id_column, how="left")
        group_cols = [c for c in group_df.columns if c != cell_id_column]
        for col in group_cols:
            if col in df.columns:
                df[col] = df[col].fillna("")
        return df, group_cols

    # --- Particles ---

    def add_particles(self, particles: list[ParticleRecord]) -> None:
        """Bulk insert particle records."""
        queries.insert_particles(self._conn, particles)
        # Update status cache for affected FOVs
        cell_ids = {p.cell_id for p in particles}
        if cell_ids:
            placeholders = ",".join("?" * len(cell_ids))
            rows = self._conn.execute(
                f"SELECT DISTINCT fov_id FROM cells WHERE id IN ({placeholders})",
                list(cell_ids),
            ).fetchall()
            for r in rows:
                self.update_fov_status_cache(r["fov_id"])

    def get_particles(
        self,
        cell_ids: list[int] | None = None,
        threshold_run_id: int | None = None,
    ) -> pd.DataFrame:
        """Query particles with optional filters."""
        rows = queries.select_particles(
            self._conn,
            cell_ids=cell_ids,
            threshold_run_id=threshold_run_id,
        )
        return pd.DataFrame(rows)

    def delete_particles_for_fov(self, fov_id: int) -> int:
        """Delete all particles for cells in a FOV.

        Returns:
            Number of particles deleted.
        """
        count = queries.delete_particles_for_fov(self._conn, fov_id)
        self.update_fov_status_cache(fov_id)
        return count

    def delete_particles_for_threshold_run(self, threshold_run_id: int) -> int:
        """Delete all particles for a specific threshold run."""
        return queries.delete_particles_for_threshold_run(
            self._conn, threshold_run_id,
        )

    def get_threshold_runs(self, fov_id: int | None = None) -> list[ThresholdRunInfo]:
        """Return threshold runs, optionally filtered by FOV."""
        if fov_id is not None:
            return queries.select_threshold_runs_for_fov(self._conn, fov_id)
        rows = self._conn.execute(
            "SELECT tr.id, tr.fov_id, ch.name AS channel, tr.name, tr.method, "
            "tr.parameters, tr.threshold_value, tr.created_at "
            "FROM threshold_runs tr "
            "JOIN channels ch ON tr.channel_id = ch.id "
            "ORDER BY tr.id",
        ).fetchall()
        return [queries._row_to_threshold_run(r) for r in rows]

    def get_experiment_summary(self) -> list[dict]:
        """Per-FOV summary of cells, measurements, thresholds, and particles."""
        return queries.select_experiment_summary(self._conn)

    # --- FOV Status Cache ---

    def update_fov_status_cache(self, fov_id: int) -> None:
        """Rebuild the JSON status cache for a single FOV."""
        queries.upsert_fov_status_cache_batch(self._conn, [fov_id])

    def update_fov_status_cache_batch(self, fov_ids: list[int]) -> None:
        """Rebuild the JSON status cache for multiple FOVs."""
        queries.upsert_fov_status_cache_batch(self._conn, fov_ids)

    def refresh_all_status_cache(self) -> None:
        """Refresh status cache for all FOVs."""
        fovs = self.get_fovs()
        fov_ids = [fov.id for fov in fovs]
        if fov_ids:
            self.update_fov_status_cache_batch(fov_ids)

    # --- FOV Tags ---

    def add_fov_tag(self, fov_id: int, tag_name: str) -> None:
        """Tag a FOV. Creates the tag if it doesn't exist."""
        tag_id = queries.select_tag_id(self._conn, tag_name)
        if tag_id is None:
            tag_id = self.add_tag(tag_name)
        queries.insert_fov_tag(self._conn, fov_id, tag_id)

    def remove_fov_tag(self, fov_id: int, tag_name: str) -> None:
        """Remove a tag from a FOV."""
        tag_id = queries.select_tag_id(self._conn, tag_name)
        if tag_id is not None:
            queries.delete_fov_tag(self._conn, fov_id, tag_id)

    def get_fov_tags(self, fov_id: int) -> list[str]:
        """Get all tag names for a FOV."""
        rows = queries.select_fov_tags(self._conn, fov_id)
        return [r["name"] for r in rows]

    # --- Particle Label I/O ---

    def write_particle_labels(
        self, fov_id: int, channel: str, labels: np.ndarray, threshold_run_id: int,
    ) -> None:
        """Write a particle label image to masks.zarr."""
        fov_info = self.get_fov_by_id(fov_id)
        gp = zarr_io.particle_label_group_path(fov_id, channel, threshold_run_id)
        zarr_io.write_particle_labels(
            self.masks_zarr_path, gp, labels,
            pixel_size_um=fov_info.pixel_size_um,
        )

    def read_particle_labels(
        self, fov_id: int, channel: str, threshold_run_id: int,
    ) -> np.ndarray:
        """Read a particle label image from masks.zarr."""
        gp = zarr_io.particle_label_group_path(fov_id, channel, threshold_run_id)
        return zarr_io.read_particle_labels(self.masks_zarr_path, gp)

    # --- Measurement Configs ---

    def create_measurement_config(self, name: str) -> int:
        """Create a measurement configuration and set it as active.

        Args:
            name: Config name (must be unique).

        Returns:
            The config ID.
        """
        _validate_name(name, "config name")
        try:
            config_id = queries.insert_measurement_config(self._conn, name)
        except sqlite3.IntegrityError:
            raise DuplicateError("measurement config", name)
        # Auto-set as active (most recently created is active by default)
        self.set_active_measurement_config(config_id)
        return config_id

    def add_measurement_config_entry(
        self,
        config_id: int,
        fov_id: int,
        segmentation_run_id: int,
        threshold_run_id: int | None = None,
    ) -> int:
        """Add an entry to a measurement config.

        Args:
            config_id: Config to add the entry to.
            fov_id: FOV for this entry.
            segmentation_run_id: Segmentation run to use.
            threshold_run_id: Optional threshold run to use.

        Returns:
            The entry ID.

        Raises:
            ValueError: If threshold_run_id belongs to a different FOV.
        """
        # Validate threshold run belongs to same FOV
        if threshold_run_id is not None:
            run = self.get_threshold_run(threshold_run_id)
            if run.fov_id != fov_id:
                raise ValueError(
                    f"Threshold run {threshold_run_id} belongs to FOV {run.fov_id}, "
                    f"not FOV {fov_id}"
                )
        return queries.insert_measurement_config_entry(
            self._conn, config_id, fov_id, segmentation_run_id, threshold_run_id,
        )

    def get_measurement_config_entries(
        self, config_id: int,
    ) -> list[MeasurementConfigEntry]:
        """Return all entries for a measurement config."""
        return queries.select_measurement_config_entries(self._conn, config_id)

    def list_measurement_configs(self) -> list[MeasurementConfigInfo]:
        """Return all measurement configurations."""
        return queries.select_measurement_configs(self._conn)

    def get_measurement_config(self, config_id: int) -> MeasurementConfigInfo:
        """Get a single measurement config by ID."""
        return queries.select_measurement_config(self._conn, config_id)

    def delete_measurement_config(self, config_id: int) -> None:
        """Delete a measurement config and its entries."""
        # Clear active config if this was the active one
        active_id = self.get_active_measurement_config_id()
        queries.delete_measurement_config(self._conn, config_id)
        if active_id == config_id:
            queries.set_active_measurement_config(self._conn, None)

    def get_active_measurement_config_id(self) -> int | None:
        """Return the active measurement config ID, or None."""
        return queries.select_active_measurement_config_id(self._conn)

    def set_active_measurement_config(self, config_id: int) -> None:
        """Set the active measurement config."""
        queries.set_active_measurement_config(self._conn, config_id)

    # --- Run Name Generation ---

    def _generate_run_name(
        self,
        base_name: str,
        fov_id: int,
        table: str,
        channel_id: int | None = None,
    ) -> str:
        """Generate a unique run name, appending _2, _3, etc. on collision.

        Uses INSERT-catch-IntegrityError pattern atomically.
        """
        # Check if base name already exists
        if table == "segmentation_runs":
            where = "fov_id = ? AND name = ?"
            params: list[object] = [fov_id, base_name]
        else:  # threshold_runs
            where = "fov_id = ? AND channel_id = ? AND name = ?"
            params = [fov_id, channel_id, base_name]

        row = self._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}",
            params,
        ).fetchone()

        if row[0] == 0:
            return base_name

        # Name collision — find next available suffix
        for i in range(2, 1000):
            candidate = f"{base_name}_{i}"
            if table == "segmentation_runs":
                params = [fov_id, candidate]
            else:
                params = [fov_id, channel_id, candidate]
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}",
                params,
            ).fetchone()
            if row[0] == 0:
                return candidate

        raise RunNameError(base_name, "too many runs with this base name")

    # --- Export ---

    def export_csv(
        self,
        path: Path,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        scope: str | None = None,
    ) -> None:
        pivot = self.get_measurement_pivot(
            channels=channels, metrics=metrics, scope=scope,
            include_cell_info=True,
        )
        pivot.to_csv(path, index=False)

    def export_prism_csv(
        self,
        output_dir: Path,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        scope: str = "whole_cell",
    ) -> dict[str, int]:
        """Export measurements in Prism-friendly format.

        Creates a directory tree with one CSV per (channel, metric).
        Each CSV has columns = {condition}_{biorep} and rows = cell values.
        FOVs from the same (condition, bio_rep) are pooled.

        Args:
            output_dir: Root output directory (created if it doesn't exist).
            channels: Optional list of channels to include.
            metrics: Optional list of metrics to include.
            scope: Measurement scope ('whole_cell', 'mask_inside', 'mask_outside').

        Returns:
            Dict with 'files_written' and 'channels_exported' counts.
        """
        import csv as csv_mod

        from percell3.core.constants import (
            PARTICLE_AGGREGATE_METRICS,
            PARTICLE_AREA_METRICS,
            PARTICLE_SUMMARY_METRICS,
        )

        particle_metric_set = set(PARTICLE_SUMMARY_METRICS)
        aggregate_metric_set = set(PARTICLE_AGGREGATE_METRICS)
        area_metric_set = set(PARTICLE_AREA_METRICS)

        # Separate aggregate metric names from per-cell metric names
        want_aggregates = not metrics or bool(aggregate_metric_set & set(metrics))
        per_cell_metrics = (
            [m for m in metrics if m not in aggregate_metric_set]
            if metrics
            else None
        )

        # Get measurements filtered by channels and scope
        df = self.get_measurements(channels=channels, scope=scope)
        if df.empty and not want_aggregates:
            return {"files_written": 0, "channels_exported": 0}

        # Filter by per-cell metrics if specified (empty list = no per-cell metrics)
        if per_cell_metrics is not None:
            df = df[df["metric"].isin(per_cell_metrics)]

        # Get valid cells with condition/bio_rep context
        cells_df = self.get_cells(is_valid=True)
        if cells_df.empty:
            return {"files_written": 0, "channels_exported": 0}

        ctx_cols = ["id", "condition_name", "bio_rep_name", "pixel_size_um"]
        ctx_cols = [c for c in ctx_cols if c in cells_df.columns]
        cell_context = cells_df[ctx_cols].rename(columns={"id": "cell_id"})
        if not df.empty:
            df = df.merge(cell_context, on="cell_id", how="inner")

        # Merge group tags so Prism columns can be split by group
        if not df.empty:
            df, _prism_group_cols = self._merge_group_tags(df)
        else:
            _prism_group_cols = []

        # Scope suffix for filenames (particle metrics never get suffix)
        scope_suffix = "" if scope == "whole_cell" else f"_{scope}"

        files_written = 0
        channels_exported: set[str] = set()

        for (channel, metric), group in df.groupby(["channel", "metric"]):
            # Convert particle area metrics from pixels to um2
            if metric in area_metric_set and "pixel_size_um" in group.columns:
                group = group.copy()
                ps = group["pixel_size_um"]
                group["value"] = group["value"] * ps * ps

            # Build ragged columns grouped by (condition, bio_rep[, group])
            column_data: dict[str, list[float]] = {}
            if _prism_group_cols:
                # Include group in column name for finer-grained Prism columns
                group_by_cols = ["condition_name", "bio_rep_name"] + _prism_group_cols
                for keys, sub in group.groupby(group_by_cols):
                    if isinstance(keys, str):
                        keys = (keys,)
                    parts = [str(k) for k in keys if str(k)]
                    col_name = "_".join(parts)
                    column_data[col_name] = sub["value"].tolist()
            else:
                for (cond, bio_rep), sub in group.groupby(
                    ["condition_name", "bio_rep_name"]
                ):
                    col_name = f"{cond}_{bio_rep}"
                    column_data[col_name] = sub["value"].tolist()

            if not column_data:
                continue

            sorted_cols = sorted(column_data.keys())
            max_rows = max(len(column_data[c]) for c in sorted_cols)

            # Create channel subdirectory
            ch_dir = output_dir / str(channel)
            ch_dir.mkdir(parents=True, exist_ok=True)

            # Particle metrics never get scope suffix
            suffix = "" if metric in particle_metric_set else scope_suffix
            csv_path = ch_dir / f"{metric}{suffix}.csv"

            with open(csv_path, "w", newline="") as f:
                writer = csv_mod.writer(f)
                writer.writerow(sorted_cols)
                for i in range(max_rows):
                    row = []
                    for col in sorted_cols:
                        values = column_data[col]
                        row.append(values[i] if i < len(values) else "")
                    writer.writerow(row)

            files_written += 1
            channels_exported.add(str(channel))

        # --- Aggregate metrics (one value per group, not per cell) ---
        # Compute pct_cells_with_particles from particle_count data.
        if want_aggregates:
            # particle_count may already be in df, or we need to fetch it
            pc_df = df[df["metric"] == "particle_count"] if not df.empty else df
            if pc_df.empty:
                # particle_count was filtered out or df was empty — re-query it
                pc_raw = self.get_measurements(channels=channels, scope="whole_cell")
                pc_raw = pc_raw[pc_raw["metric"] == "particle_count"]
                if not pc_raw.empty:
                    pc_df = pc_raw.merge(cell_context, on="cell_id", how="inner")

            if not pc_df.empty:
                for channel, ch_group in pc_df.groupby("channel"):
                    column_data_agg: dict[str, list[float]] = {}
                    for (cond, bio_rep), sub in ch_group.groupby(
                        ["condition_name", "bio_rep_name"]
                    ):
                        col_name = f"{cond}_{bio_rep}"
                        total = len(sub)
                        with_particles = int((sub["value"] > 0).sum())
                        pct = (with_particles / total * 100) if total > 0 else 0.0
                        column_data_agg[col_name] = [round(pct, 2)]

                    if column_data_agg:
                        sorted_cols = sorted(column_data_agg.keys())
                        ch_dir = output_dir / str(channel)
                        ch_dir.mkdir(parents=True, exist_ok=True)
                        csv_path = ch_dir / "pct_cells_with_particles.csv"
                        with open(csv_path, "w", newline="") as f:
                            writer = csv_mod.writer(f)
                            writer.writerow(sorted_cols)
                            writer.writerow(
                                [column_data_agg[c][0] for c in sorted_cols]
                            )
                        files_written += 1
                        channels_exported.add(str(channel))

        return {
            "files_written": files_written,
            "channels_exported": len(channels_exported),
        }

    # Intensity field names that become per-channel when channels are specified
    _PARTICLE_INTENSITY_FIELDS = {
        "mean_intensity", "max_intensity", "integrated_intensity",
    }

    def export_particles_csv(
        self,
        path: Path,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        threshold_run_id: int | None = None,
    ) -> None:
        """Export per-particle data to CSV with cell context columns.

        Args:
            path: Output CSV file path.
            channels: If provided, compute intensity metrics from each
                channel image.  Original single-channel intensity columns
                are replaced with ``{channel}_mean_intensity`` etc.
            metrics: If provided, include only these particle fields
                (plus context columns which are always included).
                Intensity names (``mean_intensity`` etc.) are expanded
                per channel when *channels* is set.
            threshold_run_id: Optional filter by threshold run.
        """
        rows = queries.select_particles_with_cell_info(
            self._conn, threshold_run_id=threshold_run_id,
        )
        df = pd.DataFrame(rows)
        if df.empty:
            df.to_csv(path, index=False)
            return

        # Always expand intensity columns to per-channel format.
        # The bare "mean_intensity" stored in particles is from the threshold
        # channel only — replacing it with {channel}_mean_intensity for each
        # channel makes the output unambiguous.
        effective_channels = channels if channels else [
            ch.name for ch in self.get_channels()
        ]
        if effective_channels:
            df = self._add_particle_channel_intensities(df, effective_channels)
            df = df.drop(
                columns=list(self._PARTICLE_INTENSITY_FIELDS),
                errors="ignore",
            )

        # Drop internal IDs
        df = df.drop(columns=["id", "threshold_run_id"], errors="ignore")

        # Merge group tags for parent cells
        if "cell_id" in df.columns:
            df, _ = self._merge_group_tags(df)

        # Apply metric filter
        context_cols = [
            "cell_id", "condition_name", "bio_rep_name", "fov_name",
            "cell_label_value", "label_value",
        ]
        if metrics:
            keep = [c for c in context_cols if c in df.columns]
            for m in metrics:
                if m in self._PARTICLE_INTENSITY_FIELDS and effective_channels:
                    for ch in effective_channels:
                        col = f"{ch}_{m}"
                        if col in df.columns:
                            keep.append(col)
                elif m in df.columns:
                    keep.append(m)
            df = df[keep]
        else:
            other = [c for c in df.columns if c not in context_cols]
            df = df[[c for c in context_cols if c in df.columns] + other]

        df.to_csv(path, index=False)

    def _add_particle_channel_intensities(
        self,
        df: pd.DataFrame,
        channels: list[str],
    ) -> pd.DataFrame:
        """Compute per-channel intensity columns for each particle.

        Reconstructs each particle's mask from the stored threshold mask
        and cell labels, then measures intensity from each channel image.
        """
        from scipy.ndimage import label as scipy_label

        # Look up the threshold channel (needed to read the mask)
        threshold_channel = None
        if "threshold_run_id" in df.columns:
            thr_id = df["threshold_run_id"].iloc[0]
            if thr_id is not None:
                for run in self.get_threshold_runs():
                    if run.id == int(thr_id):
                        threshold_channel = run.channel
                        break

        # Initialise result columns to 0
        for ch in channels:
            for suffix in ("mean_intensity", "max_intensity",
                           "integrated_intensity"):
                df[f"{ch}_{suffix}"] = 0.0

        # Process one FOV at a time to avoid reading images repeatedly
        # Group by fov_id which we get from cells
        if "fov_id" not in df.columns:
            # If fov_id is not in the particle query results, we need to add it
            # by joining through cells
            pass

        # Use fov_name grouping to get unique FOV IDs from the cell context
        fov_groups = df.groupby("fov_name")

        for fov_name, gdf in fov_groups:
            # Look up fov_id from display_name
            try:
                fov_info = queries.select_fov_by_display_name(self._conn, str(fov_name))
                fov_id = fov_info.id
            except Exception:
                continue

            # Resolve per-FOV segmentation run to read labels
            seg_runs = self.list_segmentation_runs(fov_id)
            if not seg_runs:
                continue
            seg_run_id = seg_runs[0].id

            try:
                labels = self.read_labels(fov_id, seg_run_id)
            except Exception:
                continue

            # Read threshold mask for particle disambiguation
            threshold_mask = None
            if threshold_channel:
                try:
                    # Resolve threshold run for this FOV + channel
                    fov_thr_runs = [
                        tr for tr in self.get_threshold_runs()
                        if tr.channel == threshold_channel and tr.fov_id == fov_id
                    ]
                    if fov_thr_runs:
                        thr_run_id = fov_thr_runs[-1].id
                        raw = self.read_mask(fov_id, threshold_channel, thr_run_id)
                        threshold_mask = raw > 0
                except Exception:
                    pass

            # Read each requested channel image
            ch_images: dict[str, np.ndarray] = {}
            for ch in channels:
                try:
                    ch_images[ch] = self.read_image_numpy(fov_id, ch)
                except Exception:
                    pass
            if not ch_images:
                continue

            for idx in gdf.index:
                row = df.loc[idx]
                cell_label = int(row["cell_label_value"])
                bx, by = int(row["bbox_x"]), int(row["bbox_y"])
                bw, bh = int(row["bbox_w"]), int(row["bbox_h"])
                if bw <= 0 or bh <= 0:
                    continue

                # Reconstruct particle mask inside its bbox
                label_crop = labels[by:by + bh, bx:bx + bw]
                cell_mask = label_crop == cell_label

                if threshold_mask is not None:
                    mask_crop = threshold_mask[by:by + bh, bx:bx + bw]
                    particle_mask = cell_mask & mask_crop

                    # Disambiguate overlapping particles via centroid
                    cc_labels, n_cc = scipy_label(particle_mask)
                    if n_cc > 1:
                        cx = float(row["centroid_x"]) - bx
                        cy = float(row["centroid_y"]) - by
                        ci = min(max(int(round(cx)), 0), bw - 1)
                        cj = min(max(int(round(cy)), 0), bh - 1)
                        target = cc_labels[cj, ci]
                        if target > 0:
                            particle_mask = cc_labels == target
                else:
                    particle_mask = cell_mask

                if not np.any(particle_mask):
                    continue

                for ch, ch_img in ch_images.items():
                    pixels = ch_img[by:by + bh, bx:bx + bw][particle_mask]
                    if len(pixels) > 0:
                        df.at[idx, f"{ch}_mean_intensity"] = float(
                            np.mean(pixels)
                        )
                        df.at[idx, f"{ch}_max_intensity"] = float(
                            np.max(pixels)
                        )
                        df.at[idx, f"{ch}_integrated_intensity"] = float(
                            np.sum(pixels)
                        )

        return df
