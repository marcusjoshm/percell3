"""ExperimentStore — central interface for a PerCell 3 experiment."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


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
            "Only alphanumeric, dots, hyphens, and underscores are allowed."
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
)
from percell3.core.models import CellRecord, ChannelConfig, FovInfo, MeasurementRecord
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
    def create(cls, path: Path, name: str = "", description: str = "") -> ExperimentStore:
        """Create a new .percell experiment directory."""
        path = Path(path)
        if path.exists():
            raise ExperimentError(f"Path already exists: {path}")
        path.mkdir(parents=True)

        # Create SQLite database
        db_path = path / "experiment.db"
        conn = create_schema(db_path, name=name, description=description)

        # Create zarr stores
        zarr_io.init_zarr_store(path / "images.zarr")
        zarr_io.init_zarr_store(path / "labels.zarr")
        zarr_io.init_zarr_store(path / "masks.zarr")

        # Create exports directory
        (path / "exports").mkdir()

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
        _validate_name(name, "bio_rep name")
        return queries.insert_bio_rep(self._conn, name)

    def get_bio_reps(self) -> list[str]:
        return queries.select_bio_reps(self._conn)

    def get_bio_rep(self, name: str) -> str:
        row = queries.select_bio_rep_by_name(self._conn, name)
        return row["name"]

    def _resolve_bio_rep(self, bio_rep: str | None) -> tuple[int, str]:
        """Resolve bio_rep name to (id, name). Auto-resolves when only 1 exists."""
        if bio_rep is not None:
            return queries.select_bio_rep_id(self._conn, bio_rep), bio_rep
        reps = queries.select_bio_reps(self._conn)
        if len(reps) == 1:
            return queries.select_bio_rep_id(self._conn, reps[0]), reps[0]
        raise BioRepNotFoundError(
            f"Multiple bio reps exist ({', '.join(reps)}); specify one explicitly"
        )

    # --- Condition/Timepoint/FOV Management ---

    def add_condition(self, name: str, description: str = "") -> int:
        _validate_name(name, "condition name")
        return queries.insert_condition(self._conn, name, description)

    def add_timepoint(self, name: str, time_seconds: float | None = None) -> int:
        _validate_name(name, "timepoint name")
        return queries.insert_timepoint(self._conn, name, time_seconds)

    def add_fov(
        self,
        name: str,
        condition: str,
        bio_rep: str | None = None,
        timepoint: str | None = None,
        width: int | None = None,
        height: int | None = None,
        pixel_size_um: float | None = None,
        source_file: str | None = None,
    ) -> int:
        _validate_name(name, "fov name")
        bio_rep_id, _ = self._resolve_bio_rep(bio_rep)
        cond_id = queries.select_condition_id(self._conn, condition)
        tp_id = queries.select_timepoint_id(self._conn, timepoint) if timepoint else None
        return queries.insert_fov(
            self._conn, name, condition_id=cond_id, bio_rep_id=bio_rep_id,
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
        br_id = queries.select_bio_rep_id(self._conn, bio_rep) if bio_rep else None
        tp_id = queries.select_timepoint_id(self._conn, timepoint) if timepoint else None
        return queries.select_fovs(
            self._conn, condition_id=cond_id, bio_rep_id=br_id, timepoint_id=tp_id,
        )

    # --- Image I/O ---

    def _resolve_fov(
        self,
        fov: str,
        condition: str,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> tuple[FovInfo, str]:
        """Resolve FOV name to FovInfo and zarr group path."""
        br_id, br_name = self._resolve_bio_rep(bio_rep)
        cond_id = queries.select_condition_id(self._conn, condition)
        tp_id = queries.select_timepoint_id(self._conn, timepoint) if timepoint else None
        fov_info = queries.select_fov_by_name(
            self._conn, fov, condition_id=cond_id, bio_rep_id=br_id, timepoint_id=tp_id,
        )
        gp = zarr_io.image_group_path(br_name, condition, fov, timepoint)
        return fov_info, gp

    def _channels_meta(self) -> list[dict]:
        """Build channel metadata list for NGFF."""
        channels = self.get_channels()
        return [{"name": ch.name, "color": ch.color or "FFFFFF"} for ch in channels]

    def write_image(
        self,
        fov: str,
        condition: str,
        channel: str,
        data: np.ndarray,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> None:
        fov_info, gp = self._resolve_fov(fov, condition, bio_rep, timepoint)
        ch = self.get_channel(channel)
        channels = self.get_channels()
        num_channels = len(channels)

        zarr_io.write_image_channel(
            self.images_zarr_path,
            gp,
            channel_index=ch.display_order,
            num_channels=num_channels,
            data=data,
            channels_meta=self._channels_meta(),
            pixel_size_um=fov_info.pixel_size_um,
        )

    def read_image(
        self,
        fov: str,
        condition: str,
        channel: str,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> da.Array:
        _, gp = self._resolve_fov(fov, condition, bio_rep, timepoint)
        ch = self.get_channel(channel)
        return zarr_io.read_image_channel(self.images_zarr_path, gp, ch.display_order)

    def read_image_numpy(
        self,
        fov: str,
        condition: str,
        channel: str,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> np.ndarray:
        _, gp = self._resolve_fov(fov, condition, bio_rep, timepoint)
        ch = self.get_channel(channel)
        return zarr_io.read_image_channel_numpy(
            self.images_zarr_path, gp, ch.display_order
        )

    # --- Label Images ---

    def write_labels(
        self,
        fov: str,
        condition: str,
        labels: np.ndarray,
        segmentation_run_id: int,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> None:
        fov_info, _ = self._resolve_fov(fov, condition, bio_rep, timepoint)
        br_name = fov_info.bio_rep
        gp = zarr_io.label_group_path(br_name, condition, fov, timepoint)
        img_gp = zarr_io.image_group_path(br_name, condition, fov, timepoint)
        source_path = f"../../images.zarr/{img_gp}"
        zarr_io.write_labels(
            self.labels_zarr_path, gp, labels,
            source_image_path=source_path,
            pixel_size_um=fov_info.pixel_size_um,
        )

    def read_labels(
        self,
        fov: str,
        condition: str,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> np.ndarray:
        _, br_name = self._resolve_bio_rep(bio_rep)
        gp = zarr_io.label_group_path(br_name, condition, fov, timepoint)
        return zarr_io.read_labels(self.labels_zarr_path, gp)

    # --- Cell Records ---

    def add_cells(self, cells: list[CellRecord]) -> list[int]:
        return queries.insert_cells(self._conn, cells)

    def get_cells(
        self,
        condition: str | None = None,
        bio_rep: str | None = None,
        fov: str | None = None,
        timepoint: str | None = None,
        is_valid: bool = True,
        min_area: float | None = None,
        max_area: float | None = None,
        tags: list[str] | None = None,
    ) -> pd.DataFrame:
        cond_id = queries.select_condition_id(self._conn, condition) if condition else None
        br_id = queries.select_bio_rep_id(self._conn, bio_rep) if bio_rep else None

        # Resolve fov to fov_id if provided
        fov_id = None
        if fov:
            if condition is None:
                raise ValueError("'condition' is required when filtering by 'fov'")
            tp_id = queries.select_timepoint_id(self._conn, timepoint) if timepoint else None
            fov_info = queries.select_fov_by_name(
                self._conn, fov, condition_id=cond_id, bio_rep_id=br_id,
                timepoint_id=tp_id,
            )
            fov_id = fov_info.id

        tp_id_filter = None
        if timepoint:
            tp_id_filter = queries.select_timepoint_id(self._conn, timepoint)

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
            timepoint_id=tp_id_filter,
            is_valid=is_valid,
            min_area=min_area,
            max_area=max_area,
            tag_ids=tag_ids or None,
        )
        return pd.DataFrame(rows)

    def get_cell_count(
        self,
        condition: str | None = None,
        bio_rep: str | None = None,
        fov: str | None = None,
        is_valid: bool = True,
    ) -> int:
        cond_id = queries.select_condition_id(self._conn, condition) if condition else None
        br_id = queries.select_bio_rep_id(self._conn, bio_rep) if bio_rep else None
        fov_id = None
        if fov:
            if condition is None:
                raise ValueError("'condition' is required when filtering by 'fov'")
            tp_id = None
            fov_info = queries.select_fov_by_name(
                self._conn, fov, condition_id=cond_id, bio_rep_id=br_id,
                timepoint_id=tp_id,
            )
            fov_id = fov_info.id
        return queries.count_cells(
            self._conn, condition_id=cond_id, bio_rep_id=br_id,
            fov_id=fov_id, is_valid=is_valid,
        )

    # --- Measurements ---

    def add_measurements(self, measurements: list[MeasurementRecord]) -> None:
        queries.insert_measurements(self._conn, measurements)

    def get_measurements(
        self,
        cell_ids: list[int] | None = None,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> pd.DataFrame:
        channel_ids = None
        if channels:
            channel_ids = [self.get_channel(ch).id for ch in channels]
        rows = queries.select_measurements(
            self._conn, cell_ids=cell_ids, channel_ids=channel_ids, metrics=metrics,
        )
        return pd.DataFrame(rows)

    def get_measurement_pivot(
        self,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        include_cell_info: bool = True,
    ) -> pd.DataFrame:
        df = self.get_measurements(channels=channels, metrics=metrics)
        if df.empty:
            return df

        # Create pivot column: channel_metric
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
                             "area_pixels", "centroid_x", "centroid_y"]
                available = [c for c in cell_cols if c in cells_df.columns]
                if available:
                    merge_df = cells_df[available].rename(columns={"id": "cell_id"})
                    pivot = pivot.merge(merge_df, on="cell_id", how="left")

        return pivot

    # --- Masks ---

    def write_mask(
        self,
        fov: str,
        condition: str,
        channel: str,
        mask: np.ndarray,
        threshold_run_id: int,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> None:
        fov_info, _ = self._resolve_fov(fov, condition, bio_rep, timepoint)
        br_name = fov_info.bio_rep
        gp = zarr_io.mask_group_path(br_name, condition, fov, channel, timepoint)
        zarr_io.write_mask(
            self.masks_zarr_path, gp, mask,
            pixel_size_um=fov_info.pixel_size_um,
        )

    def read_mask(
        self,
        fov: str,
        condition: str,
        channel: str,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> np.ndarray:
        _, br_name = self._resolve_bio_rep(bio_rep)
        gp = zarr_io.mask_group_path(br_name, condition, fov, channel, timepoint)
        return zarr_io.read_mask(self.masks_zarr_path, gp)

    # --- Segmentation Runs ---

    def add_segmentation_run(
        self,
        channel: str,
        model_name: str,
        parameters: dict | None = None,
    ) -> int:
        ch = self.get_channel(channel)
        return queries.insert_segmentation_run(
            self._conn, ch.id, model_name, parameters
        )

    def update_segmentation_run_cell_count(
        self, run_id: int, cell_count: int
    ) -> None:
        """Update the cell count for a segmentation run."""
        queries.update_segmentation_run_cell_count(self._conn, run_id, cell_count)

    # --- Threshold Runs ---

    def add_threshold_run(
        self,
        channel: str,
        method: str,
        parameters: dict | None = None,
    ) -> int:
        ch = self.get_channel(channel)
        return queries.insert_threshold_run(
            self._conn, ch.id, method, parameters
        )

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

    def get_segmentation_runs(self) -> list[dict]:
        """Return all segmentation runs."""
        return queries.select_segmentation_runs(self._conn)

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

    # --- Export ---

    def export_csv(
        self,
        path: Path,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> None:
        pivot = self.get_measurement_pivot(
            channels=channels, metrics=metrics, include_cell_info=True,
        )
        pivot.to_csv(path, index=False)
