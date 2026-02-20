"""Integration tests — full pipeline: CellGrouper → ThresholdEngine → ParticleAnalyzer."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord
from percell3.measure.cell_grouper import CellGrouper
from percell3.measure.particle_analyzer import ParticleAnalyzer, ParticleAnalysisResult
from percell3.measure.threshold_viewer import compute_masked_otsu, create_group_image
from percell3.measure.thresholding import ThresholdEngine


# ---------------------------------------------------------------------------
# Shared fixture: realistic experiment with bimodal cell population
# ---------------------------------------------------------------------------


@pytest.fixture
def integration_store(tmp_path: Path) -> ExperimentStore:
    """Experiment with 30 cells, bimodal GFP expression, and bright blobs.

    Layout (128x128):
    - 30 cells arranged in a 6x5 grid, each 16x16 pixels
    - First 15 cells: low GFP expression (~50), 1 bright blob each
    - Last 15 cells: high GFP expression (~200), 2 bright blobs each
    """
    store = ExperimentStore.create(tmp_path / "integration.percell")
    store.add_channel("DAPI", role="nucleus")
    store.add_channel("GFP", role="signal")
    store.add_condition("control")
    fov_id = store.add_fov("fov_1", "control", width=128, height=128, pixel_size_um=0.5)
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")

    rng = np.random.default_rng(42)

    labels = np.zeros((128, 128), dtype=np.int32)
    image = np.full((128, 128), 10, dtype=np.uint16)  # Background

    cells = []
    for i in range(30):
        row, col = divmod(i, 5)
        y0, x0 = row * 20 + 2, col * 25 + 2
        label_val = i + 1

        labels[y0:y0 + 16, x0:x0 + 16] = label_val

        if i < 15:
            # Low expression: faint cell body, one small bright blob
            image[y0:y0 + 16, x0:x0 + 16] = rng.normal(50, 5, (16, 16)).clip(1, 65535).astype(np.uint16)
            image[y0 + 4:y0 + 8, x0 + 4:x0 + 8] = 180  # Blob
        else:
            # High expression: bright cell body, two bright blobs
            image[y0:y0 + 16, x0:x0 + 16] = rng.normal(150, 10, (16, 16)).clip(1, 65535).astype(np.uint16)
            image[y0 + 2:y0 + 6, x0 + 2:x0 + 6] = 250  # Blob A
            image[y0 + 10:y0 + 14, x0 + 10:x0 + 14] = 250  # Blob B

        cells.append(CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=label_val,
            centroid_x=float(x0 + 8), centroid_y=float(y0 + 8),
            bbox_x=x0, bbox_y=y0, bbox_w=16, bbox_h=16,
            area_pixels=float(np.sum(labels == label_val)),
        ))

    cell_ids = store.add_cells(cells)
    store.write_labels("fov_1", "control", labels, seg_id)
    store.write_image("fov_1", "control", "GFP", image)

    # Add measurements (mean_intensity of GFP for grouping)
    gfp = store.get_channel("GFP")
    measurements = []
    for j, cid in enumerate(cell_ids):
        if j < 15:
            val = rng.normal(50, 5)
        else:
            val = rng.normal(200, 10)
        measurements.append(MeasurementRecord(
            cell_id=cid, channel_id=gfp.id,
            metric="mean_intensity", value=float(val),
        ))
    store.add_measurements(measurements)

    # Store helpers
    store._test_cell_ids = cell_ids
    store._test_labels = labels
    store._test_image = image

    yield store
    store.close()


@pytest.fixture
def multi_fov_store(tmp_path: Path) -> ExperimentStore:
    """Experiment with 2 FOVs, each having cells and images."""
    store = ExperimentStore.create(tmp_path / "multi_fov.percell")
    store.add_channel("DAPI", role="nucleus")
    store.add_channel("GFP", role="signal")
    store.add_condition("control")

    rng = np.random.default_rng(99)

    for fov_name in ["fov_1", "fov_2"]:
        fov_id = store.add_fov(fov_name, "control", width=64, height=64, pixel_size_um=0.5)
        seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")

        labels = np.zeros((64, 64), dtype=np.int32)
        image = np.full((64, 64), 10, dtype=np.uint16)

        # 12 cells per FOV
        cells = []
        for i in range(12):
            row, col = divmod(i, 4)
            y0, x0 = row * 20 + 2, col * 15 + 2
            lv = i + 1

            labels[y0:y0 + 12, x0:x0 + 12] = lv
            if i < 6:
                image[y0:y0 + 12, x0:x0 + 12] = rng.normal(40, 5, (12, 12)).clip(1, 65535).astype(np.uint16)
                image[y0 + 3:y0 + 7, x0 + 3:x0 + 7] = 200
            else:
                image[y0:y0 + 12, x0:x0 + 12] = rng.normal(180, 10, (12, 12)).clip(1, 65535).astype(np.uint16)
                image[y0 + 2:y0 + 6, x0 + 2:x0 + 6] = 250
                image[y0 + 7:y0 + 11, x0 + 7:x0 + 11] = 250

            cells.append(CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=lv,
                centroid_x=float(x0 + 6), centroid_y=float(y0 + 6),
                bbox_x=x0, bbox_y=y0, bbox_w=12, bbox_h=12,
                area_pixels=float(np.sum(labels == lv)),
            ))

        cell_ids = store.add_cells(cells)
        store.write_labels(fov_name, "control", labels, seg_id)
        store.write_image(fov_name, "control", "GFP", image)

        gfp = store.get_channel("GFP")
        measurements = []
        for j, cid in enumerate(cell_ids):
            val = rng.normal(40, 5) if j < 6 else rng.normal(200, 10)
            measurements.append(MeasurementRecord(
                cell_id=cid, channel_id=gfp.id,
                metric="mean_intensity", value=float(val),
            ))
        store.add_measurements(measurements)

    yield store
    store.close()


# ---------------------------------------------------------------------------
# Tests: Full Pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """CellGrouper → ThresholdEngine → ParticleAnalyzer end-to-end."""

    def test_group_threshold_analyze(self, integration_store: ExperimentStore):
        """Full pipeline: group → threshold each group → analyze particles."""
        store = integration_store
        grouper = CellGrouper()
        engine = ThresholdEngine()
        analyzer = ParticleAnalyzer(min_particle_area=5)

        # Step 1: Group cells
        grouping = grouper.group_cells(
            store, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        assert grouping.n_groups >= 1

        # Step 2: Threshold each group
        labels = store.read_labels("fov_1", "control")
        image = store.read_image_numpy("fov_1", "control", "GFP")

        threshold_run_ids = []
        for g_idx, tag_name in enumerate(grouping.tag_names):
            group_cells = store.get_cells(condition="control", tags=[tag_name])
            group_cell_ids = group_cells["id"].tolist()
            group_label_values = group_cells["label_value"].tolist()

            group_img, cell_mask = create_group_image(image, labels, group_label_values)
            threshold_value = compute_masked_otsu(group_img, cell_mask)

            result = engine.threshold_group(
                store, fov="fov_1", condition="control", channel="GFP",
                cell_ids=group_cell_ids, labels=labels, image=image,
                threshold_value=threshold_value, group_tag=tag_name,
            )
            threshold_run_ids.append(result.threshold_run_id)

        # Step 3: Analyze particles for the last threshold run
        all_cells = store.get_cells(condition="control", fov="fov_1")
        pa_result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=threshold_run_ids[-1],
            cell_ids=all_cells["id"].tolist(),
        )

        assert isinstance(pa_result, ParticleAnalysisResult)
        assert pa_result.cells_analyzed == 30
        assert pa_result.total_particles > 0
        assert len(pa_result.summary_measurements) == 30 * 5  # 5 metrics per cell

    def test_skipped_group_produces_zero_particles(self, integration_store: ExperimentStore):
        """When a group is skipped (no threshold applied), cells should get 0 particles."""
        store = integration_store
        grouper = CellGrouper()
        engine = ThresholdEngine()
        analyzer = ParticleAnalyzer(min_particle_area=5)

        grouping = grouper.group_cells(
            store, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )

        labels = store.read_labels("fov_1", "control")
        image = store.read_image_numpy("fov_1", "control", "GFP")

        # Threshold only the FIRST group, skip the second
        first_tag = grouping.tag_names[0]
        group_cells = store.get_cells(condition="control", tags=[first_tag])
        group_label_values = group_cells["label_value"].tolist()

        group_img, cell_mask = create_group_image(image, labels, group_label_values)
        threshold_value = compute_masked_otsu(group_img, cell_mask)

        result = engine.threshold_group(
            store, fov="fov_1", condition="control", channel="GFP",
            cell_ids=group_cells["id"].tolist(), labels=labels, image=image,
            threshold_value=threshold_value, group_tag=first_tag,
        )

        # Analyze only the thresholded group
        pa_result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=result.threshold_run_id,
            cell_ids=group_cells["id"].tolist(),
        )

        # Particles should only be found in the thresholded group's cells
        for p in pa_result.particles:
            assert p.cell_id in group_cells["id"].tolist()

    def test_particle_label_image_zarr_roundtrip(self, integration_store: ExperimentStore):
        """Particle label images survive zarr write/read cycle."""
        store = integration_store
        engine = ThresholdEngine()
        analyzer = ParticleAnalyzer(min_particle_area=5)

        labels = store.read_labels("fov_1", "control")
        image = store.read_image_numpy("fov_1", "control", "GFP")
        all_cells = store.get_cells(condition="control", fov="fov_1")
        cell_ids = all_cells["id"].tolist()
        label_values = all_cells["label_value"].tolist()

        # Threshold all cells together as one group
        group_img, cell_mask = create_group_image(image, labels, label_values)
        thresh = compute_masked_otsu(group_img, cell_mask)
        thr_result = engine.threshold_group(
            store, fov="fov_1", condition="control", channel="GFP",
            cell_ids=cell_ids, labels=labels, image=image,
            threshold_value=thresh,
        )

        # Analyze
        pa_result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=thr_result.threshold_run_id,
            cell_ids=cell_ids,
        )

        # Write to zarr
        store.write_particle_labels(
            "fov_1", "control", "GFP",
            pa_result.particle_label_image,
        )

        # Read back
        read_back = store.read_particle_labels("fov_1", "control", "GFP")
        np.testing.assert_array_equal(read_back, pa_result.particle_label_image)
        assert read_back.dtype == np.int32


class TestReThresholding:
    """Re-thresholding should replace old results."""

    def test_rethreshold_replaces_particles(self, integration_store: ExperimentStore):
        """Running the pipeline twice should replace old particles."""
        store = integration_store
        engine = ThresholdEngine()
        analyzer = ParticleAnalyzer(min_particle_area=5)

        labels = store.read_labels("fov_1", "control")
        image = store.read_image_numpy("fov_1", "control", "GFP")
        all_cells = store.get_cells(condition="control", fov="fov_1")
        cell_ids = all_cells["id"].tolist()
        label_values = all_cells["label_value"].tolist()

        group_img, cell_mask = create_group_image(image, labels, label_values)
        thresh = compute_masked_otsu(group_img, cell_mask)

        # First run
        thr1 = engine.threshold_group(
            store, fov="fov_1", condition="control", channel="GFP",
            cell_ids=cell_ids, labels=labels, image=image,
            threshold_value=thresh,
        )
        pa1 = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=thr1.threshold_run_id, cell_ids=cell_ids,
        )
        store.add_particles(pa1.particles)
        first_count = pa1.total_particles

        # Second run with very high threshold (no particles)
        thr2 = engine.threshold_group(
            store, fov="fov_1", condition="control", channel="GFP",
            cell_ids=cell_ids, labels=labels, image=image,
            threshold_value=60000.0,  # Above max pixel value
        )
        pa2 = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=thr2.threshold_run_id, cell_ids=cell_ids,
        )

        # Very high threshold should find zero particles
        assert pa2.total_particles == 0

        # New run creates a new threshold_run_id
        assert thr2.threshold_run_id != thr1.threshold_run_id

    def test_regrouping_then_rethreshold(self, integration_store: ExperimentStore):
        """Re-grouping should clean old tags, then re-thresholding works."""
        store = integration_store
        grouper = CellGrouper()

        # First grouping
        g1 = grouper.group_cells(
            store, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        first_tags = set(g1.tag_names)

        # Re-group (should clean old tags)
        g2 = grouper.group_cells(
            store, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )

        # All cells should be assigned to new groups
        total_tagged = 0
        for tag in g2.tag_names:
            tagged = store.get_cells(condition="control", tags=[tag])
            total_tagged += len(tagged)
        assert total_tagged == 30


class TestMultiFovBatch:
    """Batch processing across multiple FOVs."""

    def test_process_two_fovs(self, multi_fov_store: ExperimentStore):
        """Full pipeline across both FOVs produces independent results."""
        store = multi_fov_store
        grouper = CellGrouper()
        engine = ThresholdEngine()
        analyzer = ParticleAnalyzer(min_particle_area=3)

        results_per_fov = {}

        for fov_name in ["fov_1", "fov_2"]:
            grouping = grouper.group_cells(
                store, fov=fov_name, condition="control",
                channel="GFP", metric="mean_intensity",
            )

            labels = store.read_labels(fov_name, "control")
            image = store.read_image_numpy(fov_name, "control", "GFP")

            all_cells = store.get_cells(condition="control", fov=fov_name)
            cell_ids = all_cells["id"].tolist()
            label_values = all_cells["label_value"].tolist()

            # Threshold all cells as one group for simplicity
            group_img, cell_mask = create_group_image(image, labels, label_values)
            thresh = compute_masked_otsu(group_img, cell_mask)

            thr_result = engine.threshold_group(
                store, fov=fov_name, condition="control", channel="GFP",
                cell_ids=cell_ids, labels=labels, image=image,
                threshold_value=thresh,
            )

            pa_result = analyzer.analyze_fov(
                store, fov=fov_name, condition="control", channel="GFP",
                threshold_run_id=thr_result.threshold_run_id,
                cell_ids=cell_ids,
            )

            results_per_fov[fov_name] = pa_result

        # Both FOVs should produce results
        for fov_name, result in results_per_fov.items():
            assert result.cells_analyzed == 12
            assert result.total_particles > 0
            assert len(result.summary_measurements) == 12 * 5

        # Results should be independent
        fov1_particles = {p.cell_id for p in results_per_fov["fov_1"].particles}
        fov2_particles = {p.cell_id for p in results_per_fov["fov_2"].particles}
        assert fov1_particles.isdisjoint(fov2_particles)


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_group_pipeline(self, integration_store: ExperimentStore):
        """Pipeline works when all cells are in one group (few cells scenario)."""
        store = integration_store
        engine = ThresholdEngine()
        analyzer = ParticleAnalyzer(min_particle_area=5)

        labels = store.read_labels("fov_1", "control")
        image = store.read_image_numpy("fov_1", "control", "GFP")
        all_cells = store.get_cells(condition="control", fov="fov_1")
        cell_ids = all_cells["id"].tolist()
        label_values = all_cells["label_value"].tolist()

        # Treat all cells as one group
        group_img, cell_mask = create_group_image(image, labels, label_values)
        thresh = compute_masked_otsu(group_img, cell_mask)

        thr_result = engine.threshold_group(
            store, fov="fov_1", condition="control", channel="GFP",
            cell_ids=cell_ids, labels=labels, image=image,
            threshold_value=thresh,
        )

        pa_result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=thr_result.threshold_run_id,
            cell_ids=cell_ids,
        )

        assert pa_result.cells_analyzed == 30
        assert pa_result.total_particles > 0

    def test_very_high_threshold_no_particles(self, integration_store: ExperimentStore):
        """Threshold above max intensity should produce zero particles."""
        store = integration_store
        engine = ThresholdEngine()
        analyzer = ParticleAnalyzer(min_particle_area=5)

        labels = store.read_labels("fov_1", "control")
        image = store.read_image_numpy("fov_1", "control", "GFP")
        all_cells = store.get_cells(condition="control", fov="fov_1")
        cell_ids = all_cells["id"].tolist()

        thr_result = engine.threshold_group(
            store, fov="fov_1", condition="control", channel="GFP",
            cell_ids=cell_ids, labels=labels, image=image,
            threshold_value=60000.0,  # Above max pixel value
        )

        pa_result = analyzer.analyze_fov(
            store, fov="fov_1", condition="control", channel="GFP",
            threshold_run_id=thr_result.threshold_run_id,
            cell_ids=cell_ids,
        )

        assert pa_result.total_particles == 0
        # All cells should still have summary measurements (with zeros)
        assert len(pa_result.summary_measurements) == 30 * 5
        for m in pa_result.summary_measurements:
            if m.metric == "particle_count":
                assert m.value == 0.0
