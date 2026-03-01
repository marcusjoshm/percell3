"""Tests for Phase 4: config management, run management, plugin input requirements."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_experiment(tmp_path: Path, name: str = "test") -> ExperimentStore:
    """Create an experiment with DAPI and GFP channels, one condition."""
    store = ExperimentStore.create(tmp_path / f"{name}.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")
    return store


def _add_fov_with_seg(
    store: ExperimentStore,
    display_name: str = "fov1",
    width: int = 40,
    height: int = 40,
) -> tuple[int, int]:
    """Add a FOV with labels (2 cells). Returns (fov_id, seg_run_id)."""
    fov_id = store.add_fov(
        "control", width=width, height=height,
        pixel_size_um=0.65, display_name=display_name,
    )

    dapi = np.full((height, width), 100, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    labels = np.zeros((height, width), dtype=np.int32)
    labels[5:20, 5:20] = 1
    labels[25:35, 25:35] = 2

    seg_run_id = store.add_segmentation_run(
        fov_id=fov_id, channel="DAPI", model_name="cyto3",
        parameters={"diameter": 30.0},
    )
    store.write_labels(fov_id, labels, seg_run_id)

    from percell3.segment.label_processor import extract_cells

    cells = extract_cells(labels, fov_id, seg_run_id, 0.65)
    if cells:
        store.add_cells(cells)
    store.update_segmentation_run_cell_count(seg_run_id, len(cells))

    return fov_id, seg_run_id


def _add_threshold_run(
    store: ExperimentStore,
    fov_id: int,
    channel: str = "GFP",
    width: int = 40,
    height: int = 40,
) -> int:
    """Add a threshold run to an existing FOV. Returns thr_run_id."""
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[10:20, 10:20] = 255
    thr_run_id = store.add_threshold_run(
        fov_id=fov_id, channel=channel, method="otsu",
        parameters={"threshold_value": 100.0},
    )
    store.write_mask(fov_id, channel, mask, thr_run_id)
    return thr_run_id


# ---------------------------------------------------------------------------
# Test: Auto-create default config
# ---------------------------------------------------------------------------


class TestAutoCreateDefaultConfig:
    """Tests for ExperimentStore.auto_create_default_config()."""

    def test_creates_config_with_entries(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id = _add_fov_with_seg(store)
        thr_id = _add_threshold_run(store, fov_id)

        config_id = store.auto_create_default_config()

        config = store.get_measurement_config(config_id)
        assert config.name == "default"
        assert config.entry_count == 1

        entries = store.get_measurement_config_entries(config_id)
        assert len(entries) == 1
        assert entries[0].fov_id == fov_id
        assert entries[0].segmentation_run_id == seg_id
        assert entries[0].threshold_run_id == thr_id

    def test_uses_latest_seg_run(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id1 = _add_fov_with_seg(store)

        # Add a second seg run
        labels = np.zeros((40, 40), dtype=np.int32)
        labels[5:20, 5:20] = 1
        seg_id2 = store.add_segmentation_run(
            fov_id=fov_id, channel="DAPI", model_name="nuclei",
            parameters={"diameter": 20.0},
        )
        store.write_labels(fov_id, labels, seg_id2)

        config_id = store.auto_create_default_config()
        entries = store.get_measurement_config_entries(config_id)
        # Should use latest seg run
        assert entries[0].segmentation_run_id == seg_id2

    def test_fov_without_seg_skipped(self, tmp_path):
        store = _create_experiment(tmp_path)
        # Add FOV without segmentation
        fov_id = store.add_fov("control", width=40, height=40, display_name="empty_fov")

        # Add another FOV with seg
        fov_id2, seg_id = _add_fov_with_seg(store, display_name="seg_fov")

        config_id = store.auto_create_default_config()
        entries = store.get_measurement_config_entries(config_id)
        # Only the segmented FOV should have an entry
        assert len(entries) == 1
        assert entries[0].fov_id == fov_id2

    def test_no_seg_runs_raises(self, tmp_path):
        store = _create_experiment(tmp_path)
        store.add_fov("control", width=40, height=40, display_name="fov1")

        with pytest.raises(ValueError, match="No segmentation runs"):
            store.auto_create_default_config()

    def test_sets_active_config(self, tmp_path):
        store = _create_experiment(tmp_path)
        _add_fov_with_seg(store)

        config_id = store.auto_create_default_config()
        assert store.get_active_measurement_config_id() == config_id

    def test_multiple_threshold_runs_per_fov(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id = _add_fov_with_seg(store)
        thr_id1 = _add_threshold_run(store, fov_id, "GFP")
        thr_id2 = _add_threshold_run(store, fov_id, "GFP")

        config_id = store.auto_create_default_config()
        entries = store.get_measurement_config_entries(config_id)
        # Should have one entry per threshold run
        assert len(entries) == 2
        thr_ids = {e.threshold_run_id for e in entries}
        assert thr_ids == {thr_id1, thr_id2}


# ---------------------------------------------------------------------------
# Test: Config entry removal
# ---------------------------------------------------------------------------


class TestRemoveMeasurementConfigEntry:
    """Tests for ExperimentStore.remove_measurement_config_entry()."""

    def test_removes_entry(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id = _add_fov_with_seg(store)

        config_id = store.create_measurement_config("test")
        entry_id = store.add_measurement_config_entry(config_id, fov_id, seg_id)

        store.remove_measurement_config_entry(entry_id)
        entries = store.get_measurement_config_entries(config_id)
        assert len(entries) == 0


# ---------------------------------------------------------------------------
# Test: Run rename validation
# ---------------------------------------------------------------------------


class TestRunRenameValidation:
    """Tests for run rename with UNIQUE constraint."""

    def test_rename_segmentation_run(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id = _add_fov_with_seg(store)

        store.rename_segmentation_run(seg_id, "my_custom_run")
        runs = store.list_segmentation_runs(fov_id)
        assert runs[0].name == "my_custom_run"

    def test_rename_threshold_run(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id = _add_fov_with_seg(store)
        thr_id = _add_threshold_run(store, fov_id)

        store.rename_threshold_run(thr_id, "custom_threshold")
        runs = store.list_threshold_runs(fov_id=fov_id)
        assert runs[0].name == "custom_threshold"

    def test_rename_seg_run_duplicate_raises(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id1 = _add_fov_with_seg(store)

        # Add second seg run
        seg_id2 = store.add_segmentation_run(
            fov_id=fov_id, channel="DAPI", model_name="nuclei",
            parameters={},
        )

        # Get the auto-generated name of first run
        runs = store.list_segmentation_runs(fov_id)
        first_name = runs[0].name

        # Try to rename second to same name as first — should fail
        with pytest.raises(Exception):
            store.rename_segmentation_run(seg_id2, first_name)


# ---------------------------------------------------------------------------
# Test: Plugin input requirements
# ---------------------------------------------------------------------------


class TestPluginInputRequirements:
    """Tests for PluginInputRequirement framework."""

    def test_base_class_returns_empty(self):
        """AnalysisPlugin.required_inputs() defaults to empty."""
        from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult

        class DummyPlugin(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="test", version="1.0", description="test")

            def validate(self, store):
                return []

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                return PluginResult(measurements_written=0, cells_processed=0)

        plugin = DummyPlugin()
        assert plugin.required_inputs() == []

    def test_input_kind_enum(self):
        from percell3.plugins.base import InputKind

        assert InputKind.SEGMENTATION == "segmentation"
        assert InputKind.THRESHOLD == "threshold"

    def test_split_halo_declares_inputs(self):
        from percell3.plugins.builtin.split_halo_condensate_analysis import (
            SplitHaloCondensateAnalysisPlugin,
        )
        from percell3.plugins.base import InputKind

        plugin = SplitHaloCondensateAnalysisPlugin()
        inputs = plugin.required_inputs()
        assert len(inputs) == 2
        kinds = {inp.kind for inp in inputs}
        assert InputKind.SEGMENTATION in kinds
        assert InputKind.THRESHOLD in kinds

    def test_local_bg_declares_inputs(self):
        from percell3.plugins.builtin.local_bg_subtraction import (
            LocalBGSubtractionPlugin,
        )
        from percell3.plugins.base import InputKind

        plugin = LocalBGSubtractionPlugin()
        inputs = plugin.required_inputs()
        assert len(inputs) == 2
        kinds = {inp.kind for inp in inputs}
        assert InputKind.SEGMENTATION in kinds
        assert InputKind.THRESHOLD in kinds

    def test_requirement_channel_filter(self):
        from percell3.plugins.base import InputKind, PluginInputRequirement

        req = PluginInputRequirement(kind=InputKind.THRESHOLD, channel="GFP")
        assert req.channel == "GFP"
        assert req.kind == InputKind.THRESHOLD


# ---------------------------------------------------------------------------
# Test: Delete cascade with cell_tags
# ---------------------------------------------------------------------------


class TestDeleteCascade:
    """Tests for delete operations with cascade behavior."""

    def test_delete_segmentation_run_with_measurements(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id = _add_fov_with_seg(store)

        # Add measurements
        cells = store.get_cells(fov_id=fov_id)
        cell_ids = cells["id"].tolist()
        ch = store.get_channels()
        measurements = [
            MeasurementRecord(
                cell_id=cell_ids[0],
                channel_id=ch[0].id,
                metric="mean_intensity",
                value=100.0,
            ),
        ]
        store.add_measurements(measurements)

        # Verify impact
        impact = store.get_segmentation_run_impact(seg_id)
        assert impact.cells == 2
        assert impact.measurements >= 1

        # Delete
        store.delete_segmentation_run(seg_id)

        # Verify cells gone
        cells_after = store.get_cells(fov_id=fov_id)
        assert len(cells_after) == 0

    def test_delete_threshold_run_with_config_entries(self, tmp_path):
        store = _create_experiment(tmp_path)
        fov_id, seg_id = _add_fov_with_seg(store)
        thr_id = _add_threshold_run(store, fov_id)

        # Create config with this threshold run
        config_id = store.create_measurement_config("test")
        store.add_measurement_config_entry(config_id, fov_id, seg_id, thr_id)

        # Verify impact
        impact = store.get_threshold_run_impact(thr_id)
        assert impact.config_entries == 1

        # Delete
        store.delete_threshold_run(thr_id)

        # Verify config entry removed
        entries = store.get_measurement_config_entries(config_id)
        assert len(entries) == 0


# ---------------------------------------------------------------------------
# Test: Measurement config with no config auto-creation
# ---------------------------------------------------------------------------


class TestMeasurementConfigFlow:
    """Tests for measurement config creation and switching."""

    def test_create_and_list_configs(self, tmp_path):
        store = _create_experiment(tmp_path)

        config_id1 = store.create_measurement_config("config_a")
        config_id2 = store.create_measurement_config("config_b")

        configs = store.list_measurement_configs()
        assert len(configs) == 2
        names = {c.name for c in configs}
        assert names == {"config_a", "config_b"}

    def test_set_and_get_active_config(self, tmp_path):
        store = _create_experiment(tmp_path)

        config_id1 = store.create_measurement_config("first")
        config_id2 = store.create_measurement_config("second")

        # Most recently created is auto-active
        assert store.get_active_measurement_config_id() == config_id2

        # Switch back
        store.set_active_measurement_config(config_id1)
        assert store.get_active_measurement_config_id() == config_id1

    def test_delete_active_config_clears_active(self, tmp_path):
        store = _create_experiment(tmp_path)

        config_id = store.create_measurement_config("temp")
        assert store.get_active_measurement_config_id() == config_id

        store.delete_measurement_config(config_id)
        assert store.get_active_measurement_config_id() is None

    def test_duplicate_config_name_raises(self, tmp_path):
        from percell3.core.exceptions import DuplicateError

        store = _create_experiment(tmp_path)
        store.create_measurement_config("unique_name")

        with pytest.raises(DuplicateError):
            store.create_measurement_config("unique_name")

    def test_config_entry_validation_cross_fov(self, tmp_path):
        """Threshold run must belong to same FOV as the config entry."""
        store = _create_experiment(tmp_path)
        fov_id1, seg_id1 = _add_fov_with_seg(store, display_name="fov1")
        fov_id2, seg_id2 = _add_fov_with_seg(store, display_name="fov2")
        thr_id = _add_threshold_run(store, fov_id1)

        config_id = store.create_measurement_config("test")

        # Adding thr_id (belongs to fov1) to fov2's entry should fail
        with pytest.raises(ValueError, match="belongs to FOV"):
            store.add_measurement_config_entry(config_id, fov_id2, seg_id2, thr_id)
