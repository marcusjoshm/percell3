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
    DuplicateError,
    ExperimentError,
    ExperimentNotFoundError,
    RunNameError,
    SegmentationNotFoundError,
    ThresholdNotFoundError,
)
from percell3.core.models import (
    AnalysisConfig,
    CellRecord,
    ChannelConfig,
    DeleteImpact,
    FovConfigEntry,
    FovInfo,
    MeasurementRecord,
    ParticleRecord,
    SegmentationInfo,
    ThresholdInfo,
)
from percell3.core.schema import create_schema, open_database


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

        When width and height are provided, automatically creates a whole-field
        segmentation (or reuses an existing one with matching dimensions) and
        a fov_config entry pointing to it.

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
        fov_id = queries.insert_fov(
            self._conn, display_name=display_name,
            condition_id=cond_id, bio_rep_id=bio_rep_id,
            timepoint_id=tp_id, width=width, height=height,
            pixel_size_um=pixel_size_um, source_file=source_file,
        )

        # Auto-create whole-field segmentation and config entry
        if width is not None and height is not None:
            seg_id = self._get_or_create_whole_field_segmentation(
                fov_id, width, height,
            )
            self.set_fov_config_entry(fov_id, seg_id)

        return fov_id

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

    def delete_fov(self, fov_id: int) -> None:
        """Delete a FOV and all its FOV-specific data.

        SQLite CASCADE handles: cells, measurements, particles,
        fov_config entries, fov_status_cache, fov_tags.

        Segmentations and thresholds are global entities and are NOT deleted.
        Only the FOV's image zarr group is cleaned up.

        Args:
            fov_id: Database ID of the FOV to delete.

        Raises:
            ExperimentError: If the FOV does not exist.
        """
        # Validate FOV exists
        self.get_fov_by_id(fov_id)  # raises ExperimentError if not found

        # 1. SQLite CASCADE delete (removes all dependent rows)
        queries.delete_fov_row(self._conn, fov_id)

        # 2. Remove image zarr group only (labels/masks are global, keyed by seg/thresh ID)
        fov_group = zarr_io.fov_group_path(fov_id)
        zarr_io.delete_zarr_group(self.images_zarr_path, fov_group)

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

    def rename_bio_rep(self, old_name: str, new_name: str) -> None:
        """Rename a biological replicate. DB-only."""
        _validate_name(new_name, "bio_rep name")
        queries.rename_bio_rep(self._conn, old_name, new_name)

    def rename_fov(self, fov_id: int, new_display_name: str) -> None:
        """Rename a FOV by ID. DB-only — zarr paths use fov_id."""
        _validate_name(new_display_name, "fov display_name")
        queries.rename_fov(self._conn, fov_id, new_display_name)

    def rename_segmentation(self, segmentation_id: int, new_name: str) -> None:
        """Rename a segmentation entity."""
        _validate_name(new_name, "segmentation name")
        queries.rename_segmentation(self._conn, segmentation_id, new_name)

    def rename_threshold(self, threshold_id: int, new_name: str) -> None:
        """Rename a threshold entity."""
        _validate_name(new_name, "threshold name")
        queries.rename_threshold(self._conn, threshold_id, new_name)

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

    # --- Auto-naming helpers ---

    def _generate_segmentation_name(
        self,
        model_name: str = "",
        channel: str = "",
    ) -> str:
        """Generate a unique segmentation name like 'cyto3_DAPI_1'."""
        existing = {s.name for s in self.get_segmentations()}
        base = "_".join(filter(None, [model_name, channel])) or "seg"
        n = 1
        while True:
            candidate = f"{base}_{n}"
            if candidate not in existing:
                return candidate
            n += 1

    def _generate_threshold_name(
        self,
        grouping_channel: str = "",
        threshold_channel: str = "",
        *,
        base_name: str = "",
    ) -> str:
        """Generate a unique threshold name.

        If *base_name* is provided, use it directly (with a uniqueness
        counter appended on collision).  Otherwise fall back to the
        auto-generated pattern ``thresh_{grouping}_{channel}_{N}``.
        """
        existing = {t.name for t in self.get_thresholds()}
        if base_name:
            if base_name not in existing:
                return base_name
            n = 2
            while True:
                candidate = f"{base_name}_{n}"
                if candidate not in existing:
                    return candidate
                n += 1
        # Auto-generated name (original behaviour)
        gc = grouping_channel.replace(":", "_") if grouping_channel else ""
        tc = threshold_channel.replace(":", "_") if threshold_channel else ""
        parts = list(filter(None, ["thresh", gc, tc]))
        base = "_".join(parts)
        n = 1
        while True:
            candidate = f"{base}_{n}"
            if candidate not in existing:
                return candidate
            n += 1

    # --- Whole-field segmentation ---

    def _get_or_create_whole_field_segmentation(
        self,
        fov_id: int,
        width: int,
        height: int,
    ) -> int:
        """Get or create a whole-field segmentation with matching dimensions.

        Reuses existing whole_field segmentations with the same dimensions.
        Creates an all-1 label image if a new segmentation is needed.

        Returns:
            The segmentation ID.
        """
        existing = self.get_segmentations(
            seg_type="whole_field", width=width, height=height,
        )
        if existing:
            return existing[0].id

        name = self._generate_segmentation_name("whole_field")
        seg_id = self.add_segmentation(
            name, "whole_field", width, height, source_fov_id=fov_id,
        )

        # Write all-1 label image (every pixel belongs to cell 1)
        labels = np.ones((height, width), dtype=np.int32)
        self.write_labels(labels, seg_id)

        return seg_id

    def create_whole_field_segmentation(
        self,
        fov_id: int,
        width: int,
        height: int,
    ) -> int:
        """Create a whole-field segmentation with every-pixel-is-1 labels.

        Public API for creating whole-field segmentations. Unlike the
        private helper, this always creates a new segmentation (no reuse).

        Args:
            fov_id: Source FOV ID for provenance.
            width: Image width in pixels.
            height: Image height in pixels.

        Returns:
            The segmentation ID.
        """
        name = self._generate_segmentation_name("whole_field")
        seg_id = self.add_segmentation(
            name, "whole_field", width, height, source_fov_id=fov_id,
        )
        labels = np.ones((height, width), dtype=np.int32)
        self.write_labels(labels, seg_id)
        return seg_id

    # --- Auto-config helpers ---

    def _auto_config_segmentation(self, fov_id: int, seg_id: int) -> None:
        """Update fov_config to use a new cellular segmentation for a FOV.

        Replaces the segmentation in all existing config entries for the FOV,
        preserving any threshold associations.
        """
        existing = self.get_fov_config(fov_id)
        if not existing:
            # No config yet — create a bare entry with just the segmentation
            self.set_fov_config_entry(fov_id, seg_id)
            return

        # Replace segmentation in each existing entry
        for entry in existing:
            self.delete_fov_config_entry(entry.id)
            self.set_fov_config_entry(
                fov_id, seg_id,
                threshold_id=entry.threshold_id,
                scopes=entry.scopes,
            )

    def _auto_config_threshold(self, fov_id: int, thr_id: int) -> None:
        """Add a threshold to fov_config for a FOV.

        Uses the first segmentation from the FOV's existing config.
        If no config exists, does nothing (threshold can be configured manually).
        """
        existing = self.get_fov_config(fov_id)
        if not existing:
            return

        # Use the segmentation from the first existing config entry
        seg_id = existing[0].segmentation_id
        self.set_fov_config_entry(
            fov_id, seg_id,
            threshold_id=thr_id,
            scopes=["whole_cell", "mask_inside", "mask_outside"],
        )

    # --- Label Images (keyed by segmentation_id) ---

    def write_labels(self, labels: np.ndarray, segmentation_id: int) -> None:
        """Write a label image to labels.zarr.

        Labels are stored at ``labels.zarr/seg_{segmentation_id}/0``.
        """
        gp = zarr_io.label_group_path(segmentation_id)
        zarr_io.write_labels(self.labels_zarr_path, gp, labels)

    def read_labels(self, segmentation_id: int) -> np.ndarray:
        """Read a label image from labels.zarr."""
        gp = zarr_io.label_group_path(segmentation_id)
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
        fov_ids: list[int] | None = None,
    ) -> pd.DataFrame:
        from percell3.core.constants import PARTICLE_AREA_METRICS

        # Resolve fov_ids to cell_ids for query filtering
        cell_ids = None
        if fov_ids is not None:
            cells_df = self.get_cells(is_valid=False)
            if not cells_df.empty and "fov_id" in cells_df.columns:
                cell_ids = cells_df[
                    cells_df["fov_id"].isin(fov_ids)
                ]["id"].tolist()
            else:
                cell_ids = []

        df = self.get_measurements(
            cell_ids=cell_ids, channels=channels, metrics=metrics, scope=scope,
        )
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

        # When multiple thresholds exist, pivot by (cell_id, threshold_name)
        # so each threshold gets its own row instead of being collapsed.
        has_threshold_data = df["threshold_id"].notna().any()
        if has_threshold_data:
            thr_map = {t.id: t.name for t in self.get_thresholds()}
            df["threshold_name"] = df["threshold_id"].map(thr_map).fillna("")

            # Split: base (no threshold) vs threshold-specific
            df_base = df[df["threshold_name"] == ""]
            df_thr = df[df["threshold_name"] != ""]

            # Pivot threshold-specific by (cell_id, threshold_name)
            pivot_thr = df_thr.pivot_table(
                index=["cell_id", "threshold_name"],
                columns="col", values="value", aggfunc="first",
            ).reset_index()

            if not df_base.empty:
                # Pivot base by cell_id only
                pivot_base = df_base.pivot_table(
                    index="cell_id", columns="col",
                    values="value", aggfunc="first",
                ).reset_index()
                # Merge base columns into each threshold row
                pivot = pivot_thr.merge(pivot_base, on="cell_id", how="left")
            else:
                pivot = pivot_thr
        else:
            pivot = df.pivot_table(
                index="cell_id", columns="col",
                values="value", aggfunc="first",
            ).reset_index()
            pivot["threshold_name"] = ""

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

    # --- Masks (keyed by threshold_id) ---

    def write_mask(self, mask: np.ndarray, threshold_id: int) -> None:
        """Write a binary mask to masks.zarr.

        Masks are stored at ``masks.zarr/thresh_{threshold_id}/mask/0``.
        """
        gp = zarr_io.mask_group_path(threshold_id)
        zarr_io.write_mask(self.masks_zarr_path, gp, mask)

    def read_mask(self, threshold_id: int) -> np.ndarray:
        """Read a binary mask from masks.zarr."""
        gp = zarr_io.mask_group_path(threshold_id)
        return zarr_io.read_mask(self.masks_zarr_path, gp)

    # --- Segmentations (global entities) ---

    def add_segmentation(
        self,
        name: str,
        seg_type: str,
        width: int,
        height: int,
        source_fov_id: int | None = None,
        source_channel: str | None = None,
        model_name: str = "",
        parameters: dict[str, object] | None = None,
    ) -> int:
        """Create a global segmentation entity.

        Args:
            name: Unique segmentation name.
            seg_type: 'whole_field' or 'cellular'.
            width: Image width in pixels.
            height: Image height in pixels.
            source_fov_id: FOV where segmentation was computed (provenance).
            source_channel: Channel used for segmentation (provenance).
            model_name: Model name (e.g. "cyto3").
            parameters: Optional dict of segmentation parameters.

        Returns:
            The segmentation ID.
        """
        _validate_name(name, "segmentation name")
        try:
            seg_id = queries.insert_segmentation(
                self._conn, name, seg_type, width, height,
                source_fov_id=source_fov_id, source_channel=source_channel,
                model_name=model_name, parameters=parameters,
            )
        except DuplicateError:
            raise
        except sqlite3.IntegrityError:
            raise RunNameError(name, f"a segmentation named {name!r} already exists")

        # Auto-config: update source FOV's config to use this segmentation
        if source_fov_id is not None and seg_type == "cellular":
            self._auto_config_segmentation(source_fov_id, seg_id)

        return seg_id

    def get_segmentations(
        self,
        seg_type: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> list[SegmentationInfo]:
        """Return all segmentations, optionally filtered."""
        return queries.select_segmentations(
            self._conn, seg_type=seg_type, width=width, height=height,
        )

    def get_segmentation(self, segmentation_id: int) -> SegmentationInfo:
        """Get a single segmentation by ID."""
        return queries.select_segmentation(self._conn, segmentation_id)

    def update_segmentation_cell_count(
        self, segmentation_id: int, cell_count: int,
    ) -> None:
        """Update the cell count for a segmentation."""
        queries.update_segmentation_cell_count(
            self._conn, segmentation_id, cell_count,
        )

    def get_segmentation_impact(self, segmentation_id: int) -> DeleteImpact:
        """Preview what would be deleted if this segmentation were removed.

        Returns:
            DeleteImpact with counts of cells, measurements, and
            config entries that would be cascade-deleted.
        """
        cells = self._conn.execute(
            "SELECT COUNT(*) FROM cells WHERE segmentation_id = ?",
            (segmentation_id,),
        ).fetchone()[0]

        measurements = self._conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE segmentation_id = ?",
            (segmentation_id,),
        ).fetchone()[0]

        config_entries = self._conn.execute(
            "SELECT COUNT(*) FROM fov_config WHERE segmentation_id = ?",
            (segmentation_id,),
        ).fetchone()[0]

        fov_rows = self._conn.execute(
            "SELECT DISTINCT f.display_name FROM fov_config fc "
            "JOIN fovs f ON fc.fov_id = f.id "
            "WHERE fc.segmentation_id = ?",
            (segmentation_id,),
        ).fetchall()
        affected_fovs = [r[0] for r in fov_rows]

        return DeleteImpact(
            cells=cells,
            measurements=measurements,
            config_entries=config_entries,
            affected_fovs=affected_fovs,
        )

    def delete_segmentation(self, segmentation_id: int) -> None:
        """Delete a segmentation, its cells, measurements, config entries, and Zarr data."""
        # Validate it exists
        self.get_segmentation(segmentation_id)

        # Determine affected FOVs for cache update
        fov_rows = self._conn.execute(
            "SELECT DISTINCT fov_id FROM fov_config WHERE segmentation_id = ?",
            (segmentation_id,),
        ).fetchall()
        affected_fov_ids = [r[0] for r in fov_rows]

        # CASCADE handles cells, measurements, fov_config entries in SQLite
        queries.delete_segmentation(self._conn, segmentation_id)

        # Clean up Zarr data
        gp = zarr_io.label_group_path(segmentation_id)
        zarr_io.delete_zarr_group(self.labels_zarr_path, gp)

        # Refresh status cache for affected FOVs
        if affected_fov_ids:
            self.update_fov_status_cache_batch(affected_fov_ids)

    # --- Thresholds (global entities) ---

    def add_threshold(
        self,
        name: str,
        method: str,
        width: int,
        height: int,
        source_fov_id: int | None = None,
        source_channel: str | None = None,
        grouping_channel: str | None = None,
        parameters: dict[str, object] | None = None,
    ) -> int:
        """Create a global threshold entity.

        Args:
            name: Unique threshold name.
            method: Thresholding method name (e.g. "otsu").
            width: Image width in pixels.
            height: Image height in pixels.
            source_fov_id: FOV where threshold was computed (provenance).
            source_channel: Channel used for thresholding (provenance).
            grouping_channel: Channel used for grouping (provenance).
            parameters: Optional dict of threshold parameters.

        Returns:
            The threshold ID.
        """
        _validate_name(name, "threshold name")
        try:
            thr_id = queries.insert_threshold(
                self._conn, name, method, width, height,
                source_fov_id=source_fov_id, source_channel=source_channel,
                grouping_channel=grouping_channel, parameters=parameters,
            )
        except DuplicateError:
            raise
        except sqlite3.IntegrityError:
            raise RunNameError(name, f"a threshold named {name!r} already exists")

        # Auto-config: add threshold to source FOV's config
        if source_fov_id is not None:
            self._auto_config_threshold(source_fov_id, thr_id)

        return thr_id

    def get_thresholds(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> list[ThresholdInfo]:
        """Return all thresholds, optionally filtered by dimensions."""
        return queries.select_thresholds(
            self._conn, width=width, height=height,
        )

    def get_threshold(self, threshold_id: int) -> ThresholdInfo:
        """Get a single threshold by ID."""
        return queries.select_threshold(self._conn, threshold_id)

    def update_threshold_value(self, threshold_id: int, threshold_value: float) -> None:
        """Update the computed threshold value."""
        queries.update_threshold_value(self._conn, threshold_id, threshold_value)

    def get_threshold_impact(self, threshold_id: int) -> DeleteImpact:
        """Preview what would be deleted if this threshold were removed.

        Returns:
            DeleteImpact with counts of measurements, particles, and
            config entries that would be cascade-deleted.
        """
        particles = self._conn.execute(
            "SELECT COUNT(*) FROM particles WHERE threshold_id = ?",
            (threshold_id,),
        ).fetchone()[0]

        measurements = self._conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE threshold_id = ?",
            (threshold_id,),
        ).fetchone()[0]

        config_entries = self._conn.execute(
            "SELECT COUNT(*) FROM fov_config WHERE threshold_id = ?",
            (threshold_id,),
        ).fetchone()[0]

        fov_rows = self._conn.execute(
            "SELECT DISTINCT f.display_name FROM fov_config fc "
            "JOIN fovs f ON fc.fov_id = f.id "
            "WHERE fc.threshold_id = ?",
            (threshold_id,),
        ).fetchall()
        affected_fovs = [r[0] for r in fov_rows]

        return DeleteImpact(
            measurements=measurements,
            particles=particles,
            config_entries=config_entries,
            affected_fovs=affected_fovs,
        )

    def delete_threshold(self, threshold_id: int) -> None:
        """Delete a threshold, its particles, measurements, config entries, and Zarr data."""
        # Validate it exists
        self.get_threshold(threshold_id)

        # Determine affected FOVs for cache update
        fov_rows = self._conn.execute(
            "SELECT DISTINCT fov_id FROM fov_config WHERE threshold_id = ?",
            (threshold_id,),
        ).fetchall()
        affected_fov_ids = [r[0] for r in fov_rows]

        # Explicitly delete fov_config entries referencing this threshold
        # before cascade delete. The CASCADE uses ON DELETE SET NULL which
        # can create UNIQUE constraint violations when a (config, fov, seg, NULL)
        # row already exists.
        self._conn.execute(
            "DELETE FROM fov_config WHERE threshold_id = ?",
            (threshold_id,),
        )

        # CASCADE handles particles and measurements in SQLite
        queries.delete_threshold(self._conn, threshold_id)

        # Clean up Zarr data (thresh_{id}/ contains both mask/ and particles/)
        thresh_group = f"thresh_{threshold_id}"
        zarr_io.delete_zarr_group(self.masks_zarr_path, thresh_group)

        # Refresh status cache for affected FOVs
        if affected_fov_ids:
            self.update_fov_status_cache_batch(affected_fov_ids)

    # --- Analysis Config + FOV Config ---

    def get_or_create_analysis_config(self) -> AnalysisConfig:
        """Get the experiment's analysis config, creating one if needed."""
        return queries.get_or_create_analysis_config(self._conn)

    def get_fov_config(self, fov_id: int) -> list[FovConfigEntry]:
        """Return all config entries for a FOV."""
        config = self.get_or_create_analysis_config()
        return queries.select_fov_config(self._conn, config.id, fov_id=fov_id)

    def set_fov_config_entry(
        self,
        fov_id: int,
        segmentation_id: int,
        threshold_id: int | None = None,
        scopes: list[str] | None = None,
    ) -> int:
        """Add a config entry linking a FOV to a segmentation (and optional threshold).

        Validates that the segmentation dimensions match the FOV dimensions.

        Args:
            fov_id: FOV to configure.
            segmentation_id: Segmentation to assign.
            threshold_id: Optional threshold to assign.
            scopes: Measurement scopes (default: ["whole_cell"]).

        Returns:
            The config entry ID.

        Raises:
            ValueError: If segmentation/threshold dimensions don't match the FOV.
        """
        fov = self.get_fov_by_id(fov_id)
        seg = self.get_segmentation(segmentation_id)

        # Dimension validation
        if fov.width is not None and fov.height is not None:
            if seg.width != fov.width or seg.height != fov.height:
                raise ValueError(
                    f"Segmentation dimensions ({seg.width}x{seg.height}) "
                    f"don't match FOV dimensions ({fov.width}x{fov.height})"
                )

        if threshold_id is not None:
            thr = self.get_threshold(threshold_id)
            if fov.width is not None and fov.height is not None:
                if thr.width != fov.width or thr.height != fov.height:
                    raise ValueError(
                        f"Threshold dimensions ({thr.width}x{thr.height}) "
                        f"don't match FOV dimensions ({fov.width}x{fov.height})"
                    )

        config = self.get_or_create_analysis_config()
        entry_id = queries.insert_fov_config_entry(
            self._conn, config.id, fov_id, segmentation_id,
            threshold_id=threshold_id, scopes=scopes,
        )
        self.update_fov_status_cache(fov_id)
        return entry_id

    def get_config_matrix(self) -> list[FovConfigEntry]:
        """Return the full config matrix for all FOVs."""
        config = self.get_or_create_analysis_config()
        return queries.select_fov_config(self._conn, config.id)

    def delete_fov_config_entry(self, entry_id: int) -> None:
        """Delete a single fov_config entry."""
        queries.delete_fov_config_entry(self._conn, entry_id)

    def delete_fov_config_for_fov(self, fov_id: int) -> None:
        """Delete all config entries for a FOV."""
        config = self.get_or_create_analysis_config()
        queries.delete_fov_config_for_fov(self._conn, config.id, fov_id)
        self.update_fov_status_cache(fov_id)

    def unassign_threshold_from_fov(
        self,
        threshold_id: int,
        fov_id: int,
    ) -> dict[str, int]:
        """Unassign a threshold from a FOV, cleaning up associated data.

        Removes fov_config entries linking this threshold to the FOV,
        and deletes associated particle measurements and particles.

        Args:
            threshold_id: Threshold to unassign.
            fov_id: FOV to unassign from.

        Returns:
            Dict with counts: measurements_deleted, particles_deleted,
            config_entries_deleted.
        """
        config = self.get_or_create_analysis_config()
        entries = queries.select_fov_config(self._conn, config.id, fov_id=fov_id)
        matching = [e for e in entries if e.threshold_id == threshold_id]
        if not matching:
            return {"measurements_deleted": 0, "particles_deleted": 0,
                    "config_entries_deleted": 0}

        meas_count = queries.delete_measurements_for_fov_threshold(
            self._conn, fov_id, threshold_id,
        )
        part_count = queries.delete_particles_for_fov_threshold(
            self._conn, fov_id, threshold_id,
        )
        for entry in matching:
            queries.delete_fov_config_entry(self._conn, entry.id)

        self.update_fov_status_cache(fov_id)
        return {
            "measurements_deleted": meas_count,
            "particles_deleted": part_count,
            "config_entries_deleted": len(matching),
        }

    def unassign_segmentation_from_fov(
        self,
        segmentation_id: int,
        fov_id: int,
    ) -> dict[str, int]:
        """Unassign a segmentation from a FOV, cleaning up associated data.

        Removes fov_config entries, cells, measurements, and particles
        linked to this segmentation on the given FOV.

        Args:
            segmentation_id: Segmentation to unassign.
            fov_id: FOV to unassign from.

        Raises:
            ValueError: If the segmentation is a whole_field type.

        Returns:
            Dict with counts: cells_deleted, measurements_deleted,
            particles_deleted, config_entries_deleted.
        """
        seg = self.get_segmentation(segmentation_id)
        if seg.seg_type == "whole_field":
            raise ValueError(
                "Cannot unassign a whole_field segmentation. "
                "Whole_field segmentations are auto-managed per FOV."
            )

        config = self.get_or_create_analysis_config()
        entries = queries.select_fov_config(self._conn, config.id, fov_id=fov_id)
        matching = [e for e in entries if e.segmentation_id == segmentation_id]
        if not matching:
            return {"cells_deleted": 0, "measurements_deleted": 0,
                    "particles_deleted": 0, "config_entries_deleted": 0}

        # Delete particles for any thresholds in the matching config entries
        part_count = 0
        for entry in matching:
            if entry.threshold_id is not None:
                part_count += queries.delete_particles_for_fov_threshold(
                    self._conn, fov_id, entry.threshold_id,
                )

        # Delete measurements and cells for this FOV+segmentation
        meas_count = queries.delete_measurements_for_fov_segmentation(
            self._conn, fov_id, segmentation_id,
        )
        cell_count = queries.delete_cells_for_fov_segmentation(
            self._conn, fov_id, segmentation_id,
        )

        # Delete the config entries
        for entry in matching:
            queries.delete_fov_config_entry(self._conn, entry.id)

        self.update_fov_status_cache(fov_id)
        return {
            "cells_deleted": cell_count,
            "measurements_deleted": meas_count,
            "particles_deleted": part_count,
            "config_entries_deleted": len(matching),
        }

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

    def get_analysis_runs(self) -> list[dict]:
        """Return all analysis runs."""
        return queries.select_analysis_runs(self._conn)

    def get_experiment_summary(self) -> list[dict]:
        """Per-FOV summary of cells, measurements, thresholds, and particles."""
        return queries.select_experiment_summary(self._conn)

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

    # --- Particles (keyed by fov_id + threshold_id) ---

    def add_particles(self, particles: list[ParticleRecord]) -> None:
        """Bulk insert particle records."""
        queries.insert_particles(self._conn, particles)
        # Update status cache for affected FOVs
        fov_ids = {p.fov_id for p in particles}
        for fov_id in fov_ids:
            self.update_fov_status_cache(fov_id)

    def get_particles(
        self,
        fov_id: int | None = None,
        threshold_id: int | None = None,
    ) -> pd.DataFrame:
        """Query particles with optional filters."""
        rows = queries.select_particles(
            self._conn, fov_id=fov_id, threshold_id=threshold_id,
        )
        return pd.DataFrame(rows)

    def delete_particles_for_fov(self, fov_id: int) -> int:
        """Delete all particles for a FOV.

        Returns:
            Number of particles deleted.
        """
        count = queries.delete_particles_for_fov(self._conn, fov_id)
        self.update_fov_status_cache(fov_id)
        return count

    def delete_particles_for_threshold(self, threshold_id: int) -> int:
        """Delete all particles for a specific threshold."""
        return queries.delete_particles_for_threshold(
            self._conn, threshold_id,
        )

    def delete_particles_for_fov_threshold(
        self, fov_id: int, threshold_id: int,
    ) -> int:
        """Delete particles for a specific FOV + threshold combination."""
        count = queries.delete_particles_for_fov_threshold(
            self._conn, fov_id, threshold_id,
        )
        if count:
            self.update_fov_status_cache(fov_id)
        return count

    # --- Particle Label I/O (keyed by threshold_id) ---

    def write_particle_labels(
        self, labels: np.ndarray, threshold_id: int,
    ) -> None:
        """Write a particle label image to masks.zarr.

        Labels are stored at ``masks.zarr/thresh_{threshold_id}/particles/0``.
        """
        gp = zarr_io.particle_label_group_path(threshold_id)
        zarr_io.write_particle_labels(self.masks_zarr_path, gp, labels)

    def read_particle_labels(self, threshold_id: int) -> np.ndarray:
        """Read a particle label image from masks.zarr."""
        gp = zarr_io.particle_label_group_path(threshold_id)
        return zarr_io.read_particle_labels(self.masks_zarr_path, gp)

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

    # --- Export ---

    def _get_config_provenance(self) -> list[str]:
        """Build config provenance lines for CSV headers."""
        lines = []
        config = self.get_or_create_analysis_config()
        lines.append(f"# analysis_config_id: {config.id}")

        matrix = self.get_config_matrix()
        if not matrix:
            lines.append("# config_matrix: (empty)")
            return lines

        # Group by FOV
        fov_entries: dict[int, list[FovConfigEntry]] = {}
        for entry in matrix:
            fov_entries.setdefault(entry.fov_id, []).append(entry)

        for fov_id, entries in fov_entries.items():
            try:
                fov = self.get_fov_by_id(fov_id)
                fov_name = fov.display_name
            except Exception:
                fov_name = f"fov_{fov_id}"

            seg_names = set()
            thr_names = set()
            scopes = set()
            for e in entries:
                try:
                    seg = self.get_segmentation(e.segmentation_id)
                    seg_names.add(seg.name)
                except Exception:
                    seg_names.add(f"seg_{e.segmentation_id}")
                if e.threshold_id is not None:
                    try:
                        thr = self.get_threshold(e.threshold_id)
                        thr_names.add(thr.name)
                    except Exception:
                        thr_names.add(f"thr_{e.threshold_id}")
                scopes.update(e.scopes)

            parts = [f"# {fov_name}: seg={','.join(sorted(seg_names))}"]
            if thr_names:
                parts.append(f"thr={','.join(sorted(thr_names))}")
            if scopes:
                parts.append(f"scopes={','.join(sorted(scopes))}")
            lines.append(" ".join(parts))

        return lines

    def export_csv(
        self,
        path: Path,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        scope: str | None = None,
        include_provenance: bool = True,
        fov_ids: list[int] | None = None,
    ) -> None:
        """Export measurements to a single flat CSV.

        Args:
            path: Output CSV file path.
            channels: Optional channel filter.
            metrics: Optional metric filter.
            scope: Optional scope filter.
            include_provenance: If True, prepend config provenance as comments.
            fov_ids: Optional FOV filter. None = all FOVs.
        """
        pivot = self.get_measurement_pivot(
            channels=channels, metrics=metrics, scope=scope,
            include_cell_info=True, fov_ids=fov_ids,
        )
        if include_provenance:
            provenance = self._get_config_provenance()
            with open(path, "w") as f:
                for line in provenance:
                    f.write(line + "\n")
                pivot.to_csv(f, index=False)
        else:
            pivot.to_csv(path, index=False)

    def export_prism_csv(
        self,
        output_dir: Path,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        scope: str = "whole_cell",
        fov_ids: list[int] | None = None,
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
            fov_ids: Optional FOV filter. None = all FOVs.

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

        # Resolve fov_ids to cell_ids for query filtering
        cell_ids = None
        if fov_ids is not None:
            all_cells = self.get_cells(is_valid=False)
            if not all_cells.empty and "fov_id" in all_cells.columns:
                cell_ids = all_cells[
                    all_cells["fov_id"].isin(fov_ids)
                ]["id"].tolist()
            else:
                cell_ids = []

        # Get measurements filtered by channels and scope
        df = self.get_measurements(
            cell_ids=cell_ids, channels=channels, scope=scope,
        )
        if df.empty and not want_aggregates:
            return {"files_written": 0, "channels_exported": 0}

        # Filter by per-cell metrics if specified (empty list = no per-cell metrics)
        if per_cell_metrics is not None:
            df = df[df["metric"].isin(per_cell_metrics)]

        # Get valid cells with condition/bio_rep context
        cells_df = self.get_cells(is_valid=True)
        if fov_ids is not None and not cells_df.empty and "fov_id" in cells_df.columns:
            cells_df = cells_df[cells_df["fov_id"].isin(fov_ids)]
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
        if want_aggregates:
            pc_df = df[df["metric"] == "particle_count"] if not df.empty else df
            if pc_df.empty:
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

    def export_particles_csv(
        self,
        path: Path,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        include_provenance: bool = True,
        fov_ids: list[int] | None = None,
    ) -> None:
        """Export particle data to CSV.

        Particles are FOV-level entities linked to thresholds. Each row
        represents one particle with its morphology metrics and FOV context.

        When *channels* is provided, intensity metrics (mean_intensity,
        max_intensity, integrated_intensity) are computed per channel and
        appear as ``{metric}_{channel}`` columns (e.g. ``mean_intensity_Halo``).

        Args:
            path: Output CSV file path.
            channels: Channel names for per-channel intensity columns.
                If None, uses the single intensity values stored in the
                particles table (from the threshold's source channel).
            metrics: Optional metric filter — names like ``"mean_intensity"``,
                ``"area_um2"``, etc.  Geometry metrics are kept as-is;
                intensity metrics are matched by base name before the
                channel suffix.
            include_provenance: If True, prepend config provenance as comments.
            fov_ids: Optional FOV filter. None = all FOVs.
        """
        rows = queries.select_particles_with_context(self._conn)
        df = pd.DataFrame(rows)
        if fov_ids is not None and not df.empty and "fov_id" in df.columns:
            df = df[df["fov_id"].isin(fov_ids)]
        if df.empty:
            if include_provenance:
                provenance = self._get_config_provenance()
                with open(path, "w") as f:
                    for line in provenance:
                        f.write(line + "\n")
            else:
                pd.DataFrame().to_csv(path, index=False)
            return

        # Add threshold name for provenance
        thr_names: dict[int, str] = {}
        for thr_id in df["threshold_id"].unique():
            try:
                thr = self.get_threshold(int(thr_id))
                thr_names[thr_id] = thr.name
            except Exception:
                thr_names[thr_id] = f"thr_{thr_id}"
        df["threshold_name"] = df["threshold_id"].map(thr_names)

        # --- Per-channel intensity computation ---
        intensity_base_metrics = ["mean_intensity", "max_intensity", "integrated_intensity"]
        intensity_cols: list[str] = []

        if channels:
            # Build map of threshold_id -> source_channel so we can reuse
            # the intensity values already stored in the particles table
            # instead of re-computing them with regionprops.
            thr_source_ch: dict[int, str | None] = {}
            for thr_id in df["threshold_id"].unique():
                try:
                    thr_source_ch[int(thr_id)] = self.get_threshold(int(thr_id)).source_channel
                except Exception:
                    thr_source_ch[int(thr_id)] = None

            # Initialise new columns with NaN
            for base in intensity_base_metrics:
                for ch_name in channels:
                    col = f"{base}_{ch_name}"
                    intensity_cols.append(col)
                    df[col] = np.nan

            # Fill source-channel columns from stored particle values
            for thr_id_val, src_ch in thr_source_ch.items():
                if src_ch is None or src_ch not in channels:
                    continue
                mask = df["threshold_id"] == thr_id_val
                for base in intensity_base_metrics:
                    if base in df.columns:
                        df.loc[mask, f"{base}_{src_ch}"] = df.loc[mask, base]

            # Determine which channels still need regionprops computation
            non_source_channels: dict[int, list[str]] = {}
            for thr_id_val, src_ch in thr_source_ch.items():
                remaining = [ch for ch in channels if ch != src_ch]
                if remaining:
                    non_source_channels[thr_id_val] = remaining

            if non_source_channels:
                from skimage.measure import regionprops

                plabel_cache: dict[int, np.ndarray] = {}
                img_cache: dict[tuple[int, str], np.ndarray] = {}

                for (fov_id, thr_id), grp in df.groupby(["fov_id", "threshold_id"]):
                    fov_id = int(fov_id)
                    thr_id = int(thr_id)
                    chs_to_compute = non_source_channels.get(thr_id, [])
                    if not chs_to_compute:
                        continue

                    # Read particle labels (cached)
                    if thr_id not in plabel_cache:
                        try:
                            plabel_cache[thr_id] = self.read_particle_labels(thr_id)
                        except Exception:
                            logger.debug("Cannot read particle labels for thr %d", thr_id)
                            continue
                    plabels = plabel_cache[thr_id]

                    for ch_name in chs_to_compute:
                        cache_key = (fov_id, ch_name)
                        if cache_key not in img_cache:
                            try:
                                img_cache[cache_key] = self.read_image_numpy(fov_id, ch_name)
                            except Exception:
                                logger.debug("Cannot read channel %s for fov %d", ch_name, fov_id)
                                continue
                        ch_img = img_cache[cache_key]

                        props = regionprops(plabels, intensity_image=ch_img)
                        props_by_label: dict[int, object] = {p.label: p for p in props}

                        for idx in grp.index:
                            lv = int(df.at[idx, "label_value"])
                            prop = props_by_label.get(lv)
                            if prop is None:
                                continue
                            df.at[idx, f"mean_intensity_{ch_name}"] = float(prop.intensity_mean)
                            df.at[idx, f"max_intensity_{ch_name}"] = float(
                                np.max(ch_img[plabels == lv])
                            )
                            df.at[idx, f"integrated_intensity_{ch_name}"] = float(
                                np.sum(ch_img[plabels == lv])
                            )

            # De-duplicate intensity_cols (preserve order)
            seen: set[str] = set()
            intensity_cols = [c for c in intensity_cols if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]
        else:
            # No channels specified — keep original single-column intensities
            intensity_cols = [c for c in intensity_base_metrics if c in df.columns]

        # --- Apply metrics filter ---
        geom_metric_cols = [
            "area_pixels", "area_um2", "perimeter",
            "circularity", "eccentricity", "solidity",
            "major_axis_length", "minor_axis_length",
        ]
        if metrics is not None:
            # Keep geometry metrics that are in the filter
            geom_metric_cols = [c for c in geom_metric_cols if c in metrics]
            # Keep intensity columns whose base metric name is in the filter
            intensity_cols = [
                c for c in intensity_cols
                if any(c == base or c.startswith(f"{base}_") for base in metrics)
            ]

        # --- Assemble column order ---
        context_cols = [
            "fov_name", "condition_name", "bio_rep_name",
            "threshold_name", "cell_id", "cell_label",
        ]
        position_cols = ["label_value", "centroid_x", "centroid_y"]
        ordered_cols = context_cols + position_cols + geom_metric_cols + intensity_cols
        available_cols = [c for c in ordered_cols if c in df.columns]
        df = df[available_cols]

        if include_provenance:
            provenance = self._get_config_provenance()
            with open(path, "w") as f:
                for line in provenance:
                    f.write(line + "\n")
                df.to_csv(f, index=False)
        else:
            df.to_csv(path, index=False)
