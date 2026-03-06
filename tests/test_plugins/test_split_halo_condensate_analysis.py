"""Tests for SplitHaloCondensateAnalysisPlugin."""

from __future__ import annotations

import csv as csv_mod
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.plugins.builtin.split_halo_condensate_analysis import (
    DILUTE_CSV_COLUMNS,
    GRANULE_CSV_COLUMNS,
    SplitHaloCondensateAnalysisPlugin,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_condensate_experiment(tmp_path: Path) -> ExperimentStore:
    """Create a synthetic experiment for condensate analysis testing.

    Layout:
        - 1 FOV (80x80), condition "control"
        - 2 channels: "DAPI" (segmentation), "GFP" (measurement)
        - 2 cells: cell 1 at (10,10)-(30,30), cell 2 at (50,50)-(70,70)
        - GFP image: background ~30, particles ~200
        - Threshold mask + particle labels on GFP
        - Particle 1 (4x4 at 18:22,18:22) in cell 1
        - Particle 2 (4x4 at 58:62,58:62) in cell 2
    """
    store = ExperimentStore.create(tmp_path / "condensate_test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=80, height=80, pixel_size_um=0.65)
    seg_run_id = store.add_segmentation(
        name="seg_test", seg_type="cellular", width=80, height=80,
        source_fov_id=fov_id, source_channel="DAPI", model_name="mock",
        parameters={"diameter": 30.0},
    )

    # DAPI image — uniform
    dapi = np.full((80, 80), 50, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    # GFP image — dim background with bright particles
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
    tr_id = store.add_threshold(
        name="thresh_test", method="otsu", width=80, height=80,
        source_fov_id=fov_id, source_channel="GFP",
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
    return store


# ---------------------------------------------------------------------------
# Tests: Plugin Info
# ---------------------------------------------------------------------------


class TestPluginInfo:
    def test_info(self) -> None:
        plugin = SplitHaloCondensateAnalysisPlugin()
        info = plugin.info()
        assert info.name == "split_halo_condensate_analysis"
        assert info.version == "1.0.0"
        assert "condensate" in info.description.lower()

    def test_parameter_schema(self) -> None:
        plugin = SplitHaloCondensateAnalysisPlugin()
        schema = plugin.get_parameter_schema()
        assert "measurement_channel" in schema["properties"]
        assert "particle_channel" in schema["properties"]
        assert "ring_dilation_pixels" in schema["properties"]
        assert "exclusion_dilation_pixels" in schema["properties"]
        assert "save_images" in schema["properties"]


# ---------------------------------------------------------------------------
# Tests: Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_validate_empty_experiment(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "empty.percell")
        plugin = SplitHaloCondensateAnalysisPlugin()
        errors = plugin.validate(store)
        assert len(errors) >= 1
        assert any("channel" in e.lower() for e in errors)
        store.close()

    def test_validate_no_cells(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "nocells.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        plugin = SplitHaloCondensateAnalysisPlugin()
        errors = plugin.validate(store)
        assert any("cell" in e.lower() for e in errors)
        store.close()

    def test_validate_no_threshold(self, tmp_path: Path) -> None:
        store = ExperimentStore.create(tmp_path / "nothresh.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        fov_id = store.add_fov("control", width=32, height=32)
        seg_id = store.add_segmentation(
            name="seg_nothresh", seg_type="cellular", width=32, height=32,
            source_fov_id=fov_id, source_channel="GFP", model_name="mock",
            parameters={},
        )
        labels = np.zeros((32, 32), dtype=np.int32)
        labels[5:15, 5:15] = 1
        store.write_labels(labels, seg_id)
        store.add_cells([CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=10.0, centroid_y=10.0,
            bbox_x=5, bbox_y=5, bbox_w=10, bbox_h=10,
            area_pixels=100.0,
        )])
        plugin = SplitHaloCondensateAnalysisPlugin()
        errors = plugin.validate(store)
        assert any("threshold" in e.lower() for e in errors)
        store.close()

    def test_validate_valid_experiment(self, tmp_path: Path) -> None:
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()
        errors = plugin.validate(store)
        assert errors == []
        store.close()


# ---------------------------------------------------------------------------
# Tests: Granule Measurement
# ---------------------------------------------------------------------------


class TestGranuleMeasurement:
    def test_granule_particles_processed(self, tmp_path: Path) -> None:
        """Plugin should produce per-particle granule output."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "save_images": False,
        })

        # 2 particles (1 per cell)
        assert result.measurements_written == 2
        store.close()

    def test_granule_bg_subtraction(self, tmp_path: Path) -> None:
        """BG-subtracted mean should be less than raw particle intensity."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_granule_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            bg_sub_mean = float(row["bg_sub_mean_intensity"])
            bg_estimate = float(row["bg_estimate"])
            assert bg_sub_mean > 0
            assert 10 <= bg_estimate <= 60
        store.close()

    def test_no_threshold_run_raises(self, tmp_path: Path) -> None:
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        with pytest.raises(RuntimeError, match="No threshold run"):
            plugin.run(store, parameters={
                "measurement_channel": "GFP",
                "particle_channel": "DAPI",
            })
        store.close()


# ---------------------------------------------------------------------------
# Tests: Dilute Phase
# ---------------------------------------------------------------------------


class TestDilutePhase:
    def test_dilute_measurement_produced(self, tmp_path: Path) -> None:
        """Dilute CSV should have one row per cell."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_dilute_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        # 2 cells, each should have a dilute measurement
        assert len(rows) == 2
        for col in DILUTE_CSV_COLUMNS:
            assert col in rows[0], f"Missing dilute CSV column: {col}"
        store.close()

    def test_dilute_bg_estimation(self, tmp_path: Path) -> None:
        """Dilute phase should have a background estimate from the dilute region."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_dilute_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            bg_estimate = float(row["bg_estimate"])
            raw_mean = float(row["raw_mean_intensity"])
            # Background should be near ~30 (the dim GFP background)
            assert 10 <= bg_estimate <= 60
            # Raw mean should also be near ~30 (dilute region is the dim background)
            assert 10 <= raw_mean <= 60
        store.close()

    def test_dilute_area_excludes_particles(self, tmp_path: Path) -> None:
        """Dilute area should be smaller than total cell area (particles excluded)."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "exclusion_dilation_pixels": 3,
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_dilute_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        for row in rows:
            dilute_area = int(row["dilute_area_pixels"])
            # Cell is 20x20 = 400 pixels, particle is 4x4 = 16, dilated particle is bigger
            # Dilute area should be less than 400
            assert dilute_area < 400
            assert dilute_area > 0
        store.close()


# ---------------------------------------------------------------------------
# Tests: Derived FOV Creation
# ---------------------------------------------------------------------------


class TestDerivedFOVCreation:
    def test_derived_fovs_created(self, tmp_path: Path) -> None:
        """Should create condensed_phase and dilute_phase FOVs."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "save_images": True,
            "export_csv": False,
        })

        fovs = store.get_fovs()
        fov_names = [f.display_name for f in fovs]
        condensed_fovs = [n for n in fov_names if n.startswith("condensed_phase_")]
        dilute_fovs = [n for n in fov_names if n.startswith("dilute_phase_")]

        assert len(condensed_fovs) == 1
        assert len(dilute_fovs) == 1
        store.close()

    def test_derived_fovs_have_correct_metadata(self, tmp_path: Path) -> None:
        """Derived FOVs should inherit condition, bio_rep, dimensions from source."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "save_images": True,
            "export_csv": False,
        })

        fovs = store.get_fovs()
        source_fov = next(f for f in fovs if not f.display_name.startswith(("condensed_", "dilute_")))
        condensed_fov = next(f for f in fovs if f.display_name.startswith("condensed_phase_"))

        assert condensed_fov.condition == source_fov.condition
        assert condensed_fov.bio_rep == source_fov.bio_rep
        assert condensed_fov.width == source_fov.width
        assert condensed_fov.height == source_fov.height
        assert condensed_fov.pixel_size_um == source_fov.pixel_size_um
        store.close()

    def test_condensed_fov_only_has_particle_pixels(self, tmp_path: Path) -> None:
        """Condensed phase image should have nonzero pixels only where particles are."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "save_images": True,
            "export_csv": False,
        })

        fovs = store.get_fovs()
        condensed_fov = next(f for f in fovs if f.display_name.startswith("condensed_phase_"))

        gfp_image = store.read_image_numpy(condensed_fov.id, "GFP")

        # Particle 1 at (18:22, 18:22), particle 2 at (58:62, 58:62)
        # These pixels should be nonzero
        assert np.any(gfp_image[18:22, 18:22] > 0)
        assert np.any(gfp_image[58:62, 58:62] > 0)

        # Pixels outside particles and cells should be zero
        assert gfp_image[0, 0] == 0
        assert gfp_image[40, 40] == 0
        store.close()

    def test_dilute_fov_excludes_particles(self, tmp_path: Path) -> None:
        """Dilute phase image should have zero pixels inside particle region."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "exclusion_dilation_pixels": 2,
            "save_images": True,
            "export_csv": False,
        })

        fovs = store.get_fovs()
        dilute_fov = next(f for f in fovs if f.display_name.startswith("dilute_phase_"))

        gfp_image = store.read_image_numpy(dilute_fov.id, "GFP")

        # Particle centers should be zero (excluded)
        assert gfp_image[19, 19] == 0
        assert gfp_image[59, 59] == 0

        # Cell corners (far from particles) should have background signal
        assert gfp_image[10, 10] > 0  # cell 1 corner
        assert gfp_image[50, 50] > 0  # cell 2 corner
        store.close()

    def test_all_channels_in_derived_fovs(self, tmp_path: Path) -> None:
        """Derived FOVs should contain all channels from the original."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "save_images": True,
            "export_csv": False,
        })

        fovs = store.get_fovs()
        condensed_fov = next(f for f in fovs if f.display_name.startswith("condensed_phase_"))

        # Should be able to read both DAPI and GFP from derived FOV
        dapi_image = store.read_image_numpy(condensed_fov.id, "DAPI")
        gfp_image = store.read_image_numpy(condensed_fov.id, "GFP")
        assert dapi_image.shape == (80, 80)
        assert gfp_image.shape == (80, 80)
        store.close()

    def test_rerun_overwrites_existing_derived_fovs(self, tmp_path: Path) -> None:
        """Running twice should overwrite existing derived FOVs, not duplicate."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        params = {
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "save_images": True,
            "export_csv": False,
        }

        plugin.run(store, parameters=params)
        result2 = plugin.run(store, parameters=params)

        fovs = store.get_fovs()
        condensed_fovs = [f for f in fovs if f.display_name.startswith("condensed_phase_")]
        assert len(condensed_fovs) == 1  # Not duplicated

        # Should complete without "already exists" warnings
        assert not any("already exists" in w for w in result2.warnings)
        store.close()

    def test_save_images_false_skips_fov_creation(self, tmp_path: Path) -> None:
        """With save_images=False, no derived FOVs should be created."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "save_images": False,
            "export_csv": False,
        })

        fovs = store.get_fovs()
        assert len(fovs) == 1  # Only the original FOV
        store.close()


