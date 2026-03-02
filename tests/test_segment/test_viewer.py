"""Tests for the napari viewer integration (Module 3b).

Since napari is an optional dependency that may not be installed in the
test environment, these tests mock the napari layer and viewer APIs.
The save-back logic (save_edited_labels) is tested against a real
ExperimentStore without needing napari at all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from percell3.core import ExperimentStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def experiment_with_segmentation(tmp_path: Path) -> ExperimentStore:
    """Experiment with 1 FOV, DAPI channel, and existing segmentation."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("DAPI", role="segmentation", color="#0000FF")
    store.add_channel("GFP", role="measurement", color="#00FF00")
    store.add_condition("control")
    fov_id = store.add_fov("control", width=64, height=64, pixel_size_um=0.65)

    image = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
    store.write_image(fov_id, "DAPI", image)
    store.write_image(fov_id, "GFP", image)

    # Add a segmentation run with labels
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[10:30, 10:30] = 1  # Cell 1
    labels[35:55, 35:55] = 2  # Cell 2

    seg_id = store.add_segmentation(
        "seg_test", "cellular", 64, 64,
        source_fov_id=fov_id, source_channel="DAPI", model_name="cpsam",
        parameters={"model": "cpsam"},
    )
    store.write_labels(labels, seg_id)

    from percell3.segment.label_processor import extract_cells

    cells = extract_cells(labels, fov_id, seg_id, pixel_size_um=0.65)
    store.add_cells(cells)
    store.update_segmentation_cell_count(seg_id, len(cells))

    store._test_fov_id = fov_id
    store._test_seg_id = seg_id
    yield store
    store.close()


