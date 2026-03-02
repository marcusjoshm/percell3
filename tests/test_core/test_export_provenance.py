"""Tests for Phase 8: Export with Config Provenance."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from percell3.core.experiment_store import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord, ParticleRecord
from percell3.segment.label_processor import extract_cells


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def provenance_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with config entries for provenance testing.

    Creates:
      - 2 channels (DAPI, GFP)
      - 1 condition (ctrl)
      - 1 FOV (64x64) with auto-created whole_field seg + config entry
      - 1 cellular segmentation with 2 cells
      - Measurements for both cells
    """
    store = ExperimentStore.create(tmp_path / "prov.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("ctrl")

    # Write FOV images
    fov_id = store.add_fov("ctrl", width=64, height=64, pixel_size_um=0.65,
                           display_name="fov_001")
    img = np.full((64, 64), 100, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", img)
    store.write_image(fov_id, "GFP", img)

    # Create cellular segmentation with labels
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[5:25, 5:25] = 1   # cell 1: 20x20
    labels[30:50, 30:50] = 2  # cell 2: 20x20

    seg_id = store.add_segmentation(
        "cellpose_DAPI_1", "cellular", 64, 64,
        source_fov_id=fov_id, source_channel="DAPI",
        model_name="cyto3", parameters={},
    )
    store.write_labels(labels, seg_id)

    cells = extract_cells(labels, fov_id, seg_id, 0.65)
    store.add_cells(cells)
    store.update_segmentation_cell_count(seg_id, len(cells))

    # Add measurements
    ch_gfp = store.get_channel("GFP")
    cells_df = store.get_cells(fov_id=fov_id)
    measurements = [
        MeasurementRecord(
            cell_id=cid, channel_id=ch_gfp.id,
            metric="mean_intensity", value=100.0 + i * 50,
            segmentation_id=seg_id,
        )
        for i, cid in enumerate(cells_df["id"].tolist())
    ]
    store.add_measurements(measurements)

    store._test_fov_id = fov_id
    store._test_seg_id = seg_id
    yield store
    store.close()


@pytest.fixture
def provenance_experiment_with_threshold(
    provenance_experiment: ExperimentStore,
) -> ExperimentStore:
    """Extend provenance_experiment with a threshold and particles."""
    store = provenance_experiment
    fov_id = store._test_fov_id
    seg_id = store._test_seg_id

    # Create threshold
    thr_id = store.add_threshold(
        "thresh_GFP_1", "manual", 64, 64,
        source_fov_id=fov_id, source_channel="GFP",
        parameters={"value": 50.0},
    )

    # Write mask
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[5:25, 5:25] = 255  # overlaps cell 1
    store.write_mask(mask, thr_id)

    # Add particles
    particles = [
        ParticleRecord(
            fov_id=fov_id, threshold_id=thr_id,
            label_value=1,
            centroid_x=15.0, centroid_y=15.0,
            bbox_x=5, bbox_y=5, bbox_w=20, bbox_h=20,
            area_pixels=400.0, area_um2=400.0 * 0.65 * 0.65,
            mean_intensity=120.0, max_intensity=150.0,
            integrated_intensity=48000.0,
        ),
    ]
    store.add_particles(particles)

    # Add mask-scoped measurements
    ch_gfp = store.get_channel("GFP")
    cells_df = store.get_cells(fov_id=fov_id)
    mask_ms = [
        MeasurementRecord(
            cell_id=cid, channel_id=ch_gfp.id,
            metric="mean_intensity", value=50.0 + i * 25,
            scope="mask_inside", segmentation_id=seg_id,
            threshold_id=thr_id,
        )
        for i, cid in enumerate(cells_df["id"].tolist())
    ]
    store.add_measurements(mask_ms)

    store._test_thr_id = thr_id
    return store


# ── Provenance Header Tests ───────────────────────────────────────────

class TestConfigProvenance:
    """Tests for _get_config_provenance()."""

    def test_provenance_includes_config_id(
        self, provenance_experiment: ExperimentStore,
    ):
        lines = provenance_experiment._get_config_provenance()
        assert any("analysis_config_id:" in line for line in lines)

    def test_provenance_includes_fov_and_seg(
        self, provenance_experiment: ExperimentStore,
    ):
        lines = provenance_experiment._get_config_provenance()
        text = "\n".join(lines)
        assert "fov_001" in text
        # Should reference at least the cellular segmentation
        assert "cellpose_DAPI_1" in text

    def test_provenance_includes_threshold(
        self, provenance_experiment_with_threshold: ExperimentStore,
    ):
        lines = provenance_experiment_with_threshold._get_config_provenance()
        text = "\n".join(lines)
        assert "thresh_GFP_1" in text

    def test_provenance_empty_config(self, tmp_path: Path):
        """Experiment with no config entries returns empty marker."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("ctrl")
        lines = store._get_config_provenance()
        assert any("(empty)" in line for line in lines)
        store.close()

    def test_provenance_includes_scopes(
        self, provenance_experiment_with_threshold: ExperimentStore,
    ):
        lines = provenance_experiment_with_threshold._get_config_provenance()
        text = "\n".join(lines)
        assert "scopes=" in text


# ── export_csv Provenance Tests ───────────────────────────────────────

class TestExportCsvProvenance:
    """Tests for export_csv() with provenance headers."""

    def test_csv_has_comment_header(
        self, provenance_experiment: ExperimentStore, tmp_path: Path,
    ):
        csv_path = tmp_path / "out.csv"
        provenance_experiment.export_csv(csv_path)

        text = csv_path.read_text()
        lines = text.splitlines()
        # First line(s) should be comment lines
        assert lines[0].startswith("#")

    def test_csv_readable_with_comment_skip(
        self, provenance_experiment: ExperimentStore, tmp_path: Path,
    ):
        csv_path = tmp_path / "out.csv"
        provenance_experiment.export_csv(csv_path)
        df = pd.read_csv(csv_path, comment="#")
        assert not df.empty
        assert "cell_id" in df.columns

    def test_csv_provenance_disabled(
        self, provenance_experiment: ExperimentStore, tmp_path: Path,
    ):
        csv_path = tmp_path / "out.csv"
        provenance_experiment.export_csv(csv_path, include_provenance=False)

        text = csv_path.read_text()
        # Should not start with comment
        assert not text.startswith("#")

    def test_csv_provenance_contains_seg_name(
        self, provenance_experiment: ExperimentStore, tmp_path: Path,
    ):
        csv_path = tmp_path / "out.csv"
        provenance_experiment.export_csv(csv_path)

        text = csv_path.read_text()
        comment_lines = [l for l in text.splitlines() if l.startswith("#")]
        comment_text = "\n".join(comment_lines)
        assert "cellpose_DAPI_1" in comment_text

    def test_csv_data_correct_after_provenance(
        self, provenance_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Data rows should be intact despite provenance header."""
        csv_path = tmp_path / "out.csv"
        provenance_experiment.export_csv(csv_path)
        df = pd.read_csv(csv_path, comment="#")
        assert len(df) == 2  # 2 cells
        assert "GFP_mean_intensity" in df.columns


# ── export_particles_csv Tests ────────────────────────────────────────

class TestExportParticlesCsv:
    """Tests for export_particles_csv()."""

    def test_particles_csv_basic(
        self, provenance_experiment_with_threshold: ExperimentStore,
        tmp_path: Path,
    ):
        store = provenance_experiment_with_threshold
        csv_path = tmp_path / "particles.csv"
        store.export_particles_csv(csv_path)

        df = pd.read_csv(csv_path, comment="#")
        assert len(df) == 1  # 1 particle
        assert "fov_name" in df.columns
        assert "threshold_name" in df.columns
        assert "area_pixels" in df.columns

    def test_particles_csv_has_provenance(
        self, provenance_experiment_with_threshold: ExperimentStore,
        tmp_path: Path,
    ):
        store = provenance_experiment_with_threshold
        csv_path = tmp_path / "particles.csv"
        store.export_particles_csv(csv_path)

        text = csv_path.read_text()
        assert text.startswith("#")

    def test_particles_csv_no_provenance(
        self, provenance_experiment_with_threshold: ExperimentStore,
        tmp_path: Path,
    ):
        store = provenance_experiment_with_threshold
        csv_path = tmp_path / "particles.csv"
        store.export_particles_csv(csv_path, include_provenance=False)

        text = csv_path.read_text()
        assert not text.startswith("#")

    def test_particles_csv_threshold_name_column(
        self, provenance_experiment_with_threshold: ExperimentStore,
        tmp_path: Path,
    ):
        store = provenance_experiment_with_threshold
        csv_path = tmp_path / "particles.csv"
        store.export_particles_csv(csv_path)

        df = pd.read_csv(csv_path, comment="#")
        assert df.iloc[0]["threshold_name"] == "thresh_GFP_1"

    def test_particles_csv_empty_experiment(self, tmp_path: Path):
        """No particles produces a file with just provenance."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("ctrl")

        csv_path = tmp_path / "particles.csv"
        store.export_particles_csv(csv_path)

        text = csv_path.read_text()
        # Should have provenance comments but no data
        assert text.startswith("#")
        store.close()

    def test_particles_csv_context_columns(
        self, provenance_experiment_with_threshold: ExperimentStore,
        tmp_path: Path,
    ):
        store = provenance_experiment_with_threshold
        csv_path = tmp_path / "particles.csv"
        store.export_particles_csv(csv_path)

        df = pd.read_csv(csv_path, comment="#")
        assert "condition_name" in df.columns
        assert "bio_rep_name" in df.columns
        assert "fov_name" in df.columns
        assert df.iloc[0]["condition_name"] == "ctrl"

    def test_particles_csv_geometry_columns(
        self, provenance_experiment_with_threshold: ExperimentStore,
        tmp_path: Path,
    ):
        store = provenance_experiment_with_threshold
        csv_path = tmp_path / "particles.csv"
        store.export_particles_csv(csv_path)

        df = pd.read_csv(csv_path, comment="#")
        # Geometry columns should be present
        for col in ["centroid_x", "centroid_y", "area_pixels", "area_um2"]:
            assert col in df.columns
        assert df.iloc[0]["area_pixels"] == pytest.approx(400.0)
