"""Tests for cellpose widget logic (no Qt required).

Tests the CellposeParams dataclass and result-handling patterns
without needing a running Qt application or napari viewer.
"""

from __future__ import annotations

import numpy as np

from percell4.viewer.cellpose_widget import CellposeParams


# ---------------------------------------------------------------------------
# CellposeParams dataclass
# ---------------------------------------------------------------------------


class TestCellposeParams:
    """Tests for the CellposeParams dataclass."""

    def test_default_values(self):
        """Default parameters should match standard cellpose defaults."""
        params = CellposeParams()

        assert params.model_name == "cyto3"
        assert params.channel_name == ""
        assert params.diameter == 30.0
        assert params.flow_threshold == 0.4
        assert params.cellprob_threshold == 0.0
        assert params.gpu is False
        assert params.extra == {}

    def test_custom_values(self):
        """Custom parameters should be stored correctly."""
        params = CellposeParams(
            model_name="nuclei",
            channel_name="DAPI",
            diameter=50.0,
            flow_threshold=0.6,
            cellprob_threshold=-2.0,
            gpu=True,
        )

        assert params.model_name == "nuclei"
        assert params.channel_name == "DAPI"
        assert params.diameter == 50.0
        assert params.flow_threshold == 0.6
        assert params.cellprob_threshold == -2.0
        assert params.gpu is True

    def test_extra_dict_independent(self):
        """Each instance should get its own extra dict."""
        p1 = CellposeParams()
        p2 = CellposeParams()

        p1.extra["foo"] = "bar"
        assert "foo" not in p2.extra

    def test_all_builtin_model_names(self):
        """Should accept all known builtin model names."""
        for model in ["cpsam", "cyto3", "cyto2", "nuclei"]:
            params = CellposeParams(model_name=model)
            assert params.model_name == model


# ---------------------------------------------------------------------------
# Mock segmentation result handling
# ---------------------------------------------------------------------------


class TestSegmentationResultHandling:
    """Test the logic for processing segmentation results.

    These tests validate the pure numpy operations that happen
    after cellpose returns a label array, without needing napari.
    """

    def test_cell_count_from_labels(self):
        """Count unique non-zero labels to get cell count."""
        labels = np.array([
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            [2, 2, 0, 3],
            [2, 2, 0, 3],
        ], dtype=np.int32)

        n_cells = len(np.unique(labels)) - (1 if 0 in labels else 0)
        assert n_cells == 3

    def test_cell_count_all_background(self):
        """All-zero labels should give 0 cells."""
        labels = np.zeros((10, 10), dtype=np.int32)
        n_cells = len(np.unique(labels)) - (1 if 0 in labels else 0)
        assert n_cells == 0

    def test_cell_count_no_background(self):
        """Labels with no background pixel should count all unique values."""
        labels = np.array([[1, 2], [3, 4]], dtype=np.int32)
        n_cells = len(np.unique(labels)) - (1 if 0 in labels else 0)
        assert n_cells == 4

    def test_labels_dtype_conversion(self):
        """Float labels from cellpose should convert to int32."""
        float_labels = np.array([[0.0, 1.0], [2.0, 0.0]])
        int_labels = np.asarray(float_labels, dtype=np.int32)

        assert int_labels.dtype == np.int32
        assert int_labels[0, 1] == 1
        assert int_labels[1, 0] == 2

    def test_empty_segmentation_produces_empty_labels(self):
        """Segmenter returning all-zeros is a valid (empty) result."""
        labels = np.zeros((100, 100), dtype=np.int32)
        unique = np.unique(labels)
        assert len(unique) == 1
        assert unique[0] == 0