@pytest.fixture
def experiment_no_segmentation(tmp_path: Path) -> ExperimentStore:
    """Experiment with 1 FOV, DAPI channel, but no segmentation."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("DAPI", role="segmentation", color="#0000FF")
    store.add_condition("control")
    fov_id = store.add_fov("control", width=64, height=64, pixel_size_um=0.65)

    image = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
    store.write_image(fov_id, "DAPI", image)

    store._test_fov_id = fov_id
    yield store
    store.close()


def _get_fov_info(store: ExperimentStore):
    """Helper to get FovInfo for the test FOV."""
    return store.get_fov_by_id(store._test_fov_id)


# ---------------------------------------------------------------------------
# NAPARI_AVAILABLE flag
# ---------------------------------------------------------------------------


class TestNapariAvailability:
    def test_flag_reflects_importability(self) -> None:
        """NAPARI_AVAILABLE should be a bool based on whether napari can be imported."""
        from percell3.segment.viewer import NAPARI_AVAILABLE

        assert isinstance(NAPARI_AVAILABLE, bool)

    def test_launch_viewer_raises_when_napari_missing(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """launch_viewer() should raise ImportError when napari is absent."""
        from percell3.segment.viewer import launch_viewer

        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", False):
            with pytest.raises(ImportError, match="napari is required"):
                launch_viewer(
                    experiment_with_segmentation,
                    experiment_with_segmentation._test_fov_id,
                )


# ---------------------------------------------------------------------------
# Colormap selection
# ---------------------------------------------------------------------------


class TestChannelColormap:
    def test_blue_hex_color(self) -> None:
        from percell3.segment.viewer._viewer import _channel_colormap
        from percell3.core.models import ChannelConfig

        ch = ChannelConfig(id=1, name="DAPI", color="#0000FF")
        assert _channel_colormap(ch) == "blue"

    def test_green_hex_color(self) -> None:
        from percell3.segment.viewer._viewer import _channel_colormap
        from percell3.core.models import ChannelConfig

        ch = ChannelConfig(id=2, name="GFP", color="#00FF00")
        assert _channel_colormap(ch) == "green"

    def test_red_hex_color(self) -> None:
        from percell3.segment.viewer._viewer import _channel_colormap
        from percell3.core.models import ChannelConfig

        ch = ChannelConfig(id=3, name="RFP", color="#FF0000")
        assert _channel_colormap(ch) == "red"

    def test_name_fallback_dapi(self) -> None:
        from percell3.segment.viewer._viewer import _channel_colormap
        from percell3.core.models import ChannelConfig

        ch = ChannelConfig(id=1, name="DAPI", color=None)
        assert _channel_colormap(ch) == "blue"

    def test_name_fallback_gfp(self) -> None:
        from percell3.segment.viewer._viewer import _channel_colormap
        from percell3.core.models import ChannelConfig

        ch = ChannelConfig(id=2, name="GFP-channel", color=None)
        assert _channel_colormap(ch) == "green"

    def test_unknown_defaults_to_gray(self) -> None:
        from percell3.segment.viewer._viewer import _channel_colormap
        from percell3.core.models import ChannelConfig

        ch = ChannelConfig(id=4, name="CustomChannel", color="#123456")
        assert _channel_colormap(ch) == "gray"


# ---------------------------------------------------------------------------
# Save-back logic (save_edited_labels)
# ---------------------------------------------------------------------------


class TestSaveEditedLabels:
    def test_save_returns_run_id(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """Modified labels should be saved and return a new run_id."""
        from percell3.segment.viewer._viewer import save_edited_labels

        edited = np.zeros((64, 64), dtype=np.int32)
        edited[5:25, 5:25] = 1
        edited[30:50, 30:50] = 2
        edited[40:60, 10:30] = 3  # New cell

        fov_info = _get_fov_info(experiment_with_segmentation)
        run_id = save_edited_labels(
            experiment_with_segmentation,
            fov_info, edited,
            segmentation_id=experiment_with_segmentation._test_seg_id,
            channel="DAPI",
        )
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_round_trip_labels_match(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """Labels read back from zarr should match what was saved."""
        from percell3.segment.viewer._viewer import save_edited_labels

        store = experiment_with_segmentation
        edited = np.zeros((64, 64), dtype=np.int32)
        edited[10:30, 10:30] = 1
        edited[35:55, 35:55] = 2

        fov_info = _get_fov_info(store)
        run_id = save_edited_labels(
            store, fov_info, edited,
            segmentation_id=store._test_seg_id, channel="DAPI",
        )

        read_back = store.read_labels(run_id)
        np.testing.assert_array_equal(read_back, edited)

    def test_cell_count_matches_unique_labels(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """Number of cells in DB should match unique non-zero labels."""
        from percell3.segment.viewer._viewer import save_edited_labels

        edited = np.zeros((64, 64), dtype=np.int32)
        edited[5:20, 5:20] = 1
        edited[25:40, 25:40] = 2
        edited[45:60, 45:60] = 3

        fov_info = _get_fov_info(experiment_with_segmentation)
        run_id = save_edited_labels(
            experiment_with_segmentation,
            fov_info, edited,
            segmentation_id=experiment_with_segmentation._test_seg_id,
            channel="DAPI",
        )

        segs = experiment_with_segmentation.get_segmentations()
        new_seg = [s for s in segs if s.id == run_id][0]
        assert new_seg.cell_count == 3

    def test_cell_properties_correct(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """Cell area should match the painted region."""
        from percell3.segment.viewer._viewer import save_edited_labels

        store = experiment_with_segmentation
        edited = np.zeros((64, 64), dtype=np.int32)
        edited[10:40, 10:40] = 1  # 30x30 = 900 pixels

        fov_info = _get_fov_info(store)
        run_id = save_edited_labels(
            store, fov_info, edited,
            segmentation_id=None, channel="DAPI",
        )

        cells_df = store.get_cells(fov_id=store._test_fov_id)
        # Filter to just the new run's cells
        new_cells = cells_df[cells_df["segmentation_id"] == run_id]
        assert len(new_cells) == 1
        assert new_cells.iloc[0]["area_pixels"] == 900.0

    def test_empty_labels_create_run_with_zero_cells(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """All-zero labels should create a run with 0 cells."""
        from percell3.segment.viewer._viewer import save_edited_labels

        empty = np.zeros((64, 64), dtype=np.int32)

        fov_info = _get_fov_info(experiment_with_segmentation)
        run_id = save_edited_labels(
            experiment_with_segmentation,
            fov_info, empty,
            segmentation_id=experiment_with_segmentation._test_seg_id,
            channel="DAPI",
        )

        segs = experiment_with_segmentation.get_segmentations()
        new_seg = [s for s in segs if s.id == run_id][0]
        assert new_seg.cell_count == 0

    def test_overwrite_preserves_segmentation_id(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """Overwriting existing labels returns the same segmentation_id."""
        from percell3.segment.viewer._viewer import save_edited_labels

        store = experiment_with_segmentation
        edited = np.zeros((64, 64), dtype=np.int32)
        edited[10:30, 10:30] = 1

        fov_info = _get_fov_info(store)
        seg_id = save_edited_labels(
            store, fov_info, edited,
            segmentation_id=store._test_seg_id,
            channel="DAPI",
        )

        # Overwrite returns the same segmentation_id
        assert seg_id == store._test_seg_id

        # Labels should be updated
        read_back = store.read_labels(seg_id)
        np.testing.assert_array_equal(read_back, edited)

    def test_invalid_3d_labels_rejected(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """3D labels should raise ValueError."""
        from percell3.segment.viewer._viewer import save_edited_labels

        fov_info = _get_fov_info(experiment_with_segmentation)
        labels_3d = np.zeros((10, 64, 64), dtype=np.int32)
        with pytest.raises(ValueError, match="2D"):
            save_edited_labels(
                experiment_with_segmentation,
                fov_info, labels_3d,
                segmentation_id=None, channel="DAPI",
            )

    def test_negative_labels_rejected(
        self, experiment_with_segmentation: ExperimentStore,
    ) -> None:
        """Labels with negative values should raise ValueError."""
        from percell3.segment.viewer._viewer import save_edited_labels

        fov_info = _get_fov_info(experiment_with_segmentation)
        labels = np.array([[-1, 0], [0, 1]], dtype=np.int32)
        with pytest.raises(ValueError, match="negative"):
            save_edited_labels(
                experiment_with_segmentation,
                fov_info, labels,
                segmentation_id=None, channel="DAPI",
            )

    def test_scratch_segmentation_created(
        self, experiment_no_segmentation: ExperimentStore,
    ) -> None:
        """Painting from scratch (segmentation_id=None) should create a new segmentation."""
        from percell3.segment.viewer._viewer import save_edited_labels

        labels = np.zeros((64, 64), dtype=np.int32)
        labels[10:30, 10:30] = 1

        fov_info = _get_fov_info(experiment_no_segmentation)
        seg_id = save_edited_labels(
            experiment_no_segmentation,
            fov_info, labels,
            segmentation_id=None, channel="DAPI",
        )

        segs = experiment_no_segmentation.get_segmentations()
        new_seg = [s for s in segs if s.id == seg_id][0]
        assert new_seg.model_name == "napari_edit"


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------


class TestChangeDetection:
    def test_identical_arrays_have_same_hash(self) -> None:
        """Hash-based change detection: identical arrays produce the same hash."""
        import hashlib

        a = np.zeros((64, 64), dtype=np.int32)
        a[10:30, 10:30] = 1
        b = a.copy()
        assert hashlib.sha256(a.tobytes()).hexdigest() == hashlib.sha256(b.tobytes()).hexdigest()

    def test_different_arrays_have_different_hash(self) -> None:
        """Hash-based change detection: different arrays produce different hashes."""
        import hashlib

        original = np.zeros((64, 64), dtype=np.int32)
        original[10:30, 10:30] = 1
        edited = original.copy()
        edited[40:50, 40:50] = 2
        assert hashlib.sha256(original.tobytes()).hexdigest() != hashlib.sha256(edited.tobytes()).hexdigest()
