"""Tests for CondensatePartitioningRatioPlugin."""

from __future__ import annotations

import csv as csv_mod
import math
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.plugins.builtin.condensate_partitioning_ratio import (
    PARTITION_CSV_COLUMNS,
    CondensatePartitioningRatioPlugin,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_partitioning_experiment(tmp_path: Path) -> ExperimentStore:
    """Create a synthetic experiment for partitioning ratio testing.

    Layout:
        - 1 FOV (80x80), condition "control"
        - 2 channels: "DAPI" (segmentation), "GFP" (measurement)
        - 2 cells: cell 1 at (10,10)-(30,30), cell 2 at (50,50)-(70,70)
        - GFP image: background ~30, particle 1 (4x4 at 18:22,18:22) = 200,
          particle 2 (4x4 at 58:62,58:62) = 250
        - Threshold mask + particle labels on GFP
    """
    store = ExperimentStore.create(tmp_path / "partitioning_test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=80, height=80, pixel_size_um=0.65)
    seg_run_id = store.add_segmentation(
        name="seg_test",
        seg_type="cellular",
        width=80,
        height=80,
        source_fov_id=fov_id,
        source_channel="DAPI",
        model_name="mock",
        parameters={"diameter": 30.0},
    )

    # DAPI image -- uniform
    dapi = np.full((80, 80), 50, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    # GFP image -- dim background with bright particles
    rng = np.random.default_rng(42)
    gfp = rng.normal(loc=30, scale=3, size=(80, 80)).clip(0, 65535).astype(np.uint16)
    gfp[18:22, 18:22] = 200  # Particle in cell 1
    gfp[58:62, 58:62] = 250  # Particle in cell 2
    store.write_image(fov_id, "GFP", gfp)

    # Cell labels
    labels = np.zeros((80, 80), dtype=np.int32)
    labels[10:30, 10:30] = 1
    labels[50:70, 50:70] = 2
    store.write_labels(labels, seg_run_id)

    # Cells
    cells = [
        CellRecord(
            fov_id=fov_id,
            segmentation_id=seg_run_id,
            label_value=1,
            centroid_x=20.0,
            centroid_y=20.0,
            bbox_x=10,
            bbox_y=10,
            bbox_w=20,
            bbox_h=20,
            area_pixels=400.0,
        ),
        CellRecord(
            fov_id=fov_id,
            segmentation_id=seg_run_id,
            label_value=2,
            centroid_x=60.0,
            centroid_y=60.0,
            bbox_x=50,
            bbox_y=50,
            bbox_w=20,
            bbox_h=20,
            area_pixels=400.0,
        ),
    ]
    cell_ids = store.add_cells(cells)

    # Threshold run + mask + particle labels for GFP
    tr_id = store.add_threshold(
        name="thresh_test",
        method="otsu",
        width=80,
        height=80,
        source_fov_id=fov_id,
        source_channel="GFP",
        parameters={"threshold_value": 100.0},
    )

    mask = np.zeros((80, 80), dtype=np.uint8)
    mask[18:22, 18:22] = 255
    mask[58:62, 58:62] = 255
    store.write_mask(mask, tr_id)

    particle_labels = np.zeros((80, 80), dtype=np.int32)
    particle_labels[18:22, 18:22] = 1
    particle_labels[58:62, 58:62] = 2
    store.write_particle_labels(particle_labels, tr_id)

    store._test_fov_id = fov_id
    store._test_cell_ids = cell_ids
    store._test_threshold_id = tr_id
    store._test_seg_id = seg_run_id
    return store


# ---------------------------------------------------------------------------
# Tests: Plugin Info
# ---------------------------------------------------------------------------


class TestPluginInfo:
    def test_info_name(self) -> None:
        plugin = CondensatePartitioningRatioPlugin()
        assert plugin.info().name == "condensate_partitioning_ratio"

    def test_parameter_schema(self) -> None:
        plugin = CondensatePartitioningRatioPlugin()
        schema = plugin.get_parameter_schema()
        assert "measurement_channel" in schema["properties"]
        assert "particle_channel" in schema["properties"]
        assert "measurement_channel" in schema["required"]
        assert "particle_channel" in schema["required"]


# ---------------------------------------------------------------------------
# Tests: Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_experiment(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "empty.percell")
        plugin = CondensatePartitioningRatioPlugin()
        errors = plugin.validate(store)
        assert len(errors) >= 1
        assert any("channel" in e.lower() for e in errors)
        store.close()

    def test_no_cells(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "nocells.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        plugin = CondensatePartitioningRatioPlugin()
        errors = plugin.validate(store)
        assert any("cell" in e.lower() for e in errors)
        store.close()

    def test_no_thresholds(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "nothresh.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        fov_id = store.add_fov("control", width=32, height=32)
        seg_id = store.add_segmentation(
            name="seg_nothresh",
            seg_type="cellular",
            width=32,
            height=32,
            source_fov_id=fov_id,
            source_channel="GFP",
            model_name="mock",
            parameters={},
        )
        labels = np.zeros((32, 32), dtype=np.int32)
        labels[5:15, 5:15] = 1
        store.write_labels(labels, seg_id)
        store.add_cells(
            [
                CellRecord(
                    fov_id=fov_id,
                    segmentation_id=seg_id,
                    label_value=1,
                    centroid_x=10.0,
                    centroid_y=10.0,
                    bbox_x=5,
                    bbox_y=5,
                    bbox_w=10,
                    bbox_h=10,
                    area_pixels=100.0,
                )
            ]
        )
        plugin = CondensatePartitioningRatioPlugin()
        errors = plugin.validate(store)
        assert any("threshold" in e.lower() for e in errors)
        store.close()

    def test_valid_experiment(self, tmp_path: Path) -> None:
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()
        errors = plugin.validate(store)
        assert errors == []
        store.close()


# ---------------------------------------------------------------------------
# Tests: Partitioning Measurement
# ---------------------------------------------------------------------------


class TestPartitioningMeasurement:
    def test_basic_ratio(self, tmp_path: Path) -> None:
        """Bright particles on dim background should give ratio > 1.0."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        assert result.measurements_written == 2

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 2
        for row in rows:
            ratio = float(row["partitioning_ratio"])
            assert ratio > 1.0, "Bright particle on dim background should give ratio > 1"
        store.close()

    def test_condensate_area(self, tmp_path: Path) -> None:
        """Condensate area should match known particle size (4x4 = 16 pixels)."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            area = int(row["condensate_area_pixels"])
            assert area == 16, f"Expected 4x4=16 pixel area, got {area}"
        store.close()

    def test_dilute_ring_area(self, tmp_path: Path) -> None:
        """Dilute ring area should be positive and reasonable."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            dilute_area = int(row["dilute_area_pixels"])
            assert dilute_area > 0
            # Ring around a 4x4 particle with gap=3, ring=2 should be moderate
            # but not enormous; must be smaller than the cell (20x20=400)
            assert dilute_area < 400
        store.close()

    def test_ratio_value_range(self, tmp_path: Path) -> None:
        """With particle=200 and background~30, ratio should be roughly 200/30 ~ 6-7."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            ratio = float(row["partitioning_ratio"])
            # Particles are 200 or 250, background ~30
            # Ratio should be between 3 and 15 (generous range for noisy bg)
            assert 3.0 < ratio < 15.0, f"Ratio {ratio} outside expected range"
        store.close()


# ---------------------------------------------------------------------------
# Tests: Ring Construction
# ---------------------------------------------------------------------------


class TestRingConstruction:
    def test_other_particles_excluded_from_ring(self, tmp_path: Path) -> None:
        """Adjacent particles' condensate pixels should be excluded from ring."""
        store = ExperimentStore.create(tmp_path / "adjacent.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        # One large cell with two adjacent particles
        fov_id = store.add_fov("control", width=60, height=60, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_adj",
            seg_type="cellular",
            width=60,
            height=60,
            source_fov_id=fov_id,
            source_channel="DAPI",
            model_name="mock",
            parameters={},
        )

        dapi = np.full((60, 60), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        gfp = np.full((60, 60), 30, dtype=np.uint16)
        gfp[20:24, 20:24] = 200  # Particle A
        gfp[20:24, 28:32] = 200  # Particle B, 4 pixels away from A
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((60, 60), dtype=np.int32)
        labels[5:55, 5:55] = 1
        store.write_labels(labels, seg_run_id)

        store.add_cells(
            [
                CellRecord(
                    fov_id=fov_id,
                    segmentation_id=seg_run_id,
                    label_value=1,
                    centroid_x=30.0,
                    centroid_y=30.0,
                    bbox_x=5,
                    bbox_y=5,
                    bbox_w=50,
                    bbox_h=50,
                    area_pixels=2500.0,
                )
            ]
        )

        tr_id = store.add_threshold(
            name="thresh_adj",
            method="otsu",
            width=60,
            height=60,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )

        mask = np.zeros((60, 60), dtype=np.uint8)
        mask[20:24, 20:24] = 255
        mask[20:24, 28:32] = 255
        store.write_mask(mask, tr_id)

        particle_labels = np.zeros((60, 60), dtype=np.int32)
        particle_labels[20:24, 20:24] = 1
        particle_labels[20:24, 28:32] = 2
        store.write_particle_labels(particle_labels, tr_id)

        plugin = CondensatePartitioningRatioPlugin()
        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
                "gap_pixels": 1,
                "ring_pixels": 2,
            },
        )

        # Both particles should be measured
        assert result.measurements_written == 2

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        # The dilute ring for each particle should NOT include the other
        # particle's bright pixels, so dilute_mean should be near background (~30)
        for row in rows:
            dilute_mean = float(row["dilute_mean_intensity"])
            # Should be close to background (30), not pulled up by other particle (200)
            assert dilute_mean < 100, (
                f"Dilute mean {dilute_mean} too high; other particle likely not excluded"
            )
        store.close()

    def test_ring_clipped_to_cell_mask(self, tmp_path: Path) -> None:
        """Particle near cell edge: ring should not extend outside cell."""
        store = ExperimentStore.create(tmp_path / "edge_particle.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=40, height=40, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_edge",
            seg_type="cellular",
            width=40,
            height=40,
            source_fov_id=fov_id,
            source_channel="DAPI",
            model_name="mock",
            parameters={},
        )

        dapi = np.full((40, 40), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        # Background = 30 inside cell, 500 outside (to detect leakage)
        gfp = np.full((40, 40), 500, dtype=np.uint16)
        gfp[5:15, 5:15] = 30  # Inside cell is dim
        gfp[5:9, 5:9] = 200  # Particle at corner of cell
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((40, 40), dtype=np.int32)
        labels[5:15, 5:15] = 1  # 10x10 cell
        store.write_labels(labels, seg_run_id)

        store.add_cells(
            [
                CellRecord(
                    fov_id=fov_id,
                    segmentation_id=seg_run_id,
                    label_value=1,
                    centroid_x=10.0,
                    centroid_y=10.0,
                    bbox_x=5,
                    bbox_y=5,
                    bbox_w=10,
                    bbox_h=10,
                    area_pixels=100.0,
                )
            ]
        )

        tr_id = store.add_threshold(
            name="thresh_edge",
            method="otsu",
            width=40,
            height=40,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )

        mask = np.zeros((40, 40), dtype=np.uint8)
        mask[5:9, 5:9] = 255
        store.write_mask(mask, tr_id)

        particle_labels = np.zeros((40, 40), dtype=np.int32)
        particle_labels[5:9, 5:9] = 1
        store.write_particle_labels(particle_labels, tr_id)

        plugin = CondensatePartitioningRatioPlugin()
        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
                "gap_pixels": 1,
                "ring_pixels": 2,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 1
        # If ring leaked outside cell (where intensity=500), dilute_mean would be high
        dilute_mean = float(rows[0]["dilute_mean_intensity"])
        assert dilute_mean < 100, (
            f"Dilute mean {dilute_mean} suggests ring leaked outside cell boundary"
        )
        store.close()

    def test_min_ring_pixels_nan(self, tmp_path: Path) -> None:
        """Setting min_ring_pixels very high should produce NaN ratio."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
                "min_ring_pixels": 99999,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            ratio = float(row["partitioning_ratio"])
            assert math.isnan(ratio), "Expected NaN ratio when min_ring_pixels is very high"
        store.close()

    def test_zero_dilute_intensity_nan(self, tmp_path: Path) -> None:
        """When all ring pixels are zero, ratio should be NaN."""
        store = ExperimentStore.create(tmp_path / "zero_dilute.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=40, height=40, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_zero",
            seg_type="cellular",
            width=40,
            height=40,
            source_fov_id=fov_id,
            source_channel="DAPI",
            model_name="mock",
            parameters={},
        )

        dapi = np.full((40, 40), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        # GFP: all zeros except particle
        gfp = np.zeros((40, 40), dtype=np.uint16)
        gfp[15:19, 15:19] = 200  # Particle
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((40, 40), dtype=np.int32)
        labels[5:35, 5:35] = 1
        store.write_labels(labels, seg_run_id)

        store.add_cells(
            [
                CellRecord(
                    fov_id=fov_id,
                    segmentation_id=seg_run_id,
                    label_value=1,
                    centroid_x=20.0,
                    centroid_y=20.0,
                    bbox_x=5,
                    bbox_y=5,
                    bbox_w=30,
                    bbox_h=30,
                    area_pixels=900.0,
                )
            ]
        )

        tr_id = store.add_threshold(
            name="thresh_zero",
            method="otsu",
            width=40,
            height=40,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )

        mask = np.zeros((40, 40), dtype=np.uint8)
        mask[15:19, 15:19] = 255
        store.write_mask(mask, tr_id)

        particle_labels = np.zeros((40, 40), dtype=np.int32)
        particle_labels[15:19, 15:19] = 1
        store.write_particle_labels(particle_labels, tr_id)

        plugin = CondensatePartitioningRatioPlugin()
        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
                "min_ring_pixels": 0,  # Don't skip due to area
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 1
        ratio = float(rows[0]["partitioning_ratio"])
        assert math.isnan(ratio), "Expected NaN ratio when dilute intensity is zero"
        store.close()


# ---------------------------------------------------------------------------
# Tests: CSV Export
# ---------------------------------------------------------------------------


class TestCSVExport:
    def test_csv_columns(self, tmp_path: Path) -> None:
        """All PARTITION_CSV_COLUMNS should appear in CSV output."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) > 0
        for col in PARTITION_CSV_COLUMNS:
            assert col in rows[0], f"Missing CSV column: {col}"
        store.close()

    def test_csv_file_exists(self, tmp_path: Path) -> None:
        """CSV file should exist in exports/ directory."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        for key, path_str in result.custom_outputs.items():
            if key.startswith("csv_"):
                csv_path = Path(path_str)
                assert csv_path.exists()
                assert "exports" in str(csv_path)
        store.close()

    def test_csv_content(self, tmp_path: Path) -> None:
        """CSV rows should have expected metadata values."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 2
        for row in rows:
            assert row["condition"] == "control"
            assert row["fov_name"] != ""
            assert int(row["cell_id"]) > 0
            assert int(row["fov_id"]) > 0
        store.close()

    def test_no_export_when_disabled(self, tmp_path: Path) -> None:
        """export_csv=False should produce no CSV in custom_outputs."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": False,
            },
        )

        csv_keys = [k for k in result.custom_outputs if k.startswith("csv_")]
        assert len(csv_keys) == 0
        store.close()


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_particles_in_cell(self, tmp_path: Path) -> None:
        """Cell with no particles should produce no rows for that cell."""
        store = ExperimentStore.create(tmp_path / "no_particles.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=40, height=40, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_nopart",
            seg_type="cellular",
            width=40,
            height=40,
            source_fov_id=fov_id,
            source_channel="DAPI",
            model_name="mock",
            parameters={},
        )

        dapi = np.full((40, 40), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        gfp = np.full((40, 40), 30, dtype=np.uint16)
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((40, 40), dtype=np.int32)
        labels[5:35, 5:35] = 1
        store.write_labels(labels, seg_run_id)

        store.add_cells(
            [
                CellRecord(
                    fov_id=fov_id,
                    segmentation_id=seg_run_id,
                    label_value=1,
                    centroid_x=20.0,
                    centroid_y=20.0,
                    bbox_x=5,
                    bbox_y=5,
                    bbox_w=30,
                    bbox_h=30,
                    area_pixels=900.0,
                )
            ]
        )

        tr_id = store.add_threshold(
            name="thresh_nopart",
            method="otsu",
            width=40,
            height=40,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )
        mask = np.zeros((40, 40), dtype=np.uint8)
        store.write_mask(mask, tr_id)
        particle_labels = np.zeros((40, 40), dtype=np.int32)
        store.write_particle_labels(particle_labels, tr_id)

        plugin = CondensatePartitioningRatioPlugin()
        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        assert result.measurements_written == 0
        store.close()

    def test_progress_callback(self, tmp_path: Path) -> None:
        """Progress callback should be called for each FOV."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        callback = MagicMock()
        plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
            },
            progress_callback=callback,
        )

        assert callback.call_count == 1  # 1 FOV
        store.close()

    def test_cell_ids_filter(self, tmp_path: Path) -> None:
        """Providing cell_ids should only process those cells."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        first_cell_id = store._test_cell_ids[0]
        result = plugin.run(
            store,
            cell_ids=[first_cell_id],
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        # Only 1 particle from 1 cell
        assert result.measurements_written == 1

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))
        assert len(rows) == 1
        store.close()

    def test_pixel_size_none_area_um2_nan(self, tmp_path: Path) -> None:
        """FOV without pixel_size_um should produce NaN for area_um2 columns."""
        store = ExperimentStore.create(tmp_path / "no_pixelsize.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        # Create FOV without pixel_size_um
        fov_id = store.add_fov("control", width=80, height=80)
        seg_run_id = store.add_segmentation(
            name="seg_nopx",
            seg_type="cellular",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="DAPI",
            model_name="mock",
            parameters={},
        )

        dapi = np.full((80, 80), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        rng = np.random.default_rng(42)
        gfp = rng.normal(loc=30, scale=3, size=(80, 80)).clip(0, 65535).astype(np.uint16)
        gfp[18:22, 18:22] = 200
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((80, 80), dtype=np.int32)
        labels[10:30, 10:30] = 1
        store.write_labels(labels, seg_run_id)

        store.add_cells(
            [
                CellRecord(
                    fov_id=fov_id,
                    segmentation_id=seg_run_id,
                    label_value=1,
                    centroid_x=20.0,
                    centroid_y=20.0,
                    bbox_x=10,
                    bbox_y=10,
                    bbox_w=20,
                    bbox_h=20,
                    area_pixels=400.0,
                )
            ]
        )

        tr_id = store.add_threshold(
            name="thresh_nopx",
            method="otsu",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )

        mask = np.zeros((80, 80), dtype=np.uint8)
        mask[18:22, 18:22] = 255
        store.write_mask(mask, tr_id)

        particle_labels = np.zeros((80, 80), dtype=np.int32)
        particle_labels[18:22, 18:22] = 1
        store.write_particle_labels(particle_labels, tr_id)

        plugin = CondensatePartitioningRatioPlugin()
        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 1
        assert math.isnan(float(rows[0]["condensate_area_um2"]))
        assert math.isnan(float(rows[0]["dilute_area_um2"]))
        store.close()

    def test_nan_count_warning(self, tmp_path: Path) -> None:
        """Setting min_ring_pixels very high should produce a NaN warning."""
        store = _create_partitioning_experiment(tmp_path)
        plugin = CondensatePartitioningRatioPlugin()

        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "min_ring_pixels": 99999,
                "export_csv": True,
            },
        )

        assert any("NaN" in w for w in result.warnings)
        store.close()


# ---------------------------------------------------------------------------
# Tests: Multi-threshold support
# ---------------------------------------------------------------------------


class TestMultiThreshold:
    def test_merged_particle_labels(self, tmp_path: Path) -> None:
        """Two thresholds should produce renumbered labels and measure both particles."""
        store = ExperimentStore.create(tmp_path / "multi_thresh.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=80, height=80, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_multi",
            seg_type="cellular",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="DAPI",
            model_name="mock",
            parameters={"diameter": 30.0},
        )

        dapi = np.full((80, 80), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        rng = np.random.default_rng(42)
        gfp = rng.normal(loc=30, scale=3, size=(80, 80)).clip(0, 65535).astype(np.uint16)
        gfp[18:22, 18:22] = 200  # Particle in cell 1 (g1 group)
        gfp[58:62, 58:62] = 250  # Particle in cell 2 (g2 group)
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((80, 80), dtype=np.int32)
        labels[10:30, 10:30] = 1
        labels[50:70, 50:70] = 2
        store.write_labels(labels, seg_run_id)

        cells = [
            CellRecord(
                fov_id=fov_id,
                segmentation_id=seg_run_id,
                label_value=1,
                centroid_x=20.0,
                centroid_y=20.0,
                bbox_x=10,
                bbox_y=10,
                bbox_w=20,
                bbox_h=20,
                area_pixels=400.0,
            ),
            CellRecord(
                fov_id=fov_id,
                segmentation_id=seg_run_id,
                label_value=2,
                centroid_x=60.0,
                centroid_y=60.0,
                bbox_x=50,
                bbox_y=50,
                bbox_w=20,
                bbox_h=20,
                area_pixels=400.0,
            ),
        ]
        store.add_cells(cells)

        # Threshold g1: particle only in cell 1
        tr_id1 = store.add_threshold(
            name="g1_mNG",
            method="otsu",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )
        mask1 = np.zeros((80, 80), dtype=np.uint8)
        mask1[18:22, 18:22] = 255
        store.write_mask(mask1, tr_id1)
        plabels1 = np.zeros((80, 80), dtype=np.int32)
        plabels1[18:22, 18:22] = 1
        store.write_particle_labels(plabels1, tr_id1)

        # Threshold g2: particle only in cell 2
        tr_id2 = store.add_threshold(
            name="g2_mNG",
            method="otsu",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 150.0},
        )
        mask2 = np.zeros((80, 80), dtype=np.uint8)
        mask2[58:62, 58:62] = 255
        store.write_mask(mask2, tr_id2)
        plabels2 = np.zeros((80, 80), dtype=np.int32)
        plabels2[58:62, 58:62] = 1
        store.write_particle_labels(plabels2, tr_id2)

        plugin = CondensatePartitioningRatioPlugin()
        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        # Both thresholds merged: 1 particle from g1 + 1 particle from g2 = 2 total
        assert result.measurements_written == 2
        store.close()

    def test_threshold_name_in_csv(self, tmp_path: Path) -> None:
        """Combined threshold name should appear in CSV threshold_name column."""
        store = ExperimentStore.create(tmp_path / "multi_name.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=80, height=80, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_multi_name",
            seg_type="cellular",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="DAPI",
            model_name="mock",
            parameters={"diameter": 30.0},
        )

        dapi = np.full((80, 80), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        rng = np.random.default_rng(42)
        gfp = rng.normal(loc=30, scale=3, size=(80, 80)).clip(0, 65535).astype(np.uint16)
        gfp[18:22, 18:22] = 200
        gfp[58:62, 58:62] = 250
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((80, 80), dtype=np.int32)
        labels[10:30, 10:30] = 1
        labels[50:70, 50:70] = 2
        store.write_labels(labels, seg_run_id)

        cells = [
            CellRecord(
                fov_id=fov_id,
                segmentation_id=seg_run_id,
                label_value=1,
                centroid_x=20.0,
                centroid_y=20.0,
                bbox_x=10,
                bbox_y=10,
                bbox_w=20,
                bbox_h=20,
                area_pixels=400.0,
            ),
            CellRecord(
                fov_id=fov_id,
                segmentation_id=seg_run_id,
                label_value=2,
                centroid_x=60.0,
                centroid_y=60.0,
                bbox_x=50,
                bbox_y=50,
                bbox_w=20,
                bbox_h=20,
                area_pixels=400.0,
            ),
        ]
        store.add_cells(cells)

        tr_id1 = store.add_threshold(
            name="alpha_thresh",
            method="otsu",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )
        mask1 = np.zeros((80, 80), dtype=np.uint8)
        mask1[18:22, 18:22] = 255
        store.write_mask(mask1, tr_id1)
        plabels1 = np.zeros((80, 80), dtype=np.int32)
        plabels1[18:22, 18:22] = 1
        store.write_particle_labels(plabels1, tr_id1)

        tr_id2 = store.add_threshold(
            name="beta_thresh",
            method="otsu",
            width=80,
            height=80,
            source_fov_id=fov_id,
            source_channel="GFP",
            parameters={"threshold_value": 150.0},
        )
        mask2 = np.zeros((80, 80), dtype=np.uint8)
        mask2[58:62, 58:62] = 255
        store.write_mask(mask2, tr_id2)
        plabels2 = np.zeros((80, 80), dtype=np.int32)
        plabels2[58:62, 58:62] = 1
        store.write_particle_labels(plabels2, tr_id2)

        plugin = CondensatePartitioningRatioPlugin()
        result = plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "export_csv": True,
            },
        )

        csv_key = [
            k for k in result.custom_outputs if k.startswith("csv_partitioning_")
        ][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 2
        assert "threshold_name" in rows[0]
        # Combined threshold name joins loaded names
        assert rows[0]["threshold_name"] == "alpha_thresh+beta_thresh"
        store.close()
