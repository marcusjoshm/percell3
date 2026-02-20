"""Tests for ParticleAnalyzer — particle detection and morphometrics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.measure.particle_analyzer import (
    PARTICLE_SUMMARY_METRICS,
    ParticleAnalyzer,
    ParticleAnalysisResult,
)


@pytest.fixture
def particle_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with cells, labels, threshold mask, and channel image.

    Layout (64x64):
    - Cell 1 (label=1): rows 5:25, cols 5:25 — has 2 bright blobs
    - Cell 2 (label=2): rows 35:55, cols 35:55 — has 1 bright blob
    - Cell 3 (label=3): rows 5:15, cols 40:50 — no bright features (below threshold)
    """
    store = ExperimentStore.create(tmp_path / "particle.percell")
    store.add_channel("DAPI", role="nucleus")
    store.add_channel("GFP", role="signal")
    store.add_condition("control")
    fov_id = store.add_fov("fov_1", "control", width=64, height=64, pixel_size_um=0.5)
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")

    # Label image
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[5:25, 5:25] = 1    # Cell 1
    labels[35:55, 35:55] = 2  # Cell 2
    labels[5:15, 40:50] = 3   # Cell 3
    store.write_labels("fov_1", "control", labels, seg_id)

    # Channel image: background=20, blobs=200
    image = np.full((64, 64), 20, dtype=np.uint16)
    # Cell 1: two blobs
    image[8:14, 8:14] = 200   # Blob A in cell 1
    image[16:22, 16:22] = 200 # Blob B in cell 1
    # Cell 2: one blob
    image[40:48, 40:48] = 200 # Blob in cell 2
    # Cell 3: no bright features
    store.write_image("fov_1", "control", "GFP", image)

    # Threshold mask: pixels > 100 inside cells
    mask = np.zeros((64, 64), dtype=bool)
    mask[8:14, 8:14] = True   # Blob A
    mask[16:22, 16:22] = True # Blob B
    mask[40:48, 40:48] = True # Blob in cell 2
    thr_id = store.add_threshold_run(channel="GFP", method="otsu")
    store.write_mask("fov_1", "control", "GFP", mask.astype(np.uint8), thr_id)

    # Cells
    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=15, centroid_y=15, bbox_x=5, bbox_y=5, bbox_w=20, bbox_h=20,
            area_pixels=float(np.sum(labels == 1)),
        ),
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=2,
            centroid_x=45, centroid_y=45, bbox_x=35, bbox_y=35, bbox_w=20, bbox_h=20,
            area_pixels=float(np.sum(labels == 2)),
        ),
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=3,
            centroid_x=47, centroid_y=10, bbox_x=40, bbox_y=5, bbox_w=10, bbox_h=10,
            area_pixels=float(np.sum(labels == 3)),
        ),
    ]
    cell_ids = store.add_cells(cells)

    # Store cell_ids and threshold_run_id as fixture data
    store._test_cell_ids = cell_ids
    store._test_thr_id = thr_id

    yield store
    store.close()


