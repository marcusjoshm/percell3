"""Integration tests for BG subtraction — full pipeline through PluginRegistry."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.plugins.registry import PluginRegistry


def _build_synthetic_experiment(tmp_path: Path) -> ExperimentStore:
    """Create a full experiment with known BG and particle intensities.

    Background: ~40, particles: ~300
    2 FOVs, 2 channels (DAPI seg, GFP measurement), 2 cells per FOV.
    GFP is thresholded with particles at known locations.
    """
    store = ExperimentStore.create(tmp_path / "integration.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    seg_run_id = store.add_segmentation_run("DAPI", "mock", {"diameter": 30.0})
    tr_id = store.add_threshold_run("GFP", "otsu", {"threshold_value": 150.0})

    rng = np.random.default_rng(123)

    fov_ids = []
    all_cell_ids = []
    for _ in range(2):
        fov_id = store.add_fov("control", width=100, height=100, pixel_size_um=0.65)
        fov_ids.append(fov_id)

        # DAPI — uniform
        dapi = np.full((100, 100), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        # GFP — background ~40, particles ~300
        gfp = rng.normal(loc=40, scale=5, size=(100, 100)).clip(0, 65535).astype(np.uint16)
        # Particle in cell 1 (pixel region 15:25, 15:25 inside cell bbox 5:35, 5:35)
        gfp[15:25, 15:25] = rng.normal(loc=300, scale=10, size=(10, 10)).clip(0, 65535).astype(np.uint16)
        # Particle in cell 2 (pixel region 65:75, 65:75 inside cell bbox 55:85, 55:85)
        gfp[65:75, 65:75] = rng.normal(loc=300, scale=10, size=(10, 10)).clip(0, 65535).astype(np.uint16)
        store.write_image(fov_id, "GFP", gfp)

        # Cell labels
        labels = np.zeros((100, 100), dtype=np.int32)
        labels[5:35, 5:35] = 1
        labels[55:85, 55:85] = 2
        store.write_labels(fov_id, labels, seg_run_id)

        # Cells
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_run_id, label_value=1,
                centroid_x=20.0, centroid_y=20.0,
                bbox_x=5, bbox_y=5, bbox_w=30, bbox_h=30,
                area_pixels=900.0,
            ),
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_run_id, label_value=2,
                centroid_x=70.0, centroid_y=70.0,
                bbox_x=55, bbox_y=55, bbox_w=30, bbox_h=30,
                area_pixels=900.0,
            ),
        ]
        cell_ids = store.add_cells(cells)
        all_cell_ids.extend(cell_ids)

        # Threshold mask
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[15:25, 15:25] = 255
        mask[65:75, 65:75] = 255
        store.write_mask(fov_id, "GFP", mask, tr_id)

        # Particle labels
        particle_labels = np.zeros((100, 100), dtype=np.int32)
        particle_labels[15:25, 15:25] = 1
        particle_labels[65:75, 65:75] = 2
        store.write_particle_labels(fov_id, "GFP", particle_labels)

    store._test_fov_ids = fov_ids
    store._test_cell_ids = all_cell_ids
    return store


class TestBGSubtractionIntegration:
    """Full pipeline: registry → discover → run plugin → check results."""

    def test_registry_discovers_plugin(self) -> None:
        registry = PluginRegistry()
        registry.discover()
        names = [p.name for p in registry.list_plugins()]
        assert "local_bg_subtraction" in names

    def test_full_pipeline(self, tmp_path: Path) -> None:
        """Run BG subtraction via PluginRegistry and verify per-particle output."""
        store = _build_synthetic_experiment(tmp_path)
        registry = PluginRegistry()
        registry.discover()

        result = registry.run_plugin(
            "local_bg_subtraction", store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "dilation_pixels": 5,
            },
        )

        # All 4 cells processed (2 FOVs x 2 cells)
        assert result.cells_processed == 4
        # 4 particles total (1 per cell)
        assert result.measurements_written == 4

        # No cell-level DB measurements written
        measurements = store.get_measurements()
        assert len(measurements) == 0

        # Per-condition CSV should be exported (all FOVs are "control")
        assert "csv_control" in result.custom_outputs
        csv_path = Path(result.custom_outputs["csv_control"])
        assert csv_path.exists()

        # Read CSV and verify per-particle values
        import csv
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 4  # 4 particles total

        for row in rows:
            bg_estimate = float(row["bg_estimate"])
            bg_sub_mean = float(row["bg_sub_mean_intensity"])
            # BG estimate should be close to 40 (the true background)
            assert 20 <= bg_estimate <= 70, f"BG estimate {bg_estimate} out of range"
            # BG-subtracted mean should be > 50 (particles ~300, bg ~40)
            assert bg_sub_mean > 50, f"BG-sub mean {bg_sub_mean} too low"

        store.close()

    def test_with_exclusion_mask(self, tmp_path: Path) -> None:
        """Exclusion mask should work through the full pipeline."""
        store = _build_synthetic_experiment(tmp_path)

        # Add DAPI threshold with exclusion mask
        tr_dapi = store.add_threshold_run("DAPI", "otsu", {"threshold_value": 45.0})
        for fov_id in store._test_fov_ids:
            excl_mask = np.zeros((100, 100), dtype=np.uint8)
            excl_mask[10:20, 10:20] = 255  # overlaps with cell 1 particle region
            store.write_mask(fov_id, "DAPI", excl_mask, tr_dapi)

        registry = PluginRegistry()
        registry.discover()

        result = registry.run_plugin(
            "local_bg_subtraction", store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "exclusion_channel": "DAPI",
                "dilation_pixels": 5,
            },
        )

        assert result.cells_processed == 4
        assert result.measurements_written > 0
        store.close()

    def test_no_particles_graceful(self, tmp_path: Path) -> None:
        """FOV with no particles in label image should be handled gracefully."""
        store = ExperimentStore.create(tmp_path / "empty_particles.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        seg_id = store.add_segmentation_run("DAPI", "mock", {})
        tr_id = store.add_threshold_run("GFP", "otsu", {})

        fov_id = store.add_fov("control", width=50, height=50)

        # Images
        store.write_image(fov_id, "DAPI", np.full((50, 50), 50, dtype=np.uint16))
        store.write_image(fov_id, "GFP", np.full((50, 50), 30, dtype=np.uint16))

        # Labels + cell
        labels = np.zeros((50, 50), dtype=np.int32)
        labels[10:30, 10:30] = 1
        store.write_labels(fov_id, labels, seg_id)
        store.add_cells([CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=20.0, centroid_y=20.0,
            bbox_x=10, bbox_y=10, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        )])

        # Empty threshold mask and particle labels (no particles)
        store.write_mask(fov_id, "GFP", np.zeros((50, 50), dtype=np.uint8), tr_id)
        store.write_particle_labels(fov_id, "GFP", np.zeros((50, 50), dtype=np.int32))

        registry = PluginRegistry()
        registry.discover()

        result = registry.run_plugin(
            "local_bg_subtraction", store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "dilation_pixels": 5,
            },
        )

        # Cell has no particles → not processed, warning issued
        assert result.cells_processed == 0
        assert len(result.warnings) > 0
        store.close()

    def test_analysis_run_tracked(self, tmp_path: Path) -> None:
        """Plugin run should create an analysis_run record in the database."""
        store = _build_synthetic_experiment(tmp_path)
        registry = PluginRegistry()
        registry.discover()

        runs_before = store.get_analysis_runs()

        registry.run_plugin(
            "local_bg_subtraction", store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "dilation_pixels": 5,
            },
        )

        runs_after = store.get_analysis_runs()
        assert len(runs_after) == len(runs_before) + 1

        latest_run = runs_after[-1]
        assert latest_run["plugin_name"] == "local_bg_subtraction"
        assert latest_run["status"] == "completed"
        store.close()
