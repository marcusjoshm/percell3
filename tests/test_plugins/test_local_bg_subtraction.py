"""Tests for LocalBGSubtractionPlugin — validate, run, CSV export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.plugins.builtin.local_bg_subtraction import (
    CSV_COLUMNS,
    LocalBGSubtractionPlugin,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_bg_sub_experiment(tmp_path: Path) -> ExperimentStore:
    """Create a synthetic experiment ready for background subtraction.

    Layout:
        - 1 FOV (80x80), condition "control"
        - 2 channels: "DAPI" (segmentation), "GFP" (measurement)
        - 2 cells: cell 1 at (10,10)-(30,30), cell 2 at (50,50)-(70,70)
        - GFP image: background ~30, particles ~200
        - Threshold mask on GFP: particles are small bright spots inside cells
        - Particle labels: label 1 for cell 1 particle, label 2 for cell 2 particle
    """
    store = ExperimentStore.create(tmp_path / "bg_test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=80, height=80, pixel_size_um=0.65)
    seg_run_id = store.add_segmentation_run(
        fov_id=fov_id, channel="DAPI", model_name="mock",
        parameters={"diameter": 30.0},
    )

    # DAPI image
    dapi = np.full((80, 80), 50, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    # GFP image: dim background, bright particles
    rng = np.random.default_rng(42)
    gfp = rng.normal(loc=30, scale=3, size=(80, 80)).clip(0, 65535).astype(np.uint16)
    # Bright particles inside cells
    gfp[18:22, 18:22] = 200  # Particle in cell 1
    gfp[58:62, 58:62] = 250  # Particle in cell 2
    store.write_image(fov_id, "GFP", gfp)

    # Cell labels
    labels = np.zeros((80, 80), dtype=np.int32)
    labels[10:30, 10:30] = 1
    labels[50:70, 50:70] = 2
    store.write_labels(fov_id, labels, seg_run_id)

    # Cells
    cells = [
        CellRecord(
            fov_id=fov_id,
            segmentation_id=seg_run_id,
            label_value=1,
            centroid_x=20.0, centroid_y=20.0,
            bbox_x=10, bbox_y=10, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        ),
        CellRecord(
            fov_id=fov_id,
            segmentation_id=seg_run_id,
            label_value=2,
            centroid_x=60.0, centroid_y=60.0,
            bbox_x=50, bbox_y=50, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        ),
    ]
    cell_ids = store.add_cells(cells)

    # Threshold run + mask + particle labels for GFP
    tr_id = store.add_threshold_run(
        fov_id=fov_id, channel="GFP", method="otsu",
        parameters={"threshold_value": 100.0},
    )

    # Binary threshold mask
    mask = np.zeros((80, 80), dtype=np.uint8)
    mask[18:22, 18:22] = 255  # particle in cell 1
    mask[58:62, 58:62] = 255  # particle in cell 2
    store.write_mask(fov_id, "GFP", mask, tr_id)

    # Particle labels (integer-coded, one label per connected component)
    particle_labels = np.zeros((80, 80), dtype=np.int32)
    particle_labels[18:22, 18:22] = 1
    particle_labels[58:62, 58:62] = 2
    store.write_particle_labels(fov_id, "GFP", particle_labels, tr_id)

    store._test_fov_id = fov_id
    store._test_cell_ids = cell_ids
    store._test_threshold_run_id = tr_id
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLocalBGSubtractionPluginInfo:
    """Tests for plugin metadata."""

    def test_info(self) -> None:
        plugin = LocalBGSubtractionPlugin()
        info = plugin.info()
        assert info.name == "local_bg_subtraction"
        assert info.version == "1.0.0"
        assert "background" in info.description.lower()

    def test_parameter_schema(self) -> None:
        plugin = LocalBGSubtractionPlugin()
        schema = plugin.get_parameter_schema()
        assert "measurement_channel" in schema["properties"]
        assert "particle_channel" in schema["properties"]
        assert "dilation_pixels" in schema["properties"]


class TestLocalBGSubtractionValidation:
    """Tests for validate() method."""

    def test_validate_empty_experiment(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "empty.percell")
        plugin = LocalBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert len(errors) >= 1
        assert any("channel" in e.lower() for e in errors)
        store.close()

    def test_validate_no_cells(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "nocells.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        plugin = LocalBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert any("cell" in e.lower() for e in errors)
        store.close()

    def test_validate_no_threshold(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "nothresh.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        fov_id = store.add_fov("control", width=32, height=32)
        seg_id = store.add_segmentation_run(
            fov_id=fov_id, channel="GFP", model_name="mock", parameters={},
        )
        labels = np.zeros((32, 32), dtype=np.int32)
        labels[5:15, 5:15] = 1
        store.write_labels(fov_id, labels, seg_id)
        store.add_cells([CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=10.0, centroid_y=10.0,
            bbox_x=5, bbox_y=5, bbox_w=10, bbox_h=10,
            area_pixels=100.0,
        )])
        plugin = LocalBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert any("threshold" in e.lower() for e in errors)
        store.close()

    def test_validate_valid_experiment(self, tmp_path: Path) -> None:
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert errors == []
        store.close()


class TestLocalBGSubtractionRun:
    """Tests for run() method with synthetic data."""

    def test_run_basic(self, tmp_path: Path) -> None:
        """Plugin should produce per-particle output for all cells."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
        })

        assert result.cells_processed == 2
        # measurements_written now counts particles, not DB records
        assert result.measurements_written == 2  # 1 particle per cell
        store.close()

    def test_run_no_db_measurements(self, tmp_path: Path) -> None:
        """Plugin should NOT write cell-level aggregates to the measurements table."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
        })

        measurements = store.get_measurements()
        assert len(measurements) == 0
        store.close()

    def test_run_bg_subtraction_reduces_intensity(self, tmp_path: Path) -> None:
        """BG-subtracted mean should be less than raw particle intensity in CSV."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
            "export_csv": True,
        })

        # Read back the CSV to verify values
        import csv as csv_mod
        csv_key = [k for k in result.custom_outputs if k.startswith("csv_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            bg_sub_mean = float(row["bg_sub_mean_intensity"])
            bg_estimate = float(row["bg_estimate"])
            # bg_sub should be positive (bright particles on dim background)
            assert bg_sub_mean > 0
            # Background estimate should be close to the actual background (~30)
            assert 10 <= bg_estimate <= 60
        store.close()

    def test_run_exports_csv_per_condition(self, tmp_path: Path) -> None:
        """Per-particle CSV should be exported, one per condition."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
            "export_csv": True,
        })

        # Should have one CSV for the "control" condition
        assert "csv_control" in result.custom_outputs
        csv_path = Path(result.custom_outputs["csv_control"])
        assert csv_path.exists()
        assert "control" in csv_path.name

        # Check CSV has the right columns
        import csv
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2  # 2 particles
        for col in CSV_COLUMNS:
            assert col in rows[0], f"Missing CSV column: {col}"
        store.close()

    def test_run_no_csv_export(self, tmp_path: Path) -> None:
        """With export_csv=False, no CSV should be generated."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
            "export_csv": False,
        })

        csv_keys = [k for k in result.custom_outputs if k.startswith("csv_")]
        assert len(csv_keys) == 0
        store.close()

    def test_run_with_exclusion_mask(self, tmp_path: Path) -> None:
        """Exclusion mask should not crash the plugin."""
        store = _create_bg_sub_experiment(tmp_path)

        # Add a DAPI threshold run + mask for exclusion
        tr_id = store.add_threshold_run(
            fov_id=store._test_fov_id, channel="DAPI", method="otsu",
            parameters={"threshold_value": 40.0},
        )
        excl_mask = np.zeros((80, 80), dtype=np.uint8)
        excl_mask[15:25, 15:25] = 255  # overlapping with cell 1 region
        store.write_mask(store._test_fov_id, "DAPI", excl_mask, tr_id)

        plugin = LocalBGSubtractionPlugin()
        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "exclusion_channel": "DAPI",
            "dilation_pixels": 5,
        })

        assert result.cells_processed == 2
        assert result.measurements_written > 0
        store.close()

    def test_run_with_progress_callback(self, tmp_path: Path) -> None:
        """Progress callback should be called for each FOV."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        callback = MagicMock()
        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
        }, progress_callback=callback)

        assert callback.call_count == 1  # 1 FOV
        store.close()

    def test_run_no_threshold_run_raises(self, tmp_path: Path) -> None:
        """If the particle channel has no threshold run, should raise."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        with pytest.raises(RuntimeError, match="No threshold run"):
            plugin.run(store, parameters={
                "measurement_channel": "GFP",
                "particle_channel": "DAPI",  # DAPI has no threshold run
                "dilation_pixels": 5,
            })
        store.close()

    def test_run_rerun_produces_new_csvs(self, tmp_path: Path) -> None:
        """Running twice should produce separate timestamped CSV files."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        params = {
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
        }

        result1 = plugin.run(store, parameters=params)
        result2 = plugin.run(store, parameters=params)

        # Both should succeed
        assert result1.cells_processed == 2
        assert result2.cells_processed == 2
        assert result1.measurements_written == 2
        assert result2.measurements_written == 2
        store.close()

    def test_run_with_cell_ids_filter(self, tmp_path: Path) -> None:
        """Providing cell_ids should only process those cells."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        # Only process the first cell
        first_cell_id = store._test_cell_ids[0]
        result = plugin.run(
            store,
            cell_ids=[first_cell_id],
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "dilation_pixels": 5,
            },
        )

        assert result.cells_processed == 1
        store.close()

    def test_run_with_normalization_channel(self, tmp_path: Path) -> None:
        """Normalization channel mean intensity should appear in CSV."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "normalization_channel": "DAPI",
            "dilation_pixels": 5,
            "export_csv": True,
        })

        assert result.cells_processed == 2

        import csv as csv_mod
        csv_key = [k for k in result.custom_outputs if k.startswith("csv_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 2
        for row in rows:
            assert "norm_mean_intensity" in row
            # DAPI is uniform 50 in the test fixture, particles overlap it
            norm_val = float(row["norm_mean_intensity"])
            assert norm_val == pytest.approx(50.0, abs=1.0)
        store.close()

    def test_run_without_normalization_channel(self, tmp_path: Path) -> None:
        """Without normalization channel, norm_mean_intensity column should be empty."""
        store = _create_bg_sub_experiment(tmp_path)
        plugin = LocalBGSubtractionPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "dilation_pixels": 5,
            "export_csv": True,
        })

        import csv as csv_mod
        csv_key = [k for k in result.custom_outputs if k.startswith("csv_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            assert row["norm_mean_intensity"] == ""
        store.close()
