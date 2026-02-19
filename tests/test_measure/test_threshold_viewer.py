"""Tests for threshold_viewer — pure computation (no napari required)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.measure.threshold_viewer import (
    ThresholdDecision,
    compute_masked_otsu,
    create_group_image,
)
from percell3.measure.thresholding import ThresholdEngine, ThresholdResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bimodal_image():
    """64x64 bimodal image: background ~20, foreground ~200."""
    rng = np.random.default_rng(42)
    img = np.zeros((64, 64), dtype=np.uint16)
    img[:, :] = rng.normal(20, 3, (64, 64)).clip(0, 65535).astype(np.uint16)
    img[20:50, 20:50] = rng.normal(200, 10, (30, 30)).clip(0, 65535).astype(np.uint16)
    return img


@pytest.fixture
def label_image():
    """64x64 label image with 3 cells."""
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[10:30, 10:30] = 1  # Cell 1 (low region + some high)
    labels[25:50, 25:50] = 2  # Cell 2 (overlaps with high region)
    labels[50:60, 50:60] = 3  # Cell 3 (only background)
    return labels


@pytest.fixture
def threshold_store(tmp_path: Path) -> ExperimentStore:
    """Experiment with cells and images ready for group thresholding."""
    store = ExperimentStore.create(tmp_path / "thresh.percell")
    store.add_channel("DAPI", role="nucleus")
    store.add_channel("GFP", role="signal")
    store.add_condition("control")
    fov_id = store.add_fov("fov_1", "control", width=64, height=64)
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")

    # Label image
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[10:30, 10:30] = 1
    labels[25:50, 25:50] = 2
    labels[50:60, 50:60] = 3
    store.write_labels("fov_1", "control", labels, seg_id)

    # Bimodal image
    rng = np.random.default_rng(42)
    image = np.zeros((64, 64), dtype=np.uint16)
    image[:, :] = rng.normal(20, 3, (64, 64)).clip(0, 65535).astype(np.uint16)
    image[20:50, 20:50] = rng.normal(200, 10, (30, 30)).clip(0, 65535).astype(np.uint16)
    store.write_image("fov_1", "control", "GFP", image)

    # Add cells
    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=20, centroid_y=20, bbox_x=10, bbox_y=10, bbox_w=20, bbox_h=20,
            area_pixels=400,
        ),
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=2,
            centroid_x=37, centroid_y=37, bbox_x=25, bbox_y=25, bbox_w=25, bbox_h=25,
            area_pixels=625,
        ),
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=3,
            centroid_x=55, centroid_y=55, bbox_x=50, bbox_y=50, bbox_w=10, bbox_h=10,
            area_pixels=100,
        ),
    ]
    cell_ids = store.add_cells(cells)

    yield store
    store.close()


# ---------------------------------------------------------------------------
# Tests: create_group_image
# ---------------------------------------------------------------------------


class TestCreateGroupImage:
    def test_basic(self, bimodal_image, label_image):
        group_img, mask = create_group_image(bimodal_image, label_image, [1, 2])

        # Cells 1 and 2 should be visible
        assert np.any(group_img[label_image == 1] > 0)
        assert np.any(group_img[label_image == 2] > 0)
        # Cell 3 should be zeroed
        assert np.all(group_img[label_image == 3] == 0)
        # Background should be zeroed
        assert np.all(group_img[label_image == 0] == 0)

    def test_mask_shape(self, bimodal_image, label_image):
        _, mask = create_group_image(bimodal_image, label_image, [1])
        assert mask.shape == label_image.shape
        assert mask.dtype == bool
        # Only cell 1 pixels should be True
        assert np.all(mask == (label_image == 1))

    def test_single_cell(self, bimodal_image, label_image):
        group_img, mask = create_group_image(bimodal_image, label_image, [3])
        assert np.all(group_img[label_image != 3] == 0)
        assert np.sum(mask) == np.sum(label_image == 3)


# ---------------------------------------------------------------------------
# Tests: compute_masked_otsu
# ---------------------------------------------------------------------------


class TestComputeMaskedOtsu:
    def test_basic_otsu(self, bimodal_image, label_image):
        """Otsu on cells 1+2 (which include high-intensity region)."""
        _, mask = create_group_image(bimodal_image, label_image, [1, 2])
        thresh = compute_masked_otsu(bimodal_image, mask)
        # Should find threshold between ~20 and ~200
        assert 20 < thresh < 200

    def test_with_roi(self, bimodal_image, label_image):
        """ROI restricts which pixels are used for Otsu."""
        _, mask = create_group_image(bimodal_image, label_image, [1, 2])
        # ROI covering only the high-intensity region
        roi = [(20, 20, 50, 50)]
        thresh = compute_masked_otsu(bimodal_image, mask, roi=roi)
        assert thresh > 0

    def test_no_pixels_raises(self):
        """Empty mask should raise ValueError."""
        image = np.zeros((10, 10), dtype=np.uint16)
        mask = np.zeros((10, 10), dtype=bool)
        with pytest.raises(ValueError, match="No valid pixels"):
            compute_masked_otsu(image, mask)

    def test_roi_outside_mask(self, bimodal_image, label_image):
        """ROI that doesn't intersect any cell pixels."""
        _, mask = create_group_image(bimodal_image, label_image, [3])
        # ROI far from cell 3
        roi = [(0, 0, 5, 5)]
        with pytest.raises(ValueError, match="No valid pixels"):
            compute_masked_otsu(bimodal_image, mask, roi=roi)


