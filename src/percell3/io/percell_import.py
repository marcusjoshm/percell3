"""Import FOVs from another PerCell 3 project.

Copies selected FOVs and all associated data (channels, segmentations,
thresholds, cells, measurements, particles, tags) from a source project
into the current destination project, with full ID remapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)

BATCH_SIZE = 900  # SQLite bind param safety margin (limit is 999)


@dataclass
class RemapTable:
    """Maps source project IDs to destination project IDs."""

    fov: dict[int, int] = field(default_factory=dict)
    segmentation: dict[int, int] = field(default_factory=dict)
    threshold: dict[int, int] = field(default_factory=dict)
    cell: dict[int, int] = field(default_factory=dict)
    channel: dict[int, int] = field(default_factory=dict)
    condition: dict[int, int] = field(default_factory=dict)
    bio_rep: dict[int, int] = field(default_factory=dict)
    tag: dict[int, int] = field(default_factory=dict)


@dataclass
class ImportResult:
    """Summary of a PerCell import operation."""

    fovs_imported: int = 0
    channels_created: int = 0
    conditions_created: int = 0
    segmentations_created: int = 0
    thresholds_created: int = 0
    cells_imported: int = 0
    measurements_imported: int = 0
    particles_imported: int = 0
    warnings: list[str] = field(default_factory=list)


class PerCellImporter:
    """Import FOVs from a source PerCell project into a destination project.

    Args:
        src: Source ExperimentStore (read-only usage).
        dst: Destination ExperimentStore (read-write).
    """

    def __init__(self, src: ExperimentStore, dst: ExperimentStore) -> None:
        self._src = src
        self._dst = dst
        self._remap = RemapTable()
        self._result = ImportResult()

    def import_fovs(
        self,
        fov_ids: list[int],
        progress_callback: Any | None = None,
    ) -> ImportResult:
        """Import selected FOVs from the source project.

        Args:
            fov_ids: List of source FOV IDs to import.
            progress_callback: Optional (current, total, message) callback.

        Returns:
            ImportResult with counts and warnings.
        """
        # Guard: same-project import
        if self._src.path.resolve() == self._dst.path.resolve():
            raise ValueError("Cannot import from the same project.")

        # Phase 1: Match/create global entities (channels, conditions, bio_reps)
        self._match_channels()
        self._match_conditions()
        self._match_bio_reps()
        self._match_tags()

        # Phase 2: Import each FOV with per-FOV atomicity
        for idx, src_fov_id in enumerate(fov_ids):
            dst_fov_id = None
            try:
                dst_fov_id = self._import_single_fov(src_fov_id)
                self._result.fovs_imported += 1
            except Exception as exc:
                if dst_fov_id is not None:
                    try:
                        self._dst.delete_fov(dst_fov_id)
                    except Exception:
                        pass
                src_fov = self._src.get_fov_by_id(src_fov_id)
                self._result.warnings.append(
                    f"Failed to import FOV {src_fov.display_name}: {exc}"
                )
                logger.warning("Import failed for FOV %d: %s", src_fov_id, exc)
                continue

            if progress_callback:
                src_fov = self._src.get_fov_by_id(src_fov_id)
                progress_callback(idx + 1, len(fov_ids), src_fov.display_name)

        return self._result

    # ------------------------------------------------------------------
    # Entity matching (global entities — run once before FOV loop)
    # ------------------------------------------------------------------

    def _match_channels(self) -> None:
        """Match source channels to destination by name, creating missing ones."""
        from percell3.core.exceptions import DuplicateError

        src_channels = self._src.get_channels()
        dst_channels = {ch.name: ch for ch in self._dst.get_channels()}

        for src_ch in src_channels:
            if src_ch.name in dst_channels:
                self._remap.channel[src_ch.id] = dst_channels[src_ch.name].id
            else:
                try:
                    new_id = self._dst.add_channel(
                        src_ch.name,
                        role=src_ch.role,
                        color=src_ch.color,
                        excitation_nm=src_ch.excitation_nm,
                        emission_nm=src_ch.emission_nm,
                        is_segmentation=src_ch.is_segmentation,
                    )
                except DuplicateError:
                    # Race or re-run — find existing
                    dst_ch = self._dst.get_channel(src_ch.name)
                    new_id = dst_ch.id
                self._remap.channel[src_ch.id] = new_id
                self._result.channels_created += 1

    def _match_conditions(self) -> None:
        """Match source conditions to destination by name, creating missing ones."""
        src_conditions = self._src.get_conditions()
        dst_conditions = set(self._dst.get_conditions())

        # Build src name→id map
        src_cond_map = {}
        for name in src_conditions:
            row = self._src._conn.execute(
                "SELECT id FROM conditions WHERE name = ?", (name,),
            ).fetchone()
            if row:
                src_cond_map[name] = row["id"]

        for name, src_id in src_cond_map.items():
            if name in dst_conditions:
                row = self._dst._conn.execute(
                    "SELECT id FROM conditions WHERE name = ?", (name,),
                ).fetchone()
                self._remap.condition[src_id] = row["id"]
            else:
                new_id = self._dst.add_condition(name)
                self._remap.condition[src_id] = new_id
                self._result.conditions_created += 1

    def _match_bio_reps(self) -> None:
        """Match source bio_reps to destination by name, creating missing ones."""
        src_bio_reps = self._src.get_bio_reps()
        dst_bio_reps = set(self._dst.get_bio_reps())

        for name in src_bio_reps:
            row = self._src._conn.execute(
                "SELECT id FROM bio_reps WHERE name = ?", (name,),
            ).fetchone()
            if row is None:
                continue
            src_id = row["id"]
            if name in dst_bio_reps:
                dst_row = self._dst._conn.execute(
                    "SELECT id FROM bio_reps WHERE name = ?", (name,),
                ).fetchone()
                self._remap.bio_rep[src_id] = dst_row["id"]
            else:
                new_id = self._dst.add_bio_rep(name)
                self._remap.bio_rep[src_id] = new_id

    def _match_tags(self) -> None:
        """Match source tags to destination by name, creating missing ones."""
        src_rows = self._src._conn.execute(
            "SELECT id, name, color FROM tags ORDER BY id",
        ).fetchall()
        dst_tag_map: dict[str, int] = {}
        for row in self._dst._conn.execute(
            "SELECT id, name FROM tags ORDER BY id",
        ).fetchall():
            dst_tag_map[row["name"]] = row["id"]

        for src_row in src_rows:
            src_id = src_row["id"]
            name = src_row["name"]
            if name in dst_tag_map:
                self._remap.tag[src_id] = dst_tag_map[name]
            else:
                new_id = self._dst.add_tag(name, color=src_row["color"])
                self._remap.tag[src_id] = new_id
                dst_tag_map[name] = new_id

    # ------------------------------------------------------------------
    # Per-FOV import
    # ------------------------------------------------------------------

    def _import_single_fov(self, src_fov_id: int) -> int:
        """Import a single FOV and all its associated data.

        Returns the destination FOV ID.
        """
        src_fov = self._src.get_fov_by_id(src_fov_id)

        # Resolve destination display_name (handle collision)
        display_name = self._unique_fov_name(src_fov.display_name)

        # Create FOV (auto-creates whole_field seg + config)
        dst_fov_id = self._dst.add_fov(
            condition=src_fov.condition,
            bio_rep=src_fov.bio_rep,
            display_name=display_name,
            width=src_fov.width,
            height=src_fov.height,
            pixel_size_um=src_fov.pixel_size_um,
        )
        self._remap.fov[src_fov_id] = dst_fov_id

        # Copy channel images
        self._copy_channel_images(src_fov_id, dst_fov_id)

        # Import segmentations, thresholds, cells, measurements, particles
        self._import_fov_layers(src_fov_id, dst_fov_id)

        # Update status cache
        self._dst.update_fov_status_cache(dst_fov_id)

        return dst_fov_id

    def _unique_fov_name(self, name: str) -> str:
        """Generate a unique FOV display_name in the destination."""
        existing = {f.display_name for f in self._dst.get_fovs()}
        if name not in existing:
            return name
        for i in range(1, 1000):
            candidate = f"{name}_imported_{i}"
            if candidate not in existing:
                self._result.warnings.append(
                    f"FOV name '{name}' already exists, renamed to '{candidate}'"
                )
                return candidate
        raise ValueError(f"Cannot generate unique name for FOV '{name}'")

    def _copy_channel_images(
        self, src_fov_id: int, dst_fov_id: int,
    ) -> None:
        """Copy all channel images from source FOV to destination FOV."""
        src_channels = self._src.get_channels()
        for src_ch in src_channels:
            try:
                image = self._src.read_image_numpy(src_fov_id, src_ch.name)
            except Exception:
                # Channel may not exist on this FOV
                continue
            self._dst.write_image(dst_fov_id, src_ch.name, image)

    # ------------------------------------------------------------------
    # Layer import (segmentations, thresholds, cells, measurements, particles)
    # ------------------------------------------------------------------

    def _import_fov_layers(self, src_fov_id: int, dst_fov_id: int) -> None:
        """Import segmentations, thresholds, and all dependent data for a FOV."""
        src_config = self._src.get_fov_config(src_fov_id)

        # Collect unique segmentation and threshold IDs from config
        seg_ids_seen: set[int] = set()
        thr_ids_seen: set[int] = set()

        for entry in src_config:
            seg_ids_seen.add(entry.segmentation_id)
            if entry.threshold_id is not None:
                thr_ids_seen.add(entry.threshold_id)

        # Import segmentations (dedup: skip if already remapped)
        for src_seg_id in seg_ids_seen:
            if src_seg_id not in self._remap.segmentation:
                self._import_segmentation(src_seg_id, src_fov_id)

        # Import cells for this FOV (needs seg remap)
        self._import_cells(src_fov_id, dst_fov_id)

        # Import thresholds (dedup: skip if already remapped)
        for src_thr_id in thr_ids_seen:
            if src_thr_id not in self._remap.threshold:
                self._import_threshold(src_thr_id, src_fov_id)

        # Import measurements (needs cell, channel, seg, threshold remap)
        self._import_measurements(src_fov_id)

        # Import particles (needs fov, threshold remap)
        self._import_particles(src_fov_id, dst_fov_id)

        # Import cell tags
        self._import_cell_tags(src_fov_id)

        # Rebuild fov_config in destination
        self._import_fov_config(src_fov_id, dst_fov_id)

    def _import_segmentation(self, src_seg_id: int, src_fov_id: int) -> None:
        """Import a segmentation entity and its label image."""
        src_seg = self._src.get_segmentation(src_seg_id)

        # Check if this is a whole_field seg — map to destination's auto-created one
        if src_seg.seg_type == "whole_field":
            dst_wf_segs = self._dst.get_segmentations(
                seg_type="whole_field",
                width=src_seg.width,
                height=src_seg.height,
            )
            if dst_wf_segs:
                self._remap.segmentation[src_seg_id] = dst_wf_segs[0].id
                return

        # Create new segmentation with unique name
        name = self._unique_seg_name(src_seg.name)
        # Don't pass source_fov_id to avoid auto-config side effects
        dst_seg_id = self._dst.add_segmentation(
            name=name,
            seg_type=src_seg.seg_type,
            width=src_seg.width,
            height=src_seg.height,
            source_channel=src_seg.source_channel,
            model_name=src_seg.model_name or "",
            parameters=src_seg.parameters,
        )
        self._remap.segmentation[src_seg_id] = dst_seg_id
        self._result.segmentations_created += 1

        # Copy label image
        try:
            labels = self._src.read_labels(src_seg_id)
            self._dst.write_labels(labels, dst_seg_id)
        except Exception as exc:
            logger.warning(
                "Failed to copy labels for segmentation %d: %s", src_seg_id, exc,
            )

    def _unique_seg_name(self, name: str) -> str:
        """Generate a unique segmentation name in the destination."""
        existing = {s.name for s in self._dst.get_segmentations()}
        if name not in existing:
            return name
        for i in range(1, 1000):
            candidate = f"{name}_imported_{i}"
            if candidate not in existing:
                return candidate
        raise ValueError(f"Cannot generate unique name for segmentation '{name}'")

    def _import_threshold(self, src_thr_id: int, src_fov_id: int) -> None:
        """Import a threshold entity and its mask/particle label images."""
        src_thr = self._src.get_threshold(src_thr_id)

        name = self._unique_thr_name(src_thr.name)
        # Don't pass source_fov_id to avoid auto-config side effects
        dst_thr_id = self._dst.add_threshold(
            name=name,
            method=src_thr.method,
            width=src_thr.width,
            height=src_thr.height,
            source_channel=src_thr.source_channel,
            grouping_channel=src_thr.grouping_channel,
            parameters=src_thr.parameters,
        )
        self._remap.threshold[src_thr_id] = dst_thr_id
        self._result.thresholds_created += 1

        # Copy mask
        try:
            mask = self._src.read_mask(src_thr_id)
            self._dst.write_mask(mask, dst_thr_id)
        except Exception as exc:
            logger.warning(
                "Failed to copy mask for threshold %d: %s", src_thr_id, exc,
            )

        # Copy particle labels
        try:
            particle_labels = self._src.read_particle_labels(src_thr_id)
            self._dst.write_particle_labels(particle_labels, dst_thr_id)
        except Exception as exc:
            # Particle labels may not exist
            logger.debug(
                "No particle labels for threshold %d: %s", src_thr_id, exc,
            )

    def _unique_thr_name(self, name: str) -> str:
        """Generate a unique threshold name in the destination."""
        existing = {t.name for t in self._dst.get_thresholds()}
        if name not in existing:
            return name
        for i in range(1, 1000):
            candidate = f"{name}_imported_{i}"
            if candidate not in existing:
                return candidate
        raise ValueError(f"Cannot generate unique name for threshold '{name}'")

    def _import_cells(self, src_fov_id: int, dst_fov_id: int) -> None:
        """Import all cells for a FOV with remapped IDs."""
        from percell3.core.models import CellRecord

        # Get all cells (including invalid) for the source FOV
        src_cells_df = self._src.get_cells(fov_id=src_fov_id, is_valid=False)
        if src_cells_df.empty:
            return

        records: list[CellRecord] = []
        src_cell_ids: list[int] = []

        for _, row in src_cells_df.iterrows():
            src_cell_id = int(row["id"])
            src_seg_id = int(row["segmentation_id"])
            dst_seg_id = self._remap.segmentation.get(src_seg_id)
            if dst_seg_id is None:
                continue  # Segmentation not imported

            records.append(CellRecord(
                fov_id=dst_fov_id,
                segmentation_id=dst_seg_id,
                label_value=int(row["label_value"]),
                centroid_x=float(row["centroid_x"]),
                centroid_y=float(row["centroid_y"]),
                bbox_x=int(row["bbox_x"]),
                bbox_y=int(row["bbox_y"]),
                bbox_w=int(row["bbox_w"]),
                bbox_h=int(row["bbox_h"]),
                area_pixels=float(row["area_pixels"]),
                area_um2=float(row["area_um2"]) if row.get("area_um2") is not None else None,
                perimeter=float(row["perimeter"]) if row.get("perimeter") is not None else None,
                circularity=float(row["circularity"]) if row.get("circularity") is not None else None,
            ))
            src_cell_ids.append(src_cell_id)

        if not records:
            return

        new_ids = self._dst.add_cells(records)
        for src_id, dst_id in zip(src_cell_ids, new_ids):
            self._remap.cell[src_id] = dst_id
        self._result.cells_imported += len(new_ids)

    def _import_measurements(self, src_fov_id: int) -> None:
        """Import all measurements for cells in a source FOV."""
        from percell3.core.models import MeasurementRecord

        # Get source cell IDs for this FOV
        src_cells_df = self._src.get_cells(fov_id=src_fov_id, is_valid=False)
        if src_cells_df.empty:
            return
        src_cell_ids = src_cells_df["id"].tolist()

        # Build destination channel name→id map
        dst_ch_map = {ch.name: ch.id for ch in self._dst.get_channels()}

        # Query source measurements in batches (SQLite bind param limit)
        all_records: list[MeasurementRecord] = []
        for batch_start in range(0, len(src_cell_ids), BATCH_SIZE):
            batch_ids = src_cell_ids[batch_start:batch_start + BATCH_SIZE]
            src_rows = self._src.get_measurements(cell_ids=batch_ids)
            if src_rows.empty:
                continue

            for _, row in src_rows.iterrows():
                src_cell_id = int(row["cell_id"])
                dst_cell_id = self._remap.cell.get(src_cell_id)
                if dst_cell_id is None:
                    continue

                channel_name = row["channel"]
                dst_ch_id = dst_ch_map.get(channel_name)
                if dst_ch_id is None:
                    continue

                # Remap segmentation_id and threshold_id
                dst_seg_id = None
                if row.get("segmentation_id") is not None:
                    import math
                    seg_val = row["segmentation_id"]
                    if not (isinstance(seg_val, float) and math.isnan(seg_val)):
                        dst_seg_id = self._remap.segmentation.get(int(seg_val))

                dst_thr_id = None
                if row.get("threshold_id") is not None:
                    thr_val = row["threshold_id"]
                    if not (isinstance(thr_val, float) and math.isnan(thr_val)):
                        dst_thr_id = self._remap.threshold.get(int(thr_val))

                all_records.append(MeasurementRecord(
                    cell_id=dst_cell_id,
                    channel_id=dst_ch_id,
                    metric=row["metric"],
                    value=float(row["value"]),
                    scope=row.get("scope", "whole_cell") or "whole_cell",
                    segmentation_id=dst_seg_id,
                    threshold_id=dst_thr_id,
                    measured_at=row.get("measured_at"),
                ))

        if all_records:
            # Batch insert measurements
            for batch_start in range(0, len(all_records), BATCH_SIZE):
                batch = all_records[batch_start:batch_start + BATCH_SIZE]
                self._dst.add_measurements(batch)
            self._result.measurements_imported += len(all_records)

    def _import_particles(self, src_fov_id: int, dst_fov_id: int) -> None:
        """Import all particles for a source FOV."""
        from percell3.core.models import ParticleRecord

        src_particles_df = self._src.get_particles(fov_id=src_fov_id)
        if src_particles_df.empty:
            return

        records: list[ParticleRecord] = []
        for _, row in src_particles_df.iterrows():
            src_thr_id = int(row["threshold_id"])
            dst_thr_id = self._remap.threshold.get(src_thr_id)
            if dst_thr_id is None:
                continue

            records.append(ParticleRecord(
                fov_id=dst_fov_id,
                threshold_id=dst_thr_id,
                label_value=int(row["label_value"]),
                centroid_x=float(row["centroid_x"]),
                centroid_y=float(row["centroid_y"]),
                bbox_x=int(row["bbox_x"]),
                bbox_y=int(row["bbox_y"]),
                bbox_w=int(row["bbox_w"]),
                bbox_h=int(row["bbox_h"]),
                area_pixels=float(row["area_pixels"]),
                area_um2=float(row["area_um2"]) if row.get("area_um2") is not None else None,
                perimeter=float(row["perimeter"]) if row.get("perimeter") is not None else None,
                circularity=float(row["circularity"]) if row.get("circularity") is not None else None,
                eccentricity=float(row["eccentricity"]) if row.get("eccentricity") is not None else None,
                solidity=float(row["solidity"]) if row.get("solidity") is not None else None,
                major_axis_length=float(row["major_axis_length"]) if row.get("major_axis_length") is not None else None,
                minor_axis_length=float(row["minor_axis_length"]) if row.get("minor_axis_length") is not None else None,
                mean_intensity=float(row["mean_intensity"]) if row.get("mean_intensity") is not None else None,
                max_intensity=float(row["max_intensity"]) if row.get("max_intensity") is not None else None,
                integrated_intensity=float(row["integrated_intensity"]) if row.get("integrated_intensity") is not None else None,
            ))

        if records:
            self._dst.add_particles(records)
            self._result.particles_imported += len(records)

    def _import_cell_tags(self, src_fov_id: int) -> None:
        """Import cell tags for all cells in a source FOV."""
        src_cells_df = self._src.get_cells(fov_id=src_fov_id, is_valid=False)
        if src_cells_df.empty:
            return
        src_cell_ids = src_cells_df["id"].tolist()

        # Query cell_tags from source in batches
        for batch_start in range(0, len(src_cell_ids), BATCH_SIZE):
            batch_ids = src_cell_ids[batch_start:batch_start + BATCH_SIZE]
            placeholders = ",".join("?" * len(batch_ids))
            rows = self._src._conn.execute(
                f"SELECT cell_id, tag_id FROM cell_tags "
                f"WHERE cell_id IN ({placeholders})",
                batch_ids,
            ).fetchall()

            # Group by tag_id for batch insert
            tag_cells: dict[int, list[int]] = {}
            for row in rows:
                src_cell_id = row["cell_id"]
                src_tag_id = row["tag_id"]
                dst_cell_id = self._remap.cell.get(src_cell_id)
                dst_tag_id = self._remap.tag.get(src_tag_id)
                if dst_cell_id is not None and dst_tag_id is not None:
                    tag_cells.setdefault(dst_tag_id, []).append(dst_cell_id)

            # Insert cell_tags in destination
            for dst_tag_id, dst_cell_ids in tag_cells.items():
                self._dst._conn.executemany(
                    "INSERT OR IGNORE INTO cell_tags (cell_id, tag_id) "
                    "VALUES (?, ?)",
                    [(cid, dst_tag_id) for cid in dst_cell_ids],
                )
            if tag_cells:
                self._dst._conn.commit()

    def _import_fov_config(self, src_fov_id: int, dst_fov_id: int) -> None:
        """Rebuild fov_config entries for the imported FOV."""
        src_config = self._src.get_fov_config(src_fov_id)

        # Skip entries that are just the auto-created whole_field default
        # (add_fov already created that)
        auto_created = set()
        dst_config = self._dst.get_fov_config(dst_fov_id)
        for entry in dst_config:
            auto_created.add((entry.segmentation_id, entry.threshold_id))

        for entry in src_config:
            dst_seg_id = self._remap.segmentation.get(entry.segmentation_id)
            if dst_seg_id is None:
                continue

            dst_thr_id = None
            if entry.threshold_id is not None:
                dst_thr_id = self._remap.threshold.get(entry.threshold_id)

            # Skip if already auto-created
            if (dst_seg_id, dst_thr_id) in auto_created:
                continue

            try:
                self._dst.set_fov_config_entry(
                    dst_fov_id, dst_seg_id,
                    threshold_id=dst_thr_id,
                    scopes=entry.scopes,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create fov_config entry for FOV %d: %s",
                    dst_fov_id, exc,
                )
