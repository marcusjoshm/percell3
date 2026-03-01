"""Tests for run-scoped operations: copy, combine, delete impact, export."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, DeleteImpact, MeasurementRecord, ParticleRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_experiment(tmp_path: Path, name: str = "test") -> ExperimentStore:
    """Create an experiment with DAPI and GFP channels, one condition."""
    store = ExperimentStore.create(tmp_path / f"{name}.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")
    return store


def _add_fov_with_seg_and_threshold(
    store: ExperimentStore,
    display_name: str = "fov1",
    width: int = 40,
    height: int = 40,
) -> tuple[int, int, int]:
    """Add a FOV with labels (2 cells) and a GFP threshold mask.

    Returns:
        (fov_id, seg_run_id, threshold_run_id)
    """
    fov_id = store.add_fov(
        "control", width=width, height=height,
        pixel_size_um=0.65, display_name=display_name,
    )

    # Images
    dapi = np.full((height, width), 100, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)
    gfp = np.full((height, width), 50, dtype=np.uint16)
    gfp[10:20, 10:20] = 200
    store.write_image(fov_id, "GFP", gfp)

    # Labels — 2 cells
    labels = np.zeros((height, width), dtype=np.int32)
    labels[5:20, 5:20] = 1
    labels[25:35, 25:35] = 2

    seg_run_id = store.add_segmentation_run(
        fov_id=fov_id, channel="DAPI", model_name="cyto3",
        parameters={"diameter": 30.0},
    )
    store.write_labels(fov_id, labels, seg_run_id)

    from percell3.segment.label_processor import extract_cells

    cells = extract_cells(labels, fov_id, seg_run_id, 0.65)
    if cells:
        store.add_cells(cells)
    store.update_segmentation_run_cell_count(seg_run_id, len(cells))

    # Threshold mask on GFP
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[10:20, 10:20] = 255
    thr_run_id = store.add_threshold_run(
        fov_id=fov_id, channel="GFP", method="otsu",
        parameters={"threshold_value": 100.0},
    )
    store.write_mask(fov_id, "GFP", mask, thr_run_id)

    return fov_id, seg_run_id, thr_run_id


# ---------------------------------------------------------------------------
# Copy Segmentation Tests
# ---------------------------------------------------------------------------


class TestCopySegmentationToFov:
    """Tests for ExperimentStore.copy_segmentation_to_fov()."""

    def test_labels_copied_and_cells_recomputed(self, tmp_path: Path) -> None:
        """Labels are written to target and cells extracted via regionprops."""
        store = _create_experiment(tmp_path)
        src_fov_id, src_seg_id, _ = _add_fov_with_seg_and_threshold(store)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target",
        )
        store.write_image(target_fov_id, "DAPI", np.full((40, 40), 80, np.uint16))

        new_run_id, cell_count = store.copy_segmentation_to_fov(
            src_seg_id, target_fov_id,
        )

        assert new_run_id > 0
        assert cell_count == 2

        # Labels match
        src_labels = store.read_labels(src_fov_id, src_seg_id)
        tgt_labels = store.read_labels(target_fov_id, new_run_id)
        np.testing.assert_array_equal(src_labels, tgt_labels)

        # Cells belong to the new run
        cells_df = store.get_cells(fov_id=target_fov_id)
        assert len(cells_df) == 2
        assert (cells_df["segmentation_id"] == new_run_id).all()

    def test_provenance_recorded(self, tmp_path: Path) -> None:
        """New run records label_copy model and source info in parameters."""
        store = _create_experiment(tmp_path)
        src_fov_id, src_seg_id, _ = _add_fov_with_seg_and_threshold(store)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, display_name="target",
        )

        new_run_id, _ = store.copy_segmentation_to_fov(src_seg_id, target_fov_id)

        run = store.get_segmentation_run(new_run_id)
        assert run.model_name == "label_copy"
        assert run.parameters["source_fov_id"] == src_fov_id
        assert run.parameters["source_run_id"] == src_seg_id

    def test_existing_runs_preserved(self, tmp_path: Path) -> None:
        """Copying to a target that already has runs preserves them."""
        store = _create_experiment(tmp_path)
        src_fov_id, src_seg_id, _ = _add_fov_with_seg_and_threshold(store)

        # Target already has its own segmentation
        target_fov_id, tgt_seg_id, _ = _add_fov_with_seg_and_threshold(
            store, display_name="target",
        )

        new_run_id, _ = store.copy_segmentation_to_fov(src_seg_id, target_fov_id)

        runs = store.list_segmentation_runs(target_fov_id)
        run_ids = {r.id for r in runs}
        assert tgt_seg_id in run_ids  # original preserved
        assert new_run_id in run_ids  # new one added

    def test_dimension_mismatch_raises(self, tmp_path: Path) -> None:
        """Copying to a target with different dimensions raises ValueError."""
        store = _create_experiment(tmp_path)
        _, src_seg_id, _ = _add_fov_with_seg_and_threshold(store)

        target_fov_id = store.add_fov(
            "control", width=80, height=80, display_name="big_target",
        )

        with pytest.raises(ValueError, match="Dimension mismatch"):
            store.copy_segmentation_to_fov(src_seg_id, target_fov_id)

    def test_custom_name(self, tmp_path: Path) -> None:
        """Custom run name is used when provided."""
        store = _create_experiment(tmp_path)
        _, src_seg_id, _ = _add_fov_with_seg_and_threshold(store)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, display_name="target",
        )

        new_run_id, _ = store.copy_segmentation_to_fov(
            src_seg_id, target_fov_id, name="my_copy",
        )

        run = store.get_segmentation_run(new_run_id)
        assert run.name == "my_copy"


# ---------------------------------------------------------------------------
# Copy Threshold Tests
# ---------------------------------------------------------------------------


class TestCopyThresholdToFov:
    """Tests for ExperimentStore.copy_threshold_to_fov()."""

    def test_mask_copied_particles_deferred(self, tmp_path: Path) -> None:
        """Mask is copied, but no particles are extracted."""
        store = _create_experiment(tmp_path)
        src_fov_id, _, src_thr_id = _add_fov_with_seg_and_threshold(store)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, display_name="target",
        )

        new_run_id = store.copy_threshold_to_fov(src_thr_id, target_fov_id)

        # Mask matches
        src_mask = store.read_mask(src_fov_id, "GFP", src_thr_id)
        tgt_mask = store.read_mask(target_fov_id, "GFP", new_run_id)
        np.testing.assert_array_equal(src_mask, tgt_mask)

        # No particles created
        particles = store._conn.execute(
            "SELECT COUNT(*) FROM particles WHERE threshold_run_id = ?",
            (new_run_id,),
        ).fetchone()[0]
        assert particles == 0

    def test_provenance_recorded(self, tmp_path: Path) -> None:
        """New threshold run records mask_copy provenance."""
        store = _create_experiment(tmp_path)
        src_fov_id, _, src_thr_id = _add_fov_with_seg_and_threshold(store)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, display_name="target",
        )

        new_run_id = store.copy_threshold_to_fov(src_thr_id, target_fov_id)

        run = store.get_threshold_run(new_run_id)
        assert run.method == "mask_copy"
        assert run.parameters["source_fov_id"] == src_fov_id
        assert run.parameters["source_run_id"] == src_thr_id


# ---------------------------------------------------------------------------
# Combine Threshold Tests
# ---------------------------------------------------------------------------


class TestCombineThresholdRuns:
    """Tests for ExperimentStore.combine_threshold_runs()."""

    def test_union_pixel_level(self, tmp_path: Path) -> None:
        """Union combines masks with pixel-level OR."""
        store = _create_experiment(tmp_path)
        fov_id = store.add_fov("control", width=20, height=20)

        # Mask 1: top-left
        mask1 = np.zeros((20, 20), dtype=np.uint8)
        mask1[0:10, 0:10] = 255
        thr1 = store.add_threshold_run(fov_id=fov_id, channel="GFP", method="m1")
        store.write_mask(fov_id, "GFP", mask1, thr1)

        # Mask 2: bottom-right
        mask2 = np.zeros((20, 20), dtype=np.uint8)
        mask2[10:20, 10:20] = 255
        thr2 = store.add_threshold_run(fov_id=fov_id, channel="GFP", method="m2")
        store.write_mask(fov_id, "GFP", mask2, thr2)

        combined_id = store.combine_threshold_runs(
            [thr1, thr2], operation="union",
        )

        combined_mask = store.read_mask(fov_id, "GFP", combined_id)
        expected = np.maximum(mask1, mask2)
        np.testing.assert_array_equal(combined_mask, expected)

    def test_intersect_pixel_level(self, tmp_path: Path) -> None:
        """Intersect combines masks with pixel-level AND."""
        store = _create_experiment(tmp_path)
        fov_id = store.add_fov("control", width=20, height=20)

        # Mask 1: left half
        mask1 = np.zeros((20, 20), dtype=np.uint8)
        mask1[:, 0:15] = 255
        thr1 = store.add_threshold_run(fov_id=fov_id, channel="GFP", method="m1")
        store.write_mask(fov_id, "GFP", mask1, thr1)

        # Mask 2: top half
        mask2 = np.zeros((20, 20), dtype=np.uint8)
        mask2[0:15, :] = 255
        thr2 = store.add_threshold_run(fov_id=fov_id, channel="GFP", method="m2")
        store.write_mask(fov_id, "GFP", mask2, thr2)

        combined_id = store.combine_threshold_runs(
            [thr1, thr2], operation="intersect",
        )

        combined_mask = store.read_mask(fov_id, "GFP", combined_id)
        expected = np.minimum(mask1, mask2)
        np.testing.assert_array_equal(combined_mask, expected)

    def test_same_fov_validation(self, tmp_path: Path) -> None:
        """Raises ValueError if runs are on different FOVs."""
        store = _create_experiment(tmp_path)
        fov1 = store.add_fov("control", width=20, height=20, display_name="fov1")
        fov2 = store.add_fov("control", width=20, height=20, display_name="fov2")

        mask = np.zeros((20, 20), dtype=np.uint8)
        thr1 = store.add_threshold_run(fov_id=fov1, channel="GFP", method="m1")
        store.write_mask(fov1, "GFP", mask, thr1)
        thr2 = store.add_threshold_run(fov_id=fov2, channel="GFP", method="m2")
        store.write_mask(fov2, "GFP", mask, thr2)

        with pytest.raises(ValueError, match="same FOV"):
            store.combine_threshold_runs([thr1, thr2], operation="union")

    def test_same_channel_validation(self, tmp_path: Path) -> None:
        """Raises ValueError if runs are on different channels."""
        store = _create_experiment(tmp_path)
        fov_id = store.add_fov("control", width=20, height=20)

        mask = np.zeros((20, 20), dtype=np.uint8)
        thr1 = store.add_threshold_run(fov_id=fov_id, channel="GFP", method="m1")
        store.write_mask(fov_id, "GFP", mask, thr1)
        thr2 = store.add_threshold_run(fov_id=fov_id, channel="DAPI", method="m2")
        store.write_mask(fov_id, "DAPI", mask, thr2)

        with pytest.raises(ValueError, match="same channel"):
            store.combine_threshold_runs([thr1, thr2], operation="union")

    def test_invalid_operation_raises(self, tmp_path: Path) -> None:
        """Raises ValueError for unknown operations."""
        store = _create_experiment(tmp_path)
        with pytest.raises(ValueError, match="operation must be"):
            store.combine_threshold_runs([1, 2], operation="xor")

    def test_fewer_than_two_raises(self, tmp_path: Path) -> None:
        """Raises ValueError if fewer than 2 runs provided."""
        store = _create_experiment(tmp_path)
        with pytest.raises(ValueError, match="at least 2"):
            store.combine_threshold_runs([1], operation="union")

    def test_provenance_recorded(self, tmp_path: Path) -> None:
        """Combined run records source run IDs in parameters."""
        store = _create_experiment(tmp_path)
        fov_id = store.add_fov("control", width=20, height=20)

        mask = np.zeros((20, 20), dtype=np.uint8)
        thr1 = store.add_threshold_run(fov_id=fov_id, channel="GFP", method="m1")
        store.write_mask(fov_id, "GFP", mask, thr1)
        thr2 = store.add_threshold_run(fov_id=fov_id, channel="GFP", method="m2")
        store.write_mask(fov_id, "GFP", mask, thr2)

        combined_id = store.combine_threshold_runs(
            [thr1, thr2], operation="union",
        )

        run = store.get_threshold_run(combined_id)
        assert run.method == "union"
        assert run.parameters["source_run_ids"] == [thr1, thr2]


# ---------------------------------------------------------------------------
# Delete Impact Tests
# ---------------------------------------------------------------------------


class TestDeleteImpact:
    """Tests for get_segmentation_run_impact and get_threshold_run_impact."""

    def test_segmentation_run_impact(self, tmp_path: Path) -> None:
        """Impact summary counts cells, measurements, particles, config entries."""
        store = _create_experiment(tmp_path)
        fov_id, seg_id, thr_id = _add_fov_with_seg_and_threshold(store)

        # Add measurements
        cells_df = store.get_cells(fov_id=fov_id)
        ch = store.get_channel("DAPI")
        measurements = [
            MeasurementRecord(
                cell_id=int(cid), channel_id=ch.id,
                metric="mean_intensity", value=100.0,
            )
            for cid in cells_df["id"]
        ]
        store.add_measurements(measurements)

        # Add config entry
        config_id = store.create_measurement_config("test_config")
        store.add_measurement_config_entry(config_id, fov_id, seg_id, thr_id)

        impact = store.get_segmentation_run_impact(seg_id)
        assert isinstance(impact, DeleteImpact)
        assert impact.cells == 2
        assert impact.measurements == 2
        assert impact.config_entries == 1

    def test_threshold_run_impact(self, tmp_path: Path) -> None:
        """Impact summary counts measurements, particles, config entries."""
        store = _create_experiment(tmp_path)
        fov_id, seg_id, thr_id = _add_fov_with_seg_and_threshold(store)

        # Add threshold-scoped measurements
        cells_df = store.get_cells(fov_id=fov_id)
        ch = store.get_channel("GFP")
        measurements = [
            MeasurementRecord(
                cell_id=int(cid), channel_id=ch.id,
                metric="mean_intensity", value=50.0,
                scope="mask_inside", threshold_run_id=thr_id,
            )
            for cid in cells_df["id"]
        ]
        store.add_measurements(measurements)

        # Add particles
        first_cell_id = int(cells_df["id"].iloc[0])
        particles = [
            ParticleRecord(
                cell_id=first_cell_id, threshold_run_id=thr_id,
                label_value=1, centroid_x=10.0, centroid_y=10.0,
                bbox_x=10, bbox_y=10, bbox_w=10, bbox_h=10,
                area_pixels=100.0, mean_intensity=200.0,
                max_intensity=200.0, integrated_intensity=20000.0,
            ),
        ]
        store.add_particles(particles)

        # Add config entry
        config_id = store.create_measurement_config("test_config")
        store.add_measurement_config_entry(config_id, fov_id, seg_id, thr_id)

        impact = store.get_threshold_run_impact(thr_id)
        assert isinstance(impact, DeleteImpact)
        assert impact.measurements == 2
        assert impact.particles == 1
        assert impact.config_entries == 1

    def test_empty_run_impact(self, tmp_path: Path) -> None:
        """Impact is all zeros for a fresh run with no data."""
        store = _create_experiment(tmp_path)
        fov_id = store.add_fov("control", width=20, height=20)
        seg_id = store.add_segmentation_run(
            fov_id=fov_id, channel="DAPI", model_name="mock",
        )

        impact = store.get_segmentation_run_impact(seg_id)
        assert impact.cells == 0
        assert impact.measurements == 0
        assert impact.particles == 0
        assert impact.config_entries == 0


# ---------------------------------------------------------------------------
# Export Measurements Tests
# ---------------------------------------------------------------------------


class TestExportMeasurements:
    """Tests for ExperimentStore.export_measurements()."""

    def _setup_measurable_experiment(
        self, tmp_path: Path,
    ) -> tuple[ExperimentStore, int]:
        """Create an experiment with measurements and a config."""
        store = _create_experiment(tmp_path, "export")
        fov_id, seg_id, thr_id = _add_fov_with_seg_and_threshold(store)

        # Add whole-cell measurements
        cells_df = store.get_cells(fov_id=fov_id)
        ch = store.get_channel("DAPI")
        wc_measurements = [
            MeasurementRecord(
                cell_id=int(cid), channel_id=ch.id,
                metric="mean_intensity", value=100.0 + i * 10,
            )
            for i, cid in enumerate(cells_df["id"])
        ]
        store.add_measurements(wc_measurements)

        # Add mask-scoped measurements
        ch_gfp = store.get_channel("GFP")
        mask_measurements = [
            MeasurementRecord(
                cell_id=int(cid), channel_id=ch_gfp.id,
                metric="mean_intensity", value=50.0 + i * 5,
                scope="mask_inside", threshold_run_id=thr_id,
            )
            for i, cid in enumerate(cells_df["id"])
        ]
        store.add_measurements(mask_measurements)

        # Create measurement config
        config_id = store.create_measurement_config("test_export")
        store.add_measurement_config_entry(config_id, fov_id, seg_id, thr_id)
        store.set_active_measurement_config(config_id)

        return store, config_id

    def test_directory_structure(self, tmp_path: Path) -> None:
        """Export creates expected directory tree."""
        store, config_id = self._setup_measurable_experiment(tmp_path)
        export_dir = tmp_path / "export_out"

        result = store.export_measurements(export_dir, config_id)
        assert result["files_written"] > 0

        # Should have segmentation run directory
        seg_dirs = [d for d in export_dir.iterdir() if d.is_dir() and d.name != "summary"]
        assert len(seg_dirs) >= 1

        # Should have summary directory
        summary_dir = export_dir / "summary"
        assert summary_dir.exists()
        assert (summary_dir / "segmentation_runs.csv").exists()
        assert (summary_dir / "threshold_runs.csv").exists()

    def test_whole_cell_csv_written(self, tmp_path: Path) -> None:
        """Whole-cell measurements CSV is written in seg run directory."""
        store, config_id = self._setup_measurable_experiment(tmp_path)
        export_dir = tmp_path / "export_out"

        store.export_measurements(export_dir, config_id)

        seg_dirs = [d for d in export_dir.iterdir() if d.is_dir() and d.name != "summary"]
        wc_csv = seg_dirs[0] / "whole_cell_measurements.csv"
        assert wc_csv.exists()

    def test_uses_active_config_when_none(self, tmp_path: Path) -> None:
        """If config_id is None, uses active config."""
        store, config_id = self._setup_measurable_experiment(tmp_path)
        export_dir = tmp_path / "export_out"

        result = store.export_measurements(export_dir)  # No config_id
        assert result["files_written"] > 0

    def test_empty_config_returns_zero(self, tmp_path: Path) -> None:
        """Returns 0 files if config has no entries."""
        store = _create_experiment(tmp_path, "empty")
        config_id = store.create_measurement_config("empty")
        export_dir = tmp_path / "export_out"

        result = store.export_measurements(export_dir, config_id)
        assert result["files_written"] == 0

    def test_unsafe_run_names_sanitized(self, tmp_path: Path) -> None:
        """Run names with special characters are sanitized for filesystem."""
        store = _create_experiment(tmp_path, "unsafe")
        fov_id = store.add_fov("control", width=20, height=20)

        # Create seg run with unsafe characters
        labels = np.zeros((20, 20), dtype=np.int32)
        labels[5:15, 5:15] = 1
        seg_id = store.add_segmentation_run(
            fov_id=fov_id, channel="DAPI", model_name="cyto3",
            name="run (v1.0)",  # parentheses and dots are allowed
        )
        store.write_labels(fov_id, labels, seg_id)

        from percell3.segment.label_processor import extract_cells

        cells = extract_cells(labels, fov_id, seg_id, 0.65)
        if cells:
            store.add_cells(cells)

        ch = store.get_channel("DAPI")
        cells_df = store.get_cells(fov_id=fov_id)
        store.add_measurements([
            MeasurementRecord(
                cell_id=int(cells_df["id"].iloc[0]),
                channel_id=ch.id, metric="mean_intensity", value=100.0,
            ),
        ])

        config_id = store.create_measurement_config("test")
        store.add_measurement_config_entry(config_id, fov_id, seg_id)
        store.set_active_measurement_config(config_id)

        export_dir = tmp_path / "export_out"
        result = store.export_measurements(export_dir, config_id)
        assert result["files_written"] > 0

        # The directory should exist and be readable
        seg_dirs = [d for d in export_dir.iterdir() if d.is_dir() and d.name != "summary"]
        assert len(seg_dirs) >= 1
