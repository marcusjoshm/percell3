"""Tests for assign_segmentation_to_fov() core logic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.segment.viewer.copy_labels_widget import assign_segmentation_to_fov


class TestAssignSegmentationToFov:
    """Tests for the assign_segmentation_to_fov function."""

    def test_happy_path_assign(self, tmp_path: Path) -> None:
        """Assign a segmentation to a target FOV creates a config entry."""
        store = ExperimentStore.create(tmp_path / "assign.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov1 = store.add_fov("control", width=40, height=40)
        fov2 = store.add_fov("control", width=40, height=40)
        store.write_image(fov1, "DAPI", np.full((40, 40), 100, dtype=np.uint16))
        store.write_image(fov2, "DAPI", np.full((40, 40), 100, dtype=np.uint16))

        seg_id = store.add_segmentation(
            "seg_test", "cellular", 40, 40,
            source_fov_id=fov1, source_channel="DAPI", model_name="mock",
        )
        labels = np.zeros((40, 40), dtype=np.int32)
        labels[5:15, 5:15] = 1
        store.write_labels(labels, seg_id)
        store.add_cells([CellRecord(
            fov_id=fov1, segmentation_id=seg_id, label_value=1,
            centroid_x=10.0, centroid_y=10.0,
            bbox_x=5, bbox_y=5, bbox_w=10, bbox_h=10, area_pixels=100.0,
        )])

        assign_segmentation_to_fov(store, seg_id, fov2)

        config = store.get_fov_config(fov2)
        assert len(config) >= 1
        assert any(e.segmentation_id == seg_id for e in config)
        store.close()

    def test_dimension_mismatch_raises(self, tmp_path: Path) -> None:
        """Raise ValueError if segmentation dims don't match FOV."""
        store = ExperimentStore.create(tmp_path / "mismatch.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_condition("control")

        fov1 = store.add_fov("control", width=40, height=40)
        fov2 = store.add_fov("control", width=80, height=80)

        seg_id = store.add_segmentation(
            "seg_test", "cellular", 40, 40,
            source_fov_id=fov1, source_channel="DAPI", model_name="mock",
        )

        with pytest.raises(ValueError, match="Dimension mismatch"):
            assign_segmentation_to_fov(store, seg_id, fov2)
        store.close()

    def test_assign_same_seg_to_multiple_fovs(self, tmp_path: Path) -> None:
        """Same segmentation can be assigned to multiple FOVs."""
        store = ExperimentStore.create(tmp_path / "multi.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_condition("control")

        fov1 = store.add_fov("control", width=40, height=40)
        fov2 = store.add_fov("control", width=40, height=40)
        fov3 = store.add_fov("control", width=40, height=40)

        seg_id = store.add_segmentation(
            "seg_test", "cellular", 40, 40,
            source_fov_id=fov1, source_channel="DAPI", model_name="mock",
        )

        assign_segmentation_to_fov(store, seg_id, fov2)
        assign_segmentation_to_fov(store, seg_id, fov3)

        config2 = store.get_fov_config(fov2)
        config3 = store.get_fov_config(fov3)
        assert any(e.segmentation_id == seg_id for e in config2)
        assert any(e.segmentation_id == seg_id for e in config3)
        store.close()
