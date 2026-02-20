"""Shared fixtures for CLI module tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile
from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord, ParticleRecord


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def experiment(tmp_path: Path) -> ExperimentStore:
    """Create a fresh experiment for CLI testing."""
    store = ExperimentStore.create(tmp_path / "test.percell", name="Test")
    yield store
    store.close()


@pytest.fixture
def experiment_path(experiment: ExperimentStore) -> Path:
    """Path to the test experiment."""
    return experiment.path


@pytest.fixture
def experiment_with_data(experiment: ExperimentStore) -> ExperimentStore:
    """Experiment with channels, conditions, FOVs, and images."""
    experiment.add_channel("DAPI", role="nuclear")
    experiment.add_channel("GFP")
    experiment.add_condition("control")
    data = np.zeros((64, 64), dtype=np.uint16)
    experiment.add_fov(
        "fov1", "control", width=64, height=64, pixel_size_um=0.65,
    )
    experiment.write_image("fov1", "control", "DAPI", data)
    experiment.write_image("fov1", "control", "GFP", data)
    return experiment


@pytest.fixture
def experiment_with_particles(experiment_with_data: ExperimentStore) -> ExperimentStore:
    """Experiment with channels, conditions, FOVs, images, cells, and particles."""
    store = experiment_with_data

    # Add segmentation run and cells
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")
    fovs = store.get_fovs(condition="control")
    fov_id = fovs[0].id

    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=i,
            centroid_x=10.0 + i * 10, centroid_y=20.0 + i * 10,
            bbox_x=5 + i * 10, bbox_y=15 + i * 10, bbox_w=15, bbox_h=15,
            area_pixels=200.0,
        )
        for i in range(1, 4)
    ]
    cell_ids = store.add_cells(cells)

    # Add measurements so cell CSV export has content
    ch_info = store.get_channel("GFP")
    measurements = [
        MeasurementRecord(
            cell_id=cid, channel_id=ch_info.id,
            metric="mean_intensity", value=100.0 + i * 10,
        )
        for i, cid in enumerate(cell_ids)
    ]
    store.add_measurements(measurements)

    # Add threshold run and particles
    thr_id = store.add_threshold_run(channel="GFP", method="otsu")

    particles = [
        ParticleRecord(
            cell_id=cell_ids[0], threshold_run_id=thr_id, label_value=1,
            centroid_x=12.0, centroid_y=22.0,
            bbox_x=8, bbox_y=18, bbox_w=8, bbox_h=8,
            area_pixels=50.0, mean_intensity=120.0,
            max_intensity=200.0, integrated_intensity=6000.0,
        ),
        ParticleRecord(
            cell_id=cell_ids[0], threshold_run_id=thr_id, label_value=2,
            centroid_x=15.0, centroid_y=25.0,
            bbox_x=11, bbox_y=21, bbox_w=6, bbox_h=6,
            area_pixels=30.0, mean_intensity=80.0,
            max_intensity=150.0, integrated_intensity=2400.0,
        ),
        ParticleRecord(
            cell_id=cell_ids[1], threshold_run_id=thr_id, label_value=3,
            centroid_x=22.0, centroid_y=32.0,
            bbox_x=18, bbox_y=28, bbox_w=10, bbox_h=10,
            area_pixels=70.0, mean_intensity=90.0,
            max_intensity=180.0, integrated_intensity=6300.0,
        ),
    ]
    store.add_particles(particles)

    # Add particle summary measurements (as ParticleAnalyzer._cell_summaries would)
    # cell_ids[0] has 2 particles, cell_ids[1] has 1 particle, cell_ids[2] has 0
    cell_area = 200.0
    summary_measurements = [
        # cell_ids[0]: 2 particles (areas 50+30=80, intensities 120/80 mean, 6000/2400 integ)
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="particle_count", value=2.0),
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="total_particle_area", value=80.0),
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="mean_particle_area", value=40.0),
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="max_particle_area", value=50.0),
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="particle_coverage_fraction", value=80.0 / cell_area),
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="mean_particle_mean_intensity", value=100.0),
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="mean_particle_integrated_intensity", value=4200.0),
        MeasurementRecord(cell_id=cell_ids[0], channel_id=ch_info.id, metric="total_particle_integrated_intensity", value=8400.0),
        # cell_ids[1]: 1 particle (area 70, intensity 90 mean, 6300 integ)
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="particle_count", value=1.0),
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="total_particle_area", value=70.0),
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="mean_particle_area", value=70.0),
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="max_particle_area", value=70.0),
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="particle_coverage_fraction", value=70.0 / cell_area),
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="mean_particle_mean_intensity", value=90.0),
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="mean_particle_integrated_intensity", value=6300.0),
        MeasurementRecord(cell_id=cell_ids[1], channel_id=ch_info.id, metric="total_particle_integrated_intensity", value=6300.0),
        # cell_ids[2]: 0 particles
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="particle_count", value=0.0),
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="total_particle_area", value=0.0),
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="mean_particle_area", value=0.0),
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="max_particle_area", value=0.0),
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="particle_coverage_fraction", value=0.0),
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="mean_particle_mean_intensity", value=0.0),
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="mean_particle_integrated_intensity", value=0.0),
        MeasurementRecord(cell_id=cell_ids[2], channel_id=ch_info.id, metric="total_particle_integrated_intensity", value=0.0),
    ]
    store.add_measurements(summary_measurements)

    return store


@pytest.fixture
def experiment_with_particle_images(tmp_path: Path) -> ExperimentStore:
    """Experiment with real pixel data for multi-channel particle intensity tests.

    Layout (64x64):
    - Cell 1 (label=1): rows 15:30, cols 5:20 — has 1 particle at (8:16, 18:26)
    - Cell 2 (label=2): rows 30:45, cols 20:35 — no particles
    Two channels: DAPI (fill=50) and GFP (fill=100) with different values.
    """
    store = ExperimentStore.create(tmp_path / "multichan.percell", name="MultiCh")
    store.add_channel("DAPI", role="nuclear")
    store.add_channel("GFP")

    store.add_condition("control")
    fov_id = store.add_fov("fov1", "control", width=64, height=64, pixel_size_um=0.5)

    # Write channel images with distinct intensities
    dapi_img = np.full((64, 64), 50, dtype=np.uint16)
    gfp_img = np.full((64, 64), 100, dtype=np.uint16)
    # Bright spot in cell 1 region for particle
    dapi_img[18:26, 8:16] = 200
    gfp_img[18:26, 8:16] = 150
    store.write_image("fov1", "control", "DAPI", dapi_img)
    store.write_image("fov1", "control", "GFP", gfp_img)

    # Label image
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[15:30, 5:20] = 1
    labels[30:45, 20:35] = 2
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")
    store.write_labels("fov1", "control", labels, seg_id)

    # Threshold mask — only the bright spot
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[18:26, 8:16] = 1
    thr_id = store.add_threshold_run(channel="GFP", method="otsu")
    store.write_mask("fov1", "control", "GFP", mask, thr_id)

    # Cells
    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=12.0, centroid_y=22.0,
            bbox_x=5, bbox_y=15, bbox_w=15, bbox_h=15,
            area_pixels=float(np.sum(labels == 1)),
        ),
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=2,
            centroid_x=27.0, centroid_y=37.0,
            bbox_x=20, bbox_y=30, bbox_w=15, bbox_h=15,
            area_pixels=float(np.sum(labels == 2)),
        ),
    ]
    cell_ids = store.add_cells(cells)

    # Particle in cell 1
    particles = [
        ParticleRecord(
            cell_id=cell_ids[0], threshold_run_id=thr_id, label_value=1,
            centroid_x=12.0, centroid_y=22.0,
            bbox_x=8, bbox_y=18, bbox_w=8, bbox_h=8,
            area_pixels=64.0, mean_intensity=150.0,
            max_intensity=150.0, integrated_intensity=9600.0,
        ),
    ]
    store.add_particles(particles)

    # Measurements so cell CSV has content
    ch_info = store.get_channel("GFP")
    measurements = [
        MeasurementRecord(
            cell_id=cid, channel_id=ch_info.id,
            metric="mean_intensity", value=100.0 + i * 10,
        )
        for i, cid in enumerate(cell_ids)
    ]
    store.add_measurements(measurements)

    yield store
    store.close()


@pytest.fixture
def tiff_dir(tmp_path: Path) -> Path:
    """Create a directory with synthetic TIFF files for import testing."""
    d = tmp_path / "tiffs"
    d.mkdir()
    for ch in (0, 1):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tifffile.imwrite(str(d / f"img_ch{ch:02d}_t00.tif"), data)
    return d


@pytest.fixture
def multi_condition_tiff_dir(tmp_path: Path) -> Path:
    """Create TIFFs with multi-condition naming (ctrl_s00, treated_s00)."""
    d = tmp_path / "multi_cond_tiffs"
    d.mkdir()
    for cond in ("ctrl", "treated"):
        for site in ("s00",):
            data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
            tifffile.imwrite(str(d / f"{cond}_{site}_ch00.tif"), data)
    return d
