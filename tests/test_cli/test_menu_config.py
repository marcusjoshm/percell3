"""Tests for Phase 6: CLI Configuration Manager (layer-based)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from percell3.core.experiment_store import ExperimentStore
from percell3.segment.label_processor import extract_cells


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def config_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with 2 FOVs, 1 cellular seg, and measurements.

    Creates:
      - 2 channels (DAPI, GFP)
      - 1 condition (ctrl)
      - 2 FOVs (64x64)
      - 1 cellular segmentation on fov_1
      - Cells extracted from labels
    """
    store = ExperimentStore.create(tmp_path / "config.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("ctrl")

    # FOV 1
    fov1_id = store.add_fov("ctrl", width=64, height=64, pixel_size_um=0.65,
                             display_name="fov_001")
    img = np.full((64, 64), 100, dtype=np.uint16)
    store.write_image(fov1_id, "DAPI", img)
    store.write_image(fov1_id, "GFP", img)

    # FOV 2
    fov2_id = store.add_fov("ctrl", width=64, height=64, pixel_size_um=0.65,
                             display_name="fov_002")
    store.write_image(fov2_id, "DAPI", img)
    store.write_image(fov2_id, "GFP", img)

    # Create cellular segmentation on fov_1
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[5:25, 5:25] = 1
    labels[30:50, 30:50] = 2

    seg_id = store.add_segmentation(
        "cellpose_DAPI_1", "cellular", 64, 64,
        source_fov_id=fov1_id, source_channel="DAPI",
        model_name="cyto3", parameters={},
    )
    store.write_labels(labels, seg_id)
    cells = extract_cells(labels, fov1_id, seg_id, 0.65)
    store.add_cells(cells)
    store.update_segmentation_cell_count(seg_id, len(cells))

    store._test_fov1_id = fov1_id
    store._test_fov2_id = fov2_id
    store._test_seg_id = seg_id
    yield store
    store.close()


# ── MenuState mock ────────────────────────────────────────────────────

class MockMenuState:
    """Minimal MenuState for unit testing config menu handlers."""

    def __init__(self, store: ExperimentStore):
        self._store = store

    def require_experiment(self) -> ExperimentStore:
        return self._store


# ── Tests ─────────────────────────────────────────────────────────────

class TestShowConfigMatrix:
    """Tests for _show_config_matrix()."""

    def test_shows_matrix_with_entries(self, config_experiment: ExperimentStore):
        from percell3.cli.menu import _show_config_matrix
        state = MockMenuState(config_experiment)
        # Should not raise — just prints the table
        _show_config_matrix(state)

    def test_shows_empty_matrix(self, tmp_path: Path):
        from percell3.cli.menu import _show_config_matrix
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("ctrl")
        state = MockMenuState(store)
        _show_config_matrix(state)
        store.close()


class TestAssignSegmentation:
    """Tests for _assign_segmentation()."""

    @patch("percell3.cli.menu.numbered_select_one")
    @patch("percell3.cli.menu.numbered_select_many")
    @patch("percell3.measure.auto_measure.on_config_changed")
    def test_assign_seg_to_second_fov(
        self, mock_config_changed, mock_select_many, mock_select_one,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _assign_segmentation

        seg = config_experiment.get_segmentation(config_experiment._test_seg_id)
        mock_select_one.return_value = f"{seg.name} ({seg.cell_count or 0} cells, {seg.width}x{seg.height})"
        mock_select_many.return_value = ["fov_002"]

        state = MockMenuState(config_experiment)
        _assign_segmentation(state)

        # fov_002 should now have config pointing to our segmentation
        config = config_experiment.get_fov_config(config_experiment._test_fov2_id)
        assert len(config) > 0
        assert any(e.segmentation_id == config_experiment._test_seg_id for e in config)

    @patch("percell3.cli.menu.numbered_select_one")
    @patch("percell3.cli.menu.numbered_select_many")
    @patch("percell3.measure.auto_measure.on_config_changed")
    def test_assign_seg_dimension_mismatch_skipped(
        self, mock_config_changed, mock_select_many, mock_select_one,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _assign_segmentation

        # Create a FOV with different dimensions
        fov3_id = config_experiment.add_fov(
            "ctrl", width=128, height=128, pixel_size_um=0.65,
            display_name="fov_003",
        )
        img = np.full((128, 128), 100, dtype=np.uint16)
        config_experiment.write_image(fov3_id, "DAPI", img)

        seg = config_experiment.get_segmentation(config_experiment._test_seg_id)
        mock_select_one.return_value = f"{seg.name} ({seg.cell_count or 0} cells, {seg.width}x{seg.height})"
        mock_select_many.return_value = ["fov_003"]

        state = MockMenuState(config_experiment)
        _assign_segmentation(state)

        # fov_003 should NOT have our 64x64 segmentation
        config = config_experiment.get_fov_config(fov3_id)
        cellular_entries = [
            e for e in config if e.segmentation_id == config_experiment._test_seg_id
        ]
        assert len(cellular_entries) == 0


class TestAssignThreshold:
    """Tests for _assign_threshold()."""

    @patch("percell3.cli.menu.numbered_select_one")
    @patch("percell3.cli.menu.numbered_select_many")
    @patch("percell3.measure.auto_measure.on_config_changed")
    def test_assign_threshold_to_fov(
        self, mock_config_changed, mock_select_many, mock_select_one,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _assign_threshold

        store = config_experiment
        fov_id = store._test_fov1_id

        # Create a threshold
        thr_id = store.add_threshold(
            "thresh_GFP_1", "manual", 64, 64,
            source_fov_id=fov_id, source_channel="GFP",
            parameters={"value": 50.0},
        )
        mask = np.zeros((64, 64), dtype=np.uint8)
        mask[5:25, 5:25] = 255
        store.write_mask(mask, thr_id)

        thr = store.get_threshold(thr_id)
        mock_select_one.return_value = f"{thr.name} ({thr.width}x{thr.height})"
        mock_select_many.return_value = ["fov_002"]

        state = MockMenuState(store)
        _assign_threshold(state)

        # fov_002 should now have a config entry with this threshold
        config = store.get_fov_config(store._test_fov2_id)
        thr_entries = [e for e in config if e.threshold_id == thr_id]
        assert len(thr_entries) > 0


class TestRenameEntities:
    """Tests for _rename_segmentation() and _rename_threshold()."""

    @patch("percell3.cli.menu.menu_prompt")
    @patch("percell3.cli.menu.numbered_select_one")
    def test_rename_segmentation(
        self, mock_select, mock_prompt,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _rename_segmentation

        seg = config_experiment.get_segmentation(config_experiment._test_seg_id)
        mock_select.return_value = f"{seg.name} ({seg.seg_type})"
        mock_prompt.return_value = "my_custom_seg"

        state = MockMenuState(config_experiment)
        _rename_segmentation(state)

        renamed = config_experiment.get_segmentation(config_experiment._test_seg_id)
        assert renamed.name == "my_custom_seg"

    @patch("percell3.cli.menu.menu_prompt")
    @patch("percell3.cli.menu.numbered_select_one")
    def test_rename_threshold(
        self, mock_select, mock_prompt,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _rename_threshold

        store = config_experiment
        thr_id = store.add_threshold(
            "thresh_GFP_1", "manual", 64, 64,
            source_fov_id=store._test_fov1_id, source_channel="GFP",
            parameters={},
        )

        mock_select.return_value = "thresh_GFP_1"
        mock_prompt.return_value = "my_threshold"

        state = MockMenuState(store)
        _rename_threshold(state)

        renamed = store.get_threshold(thr_id)
        assert renamed.name == "my_threshold"


class TestDeleteEntities:
    """Tests for _delete_segmentation() and _delete_threshold()."""

    @patch("percell3.cli.menu.numbered_select_one")
    def test_delete_segmentation_confirmed(
        self, mock_select,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _delete_segmentation

        store = config_experiment
        seg = store.get_segmentation(store._test_seg_id)
        cell_count = seg.cell_count or 0

        # First call: select the segmentation, second call: confirm "Yes"
        mock_select.side_effect = [
            f"{seg.name} ({cell_count} cells)",
            "Yes",
        ]

        state = MockMenuState(store)
        _delete_segmentation(state)

        # Segmentation should be deleted
        with pytest.raises(Exception):
            store.get_segmentation(store._test_seg_id)

    @patch("percell3.cli.menu.numbered_select_one")
    def test_delete_segmentation_cancelled(
        self, mock_select,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _delete_segmentation

        store = config_experiment
        seg = store.get_segmentation(store._test_seg_id)
        cell_count = seg.cell_count or 0

        mock_select.side_effect = [
            f"{seg.name} ({cell_count} cells)",
            "No",
        ]

        state = MockMenuState(store)
        _delete_segmentation(state)

        # Segmentation should still exist
        seg_after = store.get_segmentation(store._test_seg_id)
        assert seg_after.name == seg.name

    @patch("percell3.cli.menu.numbered_select_one")
    def test_delete_threshold_confirmed(
        self, mock_select,
        config_experiment: ExperimentStore,
    ):
        from percell3.cli.menu import _delete_threshold

        store = config_experiment
        thr_id = store.add_threshold(
            "thresh_test", "manual", 64, 64,
            source_fov_id=store._test_fov1_id, source_channel="GFP",
            parameters={},
        )

        mock_select.side_effect = ["thresh_test", "Yes"]

        state = MockMenuState(store)
        _delete_threshold(state)

        with pytest.raises(Exception):
            store.get_threshold(thr_id)