# ---------------------------------------------------------------------------
# Tests: CSV Export
# ---------------------------------------------------------------------------


class TestCSVExport:
    def test_granule_csv_columns(self, tmp_path: Path) -> None:
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_granule_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 2
        for col in GRANULE_CSV_COLUMNS:
            assert col in rows[0], f"Missing granule CSV column: {col}"
        store.close()

    def test_dilute_csv_columns(self, tmp_path: Path) -> None:
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_dilute_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 2  # 1 per cell
        for col in DILUTE_CSV_COLUMNS:
            assert col in rows[0], f"Missing dilute CSV column: {col}"
        store.close()

    def test_no_csv_export(self, tmp_path: Path) -> None:
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": False,
            "save_images": False,
        })

        csv_keys = [k for k in result.custom_outputs if k.startswith("csv_")]
        assert len(csv_keys) == 0
        store.close()

    def test_normalization_channel_in_granule_csv(self, tmp_path: Path) -> None:
        """When normalization_channel is set, norm_mean_intensity should have values."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "normalization_channel": "GFP",  # use same channel for simplicity
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_granule_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) > 0
        for row in rows:
            assert "norm_mean_intensity" in row
            assert row["norm_mean_intensity"] != ""
            assert float(row["norm_mean_intensity"]) > 0
        store.close()

    def test_normalization_channel_in_dilute_csv(self, tmp_path: Path) -> None:
        """When normalization_channel is set, dilute CSV should have norm values."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "normalization_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        csv_key = [k for k in result.custom_outputs if k.startswith("csv_dilute_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) > 0
        for row in rows:
            assert "norm_mean_intensity" in row
            assert row["norm_mean_intensity"] != ""
            assert float(row["norm_mean_intensity"]) > 0
        store.close()

    def test_csv_written_to_exports_dir(self, tmp_path: Path) -> None:
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        for key, path_str in result.custom_outputs.items():
            if key.startswith("csv_"):
                csv_path = Path(path_str)
                assert csv_path.exists()
                assert "exports" in str(csv_path)
                assert "condensate" in csv_path.name
        store.close()


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_cell_with_no_particles(self, tmp_path: Path) -> None:
        """Cell with no particles should still produce dilute measurement."""
        store = ExperimentStore.create(tmp_path / "no_particles.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=40, height=40, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_nopart", seg_type="cellular", width=40, height=40,
            source_fov_id=fov_id, source_channel="DAPI", model_name="mock",
            parameters={},
        )

        dapi = np.full((40, 40), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        gfp = np.full((40, 40), 30, dtype=np.uint16)
        store.write_image(fov_id, "GFP", gfp)

        labels = np.zeros((40, 40), dtype=np.int32)
        labels[5:35, 5:35] = 1
        store.write_labels(labels, seg_run_id)

        store.add_cells([CellRecord(
            fov_id=fov_id, segmentation_id=seg_run_id, label_value=1,
            centroid_x=20.0, centroid_y=20.0,
            bbox_x=5, bbox_y=5, bbox_w=30, bbox_h=30,
            area_pixels=900.0,
        )])

        tr_id = store.add_threshold(
            name="thresh_nopart", method="otsu", width=40, height=40,
            source_fov_id=fov_id, source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )
        mask = np.zeros((40, 40), dtype=np.uint8)
        store.write_mask(mask, tr_id)
        particle_labels = np.zeros((40, 40), dtype=np.int32)
        store.write_particle_labels(particle_labels, tr_id)

        plugin = SplitHaloCondensateAnalysisPlugin()
        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        # No granule particles, but dilute measurement should exist
        assert result.measurements_written == 0

        # Check dilute CSV was exported
        dilute_keys = [k for k in result.custom_outputs if k.startswith("csv_dilute_")]
        assert len(dilute_keys) == 1
        csv_path = Path(result.custom_outputs[dilute_keys[0]])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))
        assert len(rows) == 1  # 1 cell, no particles means whole cell is dilute
        store.close()

    def test_progress_callback(self, tmp_path: Path) -> None:
        """Progress callback should be called for each FOV."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        callback = MagicMock()
        plugin.run(
            store,
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "save_images": False,
            },
            progress_callback=callback,
        )

        assert callback.call_count == 1  # 1 FOV
        store.close()

    def test_cell_ids_filter(self, tmp_path: Path) -> None:
        """Providing cell_ids should only process those cells."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        first_cell_id = store._test_cell_ids[0]
        result = plugin.run(
            store,
            cell_ids=[first_cell_id],
            parameters={
                "measurement_channel": "GFP",
                "particle_channel": "GFP",
                "save_images": False,
                "export_csv": True,
            },
        )

        # Only 1 particle from 1 cell
        assert result.measurements_written == 1

        # Dilute CSV should have 1 row
        dilute_keys = [k for k in result.custom_outputs if k.startswith("csv_dilute_")]
        assert len(dilute_keys) == 1
        csv_path = Path(result.custom_outputs[dilute_keys[0]])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))
        assert len(rows) == 1
        store.close()


