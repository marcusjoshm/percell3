"""Tests for assign_threshold_to_fov() core logic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.segment.viewer.copy_mask_widget import assign_threshold_to_fov


class TestAssignThresholdToFov:
    """Tests for the assign_threshold_to_fov function."""

    def test_happy_path_assign(self, tmp_path: Path) -> None:
        """Assign a threshold to a target FOV creates a config entry."""
        store = ExperimentStore.create(tmp_path / "assign.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov1 = store.add_fov("control", width=40, height=40)
        fov2 = store.add_fov("control", width=40, height=40)

        seg_id = store.add_segmentation(
            "seg_test", "cellular", 40, 40,
            source_fov_id=fov1, source_channel="DAPI", model_name="mock",
        )

        thr_id = store.add_threshold(
            "thresh_test", "otsu", 40, 40,
            source_fov_id=fov1, source_channel="GFP",
        )
        store.write_mask(np.zeros((40, 40), dtype=np.uint8), thr_id)

        assign_threshold_to_fov(store, thr_id, seg_id, fov2)

        config = store.get_fov_config(fov2)
        assert len(config) >= 1
        entry = next(e for e in config if e.segmentation_id == seg_id)
        assert entry.threshold_id == thr_id
        store.close()

    def test_dimension_mismatch_raises(self, tmp_path: Path) -> None:
        """Raise ValueError if threshold dims don't match FOV."""
        store = ExperimentStore.create(tmp_path / "mismatch.percell")
        store.add_channel("GFP")
        store.add_condition("control")

        fov1 = store.add_fov("control", width=40, height=40)
        fov2 = store.add_fov("control", width=80, height=80)

        seg_id = store.add_segmentation(
            "seg_test", "cellular", 40, 40,
            source_fov_id=fov1, source_channel="GFP", model_name="mock",
        )

        thr_id = store.add_threshold(
            "thresh_test", "otsu", 40, 40,
            source_fov_id=fov1, source_channel="GFP",
        )

        with pytest.raises(ValueError, match="Dimension mismatch"):
            assign_threshold_to_fov(store, thr_id, seg_id, fov2)
        store.close()

    def test_config_entry_includes_scopes(self, tmp_path: Path) -> None:
        """Assigned threshold should have mask_inside and mask_outside scopes."""
        store = ExperimentStore.create(tmp_path / "scopes.percell")
        store.add_channel("GFP")
        store.add_condition("control")

        fov1 = store.add_fov("control", width=40, height=40)
        fov2 = store.add_fov("control", width=40, height=40)

        seg_id = store.add_segmentation(
            "seg_test", "cellular", 40, 40,
            source_fov_id=fov1, source_channel="GFP", model_name="mock",
        )

        thr_id = store.add_threshold(
            "thresh_test", "otsu", 40, 40,
            source_fov_id=fov1, source_channel="GFP",
        )
        store.write_mask(np.zeros((40, 40), dtype=np.uint8), thr_id)

        assign_threshold_to_fov(store, thr_id, seg_id, fov2)

        config = store.get_fov_config(fov2)
        entry = next(e for e in config if e.threshold_id == thr_id)
        assert "mask_inside" in entry.scopes
        assert "mask_outside" in entry.scopes
        store.close()