class TestParticleAnalyzer:
    def test_detects_particles(self, particle_experiment: ExperimentStore):
        store = particle_experiment
        cell_ids = store._test_cell_ids
        thr_id = store._test_thr_id

        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=thr_id, cell_ids=cell_ids,
        )

        assert isinstance(result, ParticleAnalysisResult)
        assert result.cells_analyzed == 3
        # Cell 1: 2 blobs, Cell 2: 1 blob, Cell 3: 0 blobs
        assert result.total_particles == 3

    def test_particle_records(self, particle_experiment: ExperimentStore):
        store = particle_experiment
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=store._test_cell_ids,
        )

        # Check particle attributes
        for p in result.particles:
            assert p.threshold_run_id == store._test_thr_id
            assert p.area_pixels > 0
            assert p.centroid_x > 0
            assert p.centroid_y > 0
            assert p.bbox_w > 0
            assert p.bbox_h > 0
            # With pixel_size_um=0.5, area_um2 should be set
            assert p.area_um2 is not None
            assert p.area_um2 == pytest.approx(p.area_pixels * 0.25, rel=0.01)

    def test_unique_label_values(self, particle_experiment: ExperimentStore):
        store = particle_experiment
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=store._test_cell_ids,
        )

        label_vals = [p.label_value for p in result.particles]
        assert len(label_vals) == len(set(label_vals)), "Particle label values must be unique"

    def test_particle_label_image(self, particle_experiment: ExperimentStore):
        store = particle_experiment
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=store._test_cell_ids,
        )

        pli = result.particle_label_image
        assert pli.shape == (64, 64)
        assert pli.dtype == np.int32
        # Should have 3 unique non-zero values
        unique_nonzero = set(np.unique(pli)) - {0}
        assert len(unique_nonzero) == 3

    def test_summary_measurements(self, particle_experiment: ExperimentStore):
        store = particle_experiment
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=store._test_cell_ids,
        )

        # 3 cells * 5 metrics = 15 summary measurements
        assert len(result.summary_measurements) == 15

        # Check metric names
        metrics = {m.metric for m in result.summary_measurements}
        assert metrics == set(PARTICLE_SUMMARY_METRICS)

    def test_cell_with_no_particles(self, particle_experiment: ExperimentStore):
        """Cell 3 has no bright features — should get particle_count=0."""
        store = particle_experiment
        cell_ids = store._test_cell_ids
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=cell_ids,
        )

        # Find summary for cell 3
        cell3_id = cell_ids[2]
        cell3_summaries = [m for m in result.summary_measurements if m.cell_id == cell3_id]
        count_m = [m for m in cell3_summaries if m.metric == "particle_count"][0]
        assert count_m.value == 0.0

    def test_min_area_filter(self, particle_experiment: ExperimentStore):
        """Large min_area should filter out small particles."""
        store = particle_experiment
        # Blobs are 6x6=36 and 8x8=64 pixels, so min_area=100 filters all
        analyzer = ParticleAnalyzer(min_particle_area=100)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=store._test_cell_ids,
        )
        assert result.total_particles == 0

    def test_particle_count_per_cell(self, particle_experiment: ExperimentStore):
        """Cell 1 should have 2 particles, Cell 2 should have 1."""
        store = particle_experiment
        cell_ids = store._test_cell_ids
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=cell_ids,
        )

        cell1_particles = [p for p in result.particles if p.cell_id == cell_ids[0]]
        cell2_particles = [p for p in result.particles if p.cell_id == cell_ids[1]]
        assert len(cell1_particles) == 2
        assert len(cell2_particles) == 1

    def test_coverage_fraction(self, particle_experiment: ExperimentStore):
        """particle_coverage_fraction should be total_particle_area / cell_area."""
        store = particle_experiment
        cell_ids = store._test_cell_ids
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=cell_ids,
        )

        # Cell 1: area=400 (20x20), 2 blobs of ~36 pixels each
        cell1_id = cell_ids[0]
        cell1_summaries = {
            m.metric: m.value
            for m in result.summary_measurements if m.cell_id == cell1_id
        }
        total_area = cell1_summaries["total_particle_area"]
        coverage = cell1_summaries["particle_coverage_fraction"]
        assert coverage == pytest.approx(total_area / 400.0, rel=0.01)

    def test_morphometrics(self, particle_experiment: ExperimentStore):
        """Particles should have morphometric measurements."""
        store = particle_experiment
        analyzer = ParticleAnalyzer(min_particle_area=5)
        result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=store._test_thr_id, cell_ids=store._test_cell_ids,
        )

        for p in result.particles:
            assert p.perimeter is not None
            assert p.perimeter > 0
            assert p.mean_intensity is not None
            assert p.max_intensity is not None
            assert p.integrated_intensity is not None