# ---------------------------------------------------------------------------
# Tests: Multi-threshold support
# ---------------------------------------------------------------------------


class TestMultiThreshold:
    def test_multiple_thresholds_combined(self, tmp_path: Path) -> None:
        """When a FOV has multiple thresholds (grouped thresholding), they are merged."""
        store = ExperimentStore.create(tmp_path / "multi_thresh.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=80, height=80, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_multi", seg_type="cellular", width=80, height=80,
            source_fov_id=fov_id, source_channel="DAPI", model_name="mock",
            parameters={"diameter": 30.0},
        )

        # DAPI image
        dapi = np.full((80, 80), 50, dtype=np.uint16)
        store.write_image(fov_id, "DAPI", dapi)

        # GFP image with two different particle regions
        rng = np.random.default_rng(42)
        gfp = rng.normal(loc=30, scale=3, size=(80, 80)).clip(0, 65535).astype(np.uint16)
        gfp[18:22, 18:22] = 200  # Particle in cell 1 (g1 group)
        gfp[58:62, 58:62] = 250  # Particle in cell 2 (g2 group)
        store.write_image(fov_id, "GFP", gfp)

        # Cell labels
        labels = np.zeros((80, 80), dtype=np.int32)
        labels[10:30, 10:30] = 1
        labels[50:70, 50:70] = 2
        store.write_labels(labels, seg_run_id)

        # Two cells
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_run_id, label_value=1,
                centroid_x=20.0, centroid_y=20.0,
                bbox_x=10, bbox_y=10, bbox_w=20, bbox_h=20, area_pixels=400.0,
            ),
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_run_id, label_value=2,
                centroid_x=60.0, centroid_y=60.0,
                bbox_x=50, bbox_y=50, bbox_w=20, bbox_h=20, area_pixels=400.0,
            ),
        ]
        store.add_cells(cells)

        # Threshold g1: particle only in cell 1 (non-overlapping group)
        tr_id1 = store.add_threshold(
            name="g1_mNG", method="otsu", width=80, height=80,
            source_fov_id=fov_id, source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )
        mask1 = np.zeros((80, 80), dtype=np.uint8)
        mask1[18:22, 18:22] = 255
        store.write_mask(mask1, tr_id1)
        plabels1 = np.zeros((80, 80), dtype=np.int32)
        plabels1[18:22, 18:22] = 1
        store.write_particle_labels(plabels1, tr_id1)

        # Threshold g2: particle only in cell 2 (non-overlapping group)
        tr_id2 = store.add_threshold(
            name="g2_mNG", method="otsu", width=80, height=80,
            source_fov_id=fov_id, source_channel="GFP",
            parameters={"threshold_value": 150.0},
        )
        mask2 = np.zeros((80, 80), dtype=np.uint8)
        mask2[58:62, 58:62] = 255
        store.write_mask(mask2, tr_id2)
        plabels2 = np.zeros((80, 80), dtype=np.int32)
        plabels2[58:62, 58:62] = 1
        store.write_particle_labels(plabels2, tr_id2)

        # add_threshold with source_fov_id auto-configures the config matrix,
        # so both thresholds already have entries in fov_config.

        plugin = SplitHaloCondensateAnalysisPlugin()
        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": True,
        })

        # Both thresholds merged: 1 particle from g1 + 1 particle from g2 = 2 total
        assert result.measurements_written == 2

        # Check granule CSV has threshold_name with combined name
        csv_key = [k for k in result.custom_outputs if k.startswith("csv_granule_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))

        assert len(rows) == 2
        assert "threshold_name" in rows[0]
        # Combined threshold name joins loaded names
        assert rows[0]["threshold_name"] == "g1_mNG+g2_mNG"

        # Check dilute CSV: 2 cells, 1 measurement per cell (combined)
        dilute_key = [k for k in result.custom_outputs if k.startswith("csv_dilute_")][0]
        dilute_path = Path(result.custom_outputs[dilute_key])
        with open(dilute_path) as f:
            dilute_rows = list(csv_mod.DictReader(f))

        assert len(dilute_rows) == 2
        assert "threshold_name" in dilute_rows[0]

        # Check derived FOVs: 1 condensed + 1 dilute (combined)
        fovs = store.get_fovs()
        fov_names = [f.display_name for f in fovs]
        condensed_fovs = [n for n in fov_names if n.startswith("condensed_phase_")]
        dilute_fovs = [n for n in fov_names if n.startswith("dilute_phase_")]
        assert len(condensed_fovs) == 1
        assert len(dilute_fovs) == 1

        store.close()

    def test_threshold_with_missing_particle_labels_skipped(self, tmp_path: Path) -> None:
        """Thresholds without particle labels are silently skipped during merge."""
        store = ExperimentStore.create(tmp_path / "partial_thresh.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=80, height=80, pixel_size_um=0.65)
        seg_run_id = store.add_segmentation(
            name="seg_partial", seg_type="cellular", width=80, height=80,
            source_fov_id=fov_id, source_channel="DAPI", model_name="mock",
            parameters={"diameter": 30.0},
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

        store.add_cells([CellRecord(
            fov_id=fov_id, segmentation_id=seg_run_id, label_value=1,
            centroid_x=20.0, centroid_y=20.0,
            bbox_x=10, bbox_y=10, bbox_w=20, bbox_h=20, area_pixels=400.0,
        )])

        # Threshold g1: has mask but NO particle labels (simulates missing zarr data)
        tr_id1 = store.add_threshold(
            name="g1_mNG", method="otsu", width=80, height=80,
            source_fov_id=fov_id, source_channel="GFP",
            parameters={"threshold_value": 100.0},
        )
        mask1 = np.zeros((80, 80), dtype=np.uint8)
        mask1[18:22, 18:22] = 255
        store.write_mask(mask1, tr_id1)
        # Intentionally no write_particle_labels for g1

        # Threshold g2: has particle labels
        tr_id2 = store.add_threshold(
            name="g2_mNG", method="otsu", width=80, height=80,
            source_fov_id=fov_id, source_channel="GFP",
            parameters={"threshold_value": 150.0},
        )
        mask2 = np.zeros((80, 80), dtype=np.uint8)
        mask2[18:22, 18:22] = 255
        store.write_mask(mask2, tr_id2)
        plabels2 = np.zeros((80, 80), dtype=np.int32)
        plabels2[18:22, 18:22] = 1
        store.write_particle_labels(plabels2, tr_id2)

        plugin = SplitHaloCondensateAnalysisPlugin()
        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        # g1 skipped (no particle labels), g2 contributes 1 particle
        assert result.measurements_written == 1
        # No warnings about skipped FOV — only g1 has no particle labels
        assert not any("Skipped FOV" in w for w in result.warnings)

        # CSV threshold_name should only reference g2
        csv_key = [k for k in result.custom_outputs if k.startswith("csv_granule_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))
        assert rows[0]["threshold_name"] == "g2_mNG"

        store.close()

    def test_threshold_name_in_csv_columns(self, tmp_path: Path) -> None:
        """threshold_name should appear in both GRANULE and DILUTE CSV columns."""
        assert "threshold_name" in GRANULE_CSV_COLUMNS
        assert "threshold_name" in DILUTE_CSV_COLUMNS
        # Should be right after fov_name
        g_idx = GRANULE_CSV_COLUMNS.index("fov_name")
        assert GRANULE_CSV_COLUMNS[g_idx + 1] == "threshold_name"
        d_idx = DILUTE_CSV_COLUMNS.index("fov_name")
        assert DILUTE_CSV_COLUMNS[d_idx + 1] == "threshold_name"

    def test_fallback_without_config_entries(self, tmp_path: Path) -> None:
        """Experiments without config entries should still work via source_fov_id fallback."""
        store = _create_condensate_experiment(tmp_path)
        plugin = SplitHaloCondensateAnalysisPlugin()

        result = plugin.run(store, parameters={
            "measurement_channel": "GFP",
            "particle_channel": "GFP",
            "export_csv": True,
            "save_images": False,
        })

        # Should still process 2 particles via fallback
        assert result.measurements_written == 2

        # CSV should have threshold_name column with fallback threshold name
        csv_key = [k for k in result.custom_outputs if k.startswith("csv_granule_")][0]
        csv_path = Path(result.custom_outputs[csv_key])
        with open(csv_path) as f:
            rows = list(csv_mod.DictReader(f))
        assert "threshold_name" in rows[0]
        assert rows[0]["threshold_name"] == "thresh_test"
        store.close()


# ---------------------------------------------------------------------------
# Tests: Colormap expansion
# ---------------------------------------------------------------------------


class TestColormapExpansion:
    def test_colormaps_include_new_entries(self) -> None:
        from percell3.segment.viewer.surface_plot_widget import _COLORMAPS

        expected_new = ["nipy_spectral", "Spectral", "rainbow", "coolwarm", "gnuplot", "jet", "cividis"]
        for cmap in expected_new:
            assert cmap in _COLORMAPS, f"Missing colormap: {cmap}"