# ---------------------------------------------------------------------------
# Tests: ThresholdDecision
# ---------------------------------------------------------------------------


class TestThresholdDecision:
    def test_accepted(self):
        d = ThresholdDecision(accepted=True, threshold_value=100.0)
        assert d.accepted
        assert d.threshold_value == 100.0
        assert d.roi is None
        assert not d.skip_remaining

    def test_skip_remaining(self):
        d = ThresholdDecision(
            accepted=False, threshold_value=50.0, skip_remaining=True,
        )
        assert not d.accepted
        assert d.skip_remaining


# ---------------------------------------------------------------------------
# Tests: ThresholdEngine.threshold_group
# ---------------------------------------------------------------------------


class TestThresholdGroup:
    def test_stores_mask_and_run(self, threshold_store: ExperimentStore):
        engine = ThresholdEngine()

        labels = threshold_store.read_labels("fov_1", "control")
        image = threshold_store.read_image_numpy("fov_1", "control", "GFP")
        cells_df = threshold_store.get_cells(condition="control")
        cell_ids = cells_df["id"].tolist()[:2]  # Cells 1 and 2

        result = engine.threshold_group(
            threshold_store,
            fov="fov_1", condition="control", channel="GFP",
            cell_ids=cell_ids,
            labels=labels, image=image,
            threshold_value=100.0,
            group_tag="group:GFP:mean_intensity:g1",
        )

        assert isinstance(result, ThresholdResult)
        assert result.threshold_run_id >= 1
        assert result.threshold_value == 100.0
        assert result.positive_pixels > 0
        assert result.total_pixels > 0

        # Mask should be stored
        mask = threshold_store.read_mask("fov_1", "control", "GFP")
        assert mask.shape == (64, 64)

    def test_mask_only_within_group_cells(self, threshold_store: ExperimentStore):
        """Mask should only have positive pixels within group cells."""
        engine = ThresholdEngine()

        labels = threshold_store.read_labels("fov_1", "control")
        image = threshold_store.read_image_numpy("fov_1", "control", "GFP")
        cells_df = threshold_store.get_cells(condition="control")
        # Only cell 2 (in the bright region)
        cell_ids = [cells_df["id"].tolist()[1]]

        result = engine.threshold_group(
            threshold_store,
            fov="fov_1", condition="control", channel="GFP",
            cell_ids=cell_ids,
            labels=labels, image=image,
            threshold_value=50.0,
        )

        mask = threshold_store.read_mask("fov_1", "control", "GFP")
        # No positive pixels outside cell 2
        cell2_area = labels == 2
        assert np.all(mask[~cell2_area] == 0)

    def test_roi_stored_in_parameters(self, threshold_store: ExperimentStore):
        engine = ThresholdEngine()
        labels = threshold_store.read_labels("fov_1", "control")
        image = threshold_store.read_image_numpy("fov_1", "control", "GFP")
        cells_df = threshold_store.get_cells(condition="control")

        roi = [(20, 20, 50, 50)]
        engine.threshold_group(
            threshold_store,
            fov="fov_1", condition="control", channel="GFP",
            cell_ids=cells_df["id"].tolist(),
            labels=labels, image=image,
            threshold_value=100.0,
            roi=roi,
        )

        runs = threshold_store.get_threshold_runs()
        assert len(runs) >= 1
        latest = runs[-1]
        assert latest["parameters"]["roi"] == [[20, 20, 50, 50]]
