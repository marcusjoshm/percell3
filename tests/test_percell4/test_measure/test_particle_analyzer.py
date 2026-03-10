"""Tests for percell4.measure.particle_analyzer — connected component analysis."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.measure.particle_analyzer import ParticleAnalysisResult, analyze_particles

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


def _build_experiment_with_mask(tmp_path: Path):
    """Build a store with FOV, segmentation, ROI, and a threshold mask with 3 blobs.

    Returns (store, fov_id, mask_id, pipeline_run_id, particle_type_name).
    """
    percell_dir = tmp_path / "test.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    experiment_id = exp["id"]

    # Get ROI types
    roi_types = store.db.get_roi_type_definitions(experiment_id)
    cell_type_id = [rt for rt in roi_types if rt["name"] == "cell"][0]["id"]
    particle_type_name = "particle"

    pipeline_run_id = new_uuid()
    store.db.insert_pipeline_run(pipeline_run_id, "test_particle")

    # Create FOV
    fov_id = new_uuid()
    store.db.insert_fov(fov_id, experiment_id, status="imported")

    fov_hex = uuid_to_hex(fov_id)
    # Write a synthetic image
    image = np.full((80, 80), 50.0, dtype=np.float32)
    store.layers.write_image_channels(fov_hex, {0: image, 1: image})

    # Create segmentation set
    seg_set_id = new_uuid()
    store.db.insert_segmentation_set(
        seg_set_id, experiment_id, cell_type_id, "cellpose",
    )

    # Write label image: one big cell covering most of the image
    labels = np.zeros((80, 80), dtype=np.int32)
    labels[5:75, 5:75] = 1
    seg_hex = uuid_to_hex(seg_set_id)
    store.layers.write_labels(seg_hex, fov_hex, labels)

    # Assign segmentation
    store.db.assign_segmentation(
        [fov_id], seg_set_id, cell_type_id, pipeline_run_id,
    )

    # Create cell identity + cell ROI
    ci = new_uuid()
    store.db.insert_cell_identity(ci, fov_id, cell_type_id)
    parent_roi_id = new_uuid()
    store.db.insert_roi(
        parent_roi_id, fov_id, cell_type_id, ci, None,
        label_id=1, bbox_y=5, bbox_x=5, bbox_h=70, bbox_w=70, area_px=4900,
    )

    # Create a threshold mask with 3 separate blobs inside the cell region
    mask = np.zeros((80, 80), dtype=np.uint8)
    # Blob 1: small square at (10,10)
    mask[10:15, 10:15] = 1
    # Blob 2: small square at (30,30)
    mask[30:35, 30:35] = 1
    # Blob 3: small square at (50,50)
    mask[50:55, 50:55] = 1

    mask_id = new_uuid()
    mask_hex = uuid_to_hex(mask_id)
    store.layers.write_mask(mask_hex, mask)

    store.db.insert_threshold_mask(
        id=mask_id,
        fov_id=fov_id,
        source_channel="DAPI",
        method="manual",
        threshold_value=100.0,
        zarr_path=f"zarr/masks/{mask_hex}",
        status="computed",
    )

    return store, fov_id, mask_id, pipeline_run_id, particle_type_name


# ===================================================================
# Tests
# ===================================================================


class TestAnalyzeParticles:
    """analyze_particles finds connected components and creates sub-ROIs."""

    def test_finds_three_blobs(self, tmp_path: Path) -> None:
        store, fov_id, mask_id, pr_id, particle_type = (
            _build_experiment_with_mask(tmp_path)
        )
        try:
            result = analyze_particles(
                store,
                fov_id=fov_id,
                mask_id=mask_id,
                roi_type_name=particle_type,
                pipeline_run_id=pr_id,
            )

            assert isinstance(result, ParticleAnalysisResult)
            assert result.particles_created == 3
            assert result.parent_rois_analyzed == 1

            # Verify particle ROIs in DB
            exp = store.get_experiment()
            roi_types = store.db.get_roi_type_definitions(exp["id"])
            particle_type_id = [
                rt for rt in roi_types if rt["name"] == particle_type
            ][0]["id"]

            particle_rois = store.db.get_rois_by_fov_and_type(
                fov_id, particle_type_id,
            )
            assert len(particle_rois) == 3

            # All particles have parent_roi_id set
            for pr in particle_rois:
                assert pr["parent_roi_id"] is not None
                assert pr["cell_identity_id"] is None  # Sub-cellular

            # Each particle has area == 25 (5x5)
            for pr in particle_rois:
                assert pr["area_px"] == 25
        finally:
            store.close()

    def test_particle_label_image(self, tmp_path: Path) -> None:
        store, fov_id, mask_id, pr_id, particle_type = (
            _build_experiment_with_mask(tmp_path)
        )
        try:
            result = analyze_particles(
                store,
                fov_id=fov_id,
                mask_id=mask_id,
                roi_type_name=particle_type,
                pipeline_run_id=pr_id,
            )

            label_img = result.particle_label_image
            assert label_img.shape == (80, 80)
            # Should have exactly 3 unique non-zero labels
            unique_labels = set(label_img[label_img > 0])
            assert len(unique_labels) == 3
        finally:
            store.close()

    def test_min_particle_area_filter(self, tmp_path: Path) -> None:
        store, fov_id, mask_id, pr_id, particle_type = (
            _build_experiment_with_mask(tmp_path)
        )
        try:
            # Each blob is 5x5 = 25 pixels; setting min to 30 should filter all
            result = analyze_particles(
                store,
                fov_id=fov_id,
                mask_id=mask_id,
                roi_type_name=particle_type,
                pipeline_run_id=pr_id,
                min_particle_area=30,
            )
            assert result.particles_created == 0
        finally:
            store.close()

    def test_no_parent_rois(self, tmp_path: Path) -> None:
        """If no parent ROIs exist, returns empty result."""
        percell_dir = tmp_path / "empty.percell"
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            exp = store.get_experiment()
            experiment_id = exp["id"]

            roi_types = store.db.get_roi_type_definitions(experiment_id)
            cell_type_id = [rt for rt in roi_types if rt["name"] == "cell"][0]["id"]

            pr_id = new_uuid()
            store.db.insert_pipeline_run(pr_id, "test_empty")

            fov_id = new_uuid()
            store.db.insert_fov(fov_id, experiment_id, status="imported")

            fov_hex = uuid_to_hex(fov_id)
            image = np.ones((20, 20), dtype=np.float32)
            store.layers.write_image_channels(fov_hex, {0: image, 1: image})

            seg_set_id = new_uuid()
            store.db.insert_segmentation_set(
                seg_set_id, experiment_id, cell_type_id, "cellpose",
            )
            labels = np.zeros((20, 20), dtype=np.int32)
            seg_hex = uuid_to_hex(seg_set_id)
            store.layers.write_labels(seg_hex, fov_hex, labels)

            store.db.assign_segmentation(
                [fov_id], seg_set_id, cell_type_id, pr_id,
            )

            mask_id = new_uuid()
            mask_hex = uuid_to_hex(mask_id)
            store.layers.write_mask(mask_hex, np.ones((20, 20), dtype=np.uint8))
            store.db.insert_threshold_mask(
                id=mask_id, fov_id=fov_id, source_channel="DAPI",
                method="manual", threshold_value=0.5,
                zarr_path=f"zarr/masks/{mask_hex}", status="computed",
            )

            result = analyze_particles(
                store, fov_id=fov_id, mask_id=mask_id,
                roi_type_name="particle", pipeline_run_id=pr_id,
            )
            assert result.particles_created == 0
            assert result.parent_rois_analyzed == 0
        finally:
            store.close()

    def test_top_level_type_raises(self, tmp_path: Path) -> None:
        """Using a top-level ROI type (no parent_type_id) raises ValueError."""
        percell_dir = tmp_path / "toplevel.percell"
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            exp = store.get_experiment()
            fov_id = new_uuid()
            store.db.insert_fov(fov_id, exp["id"], status="imported")

            pr_id = new_uuid()
            store.db.insert_pipeline_run(pr_id, "test_toplevel")
            mask_id = new_uuid()

            with pytest.raises(ValueError, match="no parent_type_id"):
                analyze_particles(
                    store, fov_id=fov_id, mask_id=mask_id,
                    roi_type_name="cell", pipeline_run_id=pr_id,
                )
        finally:
            store.close()
