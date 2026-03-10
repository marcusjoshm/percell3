"""Tests for measurement overlay pure functions (no Qt or napari required)."""

from __future__ import annotations

import numpy as np

from percell4.core.db_types import new_uuid
from percell4.viewer._viewer import build_viewer_title
from percell4.viewer.measurement_widget import (
    build_measurement_lookup,
    compute_roi_centroids,
    map_values_to_colors,
)


# ---------------------------------------------------------------------------
# build_measurement_lookup
# ---------------------------------------------------------------------------


def test_build_measurement_lookup_maps_labels():
    """Lookup should map label_id -> measurement value for matching ROIs."""
    roi1_id = new_uuid()
    roi2_id = new_uuid()
    roi3_id = new_uuid()

    rois = [
        {"id": roi1_id, "label_id": 1},
        {"id": roi2_id, "label_id": 2},
        {"id": roi3_id, "label_id": 3},
    ]
    measurements = [
        {"roi_id": roi1_id, "value": 100.0},
        {"roi_id": roi2_id, "value": 200.0},
        {"roi_id": roi3_id, "value": 300.0},
    ]

    lookup = build_measurement_lookup(measurements, rois)

    assert lookup == {1: 100.0, 2: 200.0, 3: 300.0}


def test_build_measurement_lookup_empty():
    """Empty inputs should return an empty dict."""
    assert build_measurement_lookup([], []) == {}
    assert build_measurement_lookup([], [{"id": new_uuid(), "label_id": 1}]) == {}
    assert build_measurement_lookup([{"roi_id": new_uuid(), "value": 1.0}], []) == {}


def test_build_measurement_lookup_ignores_label_zero():
    """ROIs with label_id == 0 (background) should be excluded."""
    roi_id = new_uuid()
    rois = [{"id": roi_id, "label_id": 0}]
    measurements = [{"roi_id": roi_id, "value": 42.0}]

    lookup = build_measurement_lookup(measurements, rois)
    assert lookup == {}


def test_build_measurement_lookup_unmatched_roi():
    """Measurements for ROIs not in the rois list should be ignored."""
    roi_id = new_uuid()
    other_id = new_uuid()
    rois = [{"id": roi_id, "label_id": 5}]
    measurements = [{"roi_id": other_id, "value": 99.0}]

    lookup = build_measurement_lookup(measurements, rois)
    assert lookup == {}


# ---------------------------------------------------------------------------
# compute_roi_centroids
# ---------------------------------------------------------------------------


def test_compute_roi_centroids_returns_centers():
    """Centroid of a single square region should be at its center."""
    labels = np.zeros((10, 10), dtype=np.int32)
    labels[2:5, 3:7] = 1  # 3x4 block centered at (3, 5)

    centroids = compute_roi_centroids(labels)

    assert 1 in centroids
    y, x = centroids[1]
    assert abs(y - 3.0) < 0.5
    assert abs(x - 4.5) < 0.5


def test_compute_roi_centroids_multiple_rois():
    """Should return centroids for multiple distinct ROIs."""
    labels = np.zeros((20, 20), dtype=np.int32)
    labels[0:4, 0:4] = 1    # top-left block
    labels[10:14, 10:14] = 2  # bottom-right block

    centroids = compute_roi_centroids(labels)

    assert len(centroids) == 2
    assert 1 in centroids
    assert 2 in centroids

    y1, x1 = centroids[1]
    assert abs(y1 - 1.5) < 0.5
    assert abs(x1 - 1.5) < 0.5

    y2, x2 = centroids[2]
    assert abs(y2 - 11.5) < 0.5
    assert abs(x2 - 11.5) < 0.5


def test_compute_roi_centroids_excludes_background():
    """Background (label 0) should not appear in centroids."""
    labels = np.zeros((10, 10), dtype=np.int32)
    labels[2:4, 2:4] = 1

    centroids = compute_roi_centroids(labels)

    assert 0 not in centroids
    assert 1 in centroids


def test_compute_roi_centroids_empty_labels():
    """All-zero labels should return empty dict."""
    labels = np.zeros((10, 10), dtype=np.int32)
    centroids = compute_roi_centroids(labels)
    assert centroids == {}


# ---------------------------------------------------------------------------
# map_values_to_colors
# ---------------------------------------------------------------------------


def test_map_values_to_colors_shape():
    """Output RGBA array should match the labels shape with 4 channels."""
    labels = np.zeros((20, 30), dtype=np.int32)
    labels[0:5, 0:5] = 1
    labels[10:15, 10:15] = 2

    lookup = {1: 0.0, 2: 1.0}
    rgba = map_values_to_colors(lookup, labels)

    assert rgba.shape == (20, 30, 4)
    assert rgba.dtype == np.float32


def test_map_values_to_colors_background_transparent():
    """Background pixels (label 0) should be fully transparent."""
    labels = np.zeros((10, 10), dtype=np.int32)
    labels[2:4, 2:4] = 1

    lookup = {1: 0.5}
    rgba = map_values_to_colors(lookup, labels)

    # Background alpha should be 0
    assert rgba[0, 0, 3] == 0.0
    # Labeled region alpha should be > 0
    assert rgba[2, 2, 3] > 0.0


def test_map_values_to_colors_empty_lookup():
    """Empty lookup should return all-zero RGBA."""
    labels = np.zeros((5, 5), dtype=np.int32)
    labels[1:3, 1:3] = 1

    rgba = map_values_to_colors({}, labels)

    assert np.all(rgba == 0.0)


def test_map_values_to_colors_single_value():
    """Single-value lookup should still produce colored output."""
    labels = np.zeros((5, 5), dtype=np.int32)
    labels[1:3, 1:3] = 1

    lookup = {1: 42.0}
    rgba = map_values_to_colors(lookup, labels)

    # Labeled pixels should have non-zero RGBA
    assert rgba[1, 1, 3] > 0.0
    # Background should remain transparent
    assert rgba[0, 0, 3] == 0.0


# ---------------------------------------------------------------------------
# build_viewer_title (from _viewer.py)
# ---------------------------------------------------------------------------


def test_build_viewer_title_basic():
    """Title should include FOV name, status, and ROI count."""
    title = build_viewer_title(
        fov_name="fov_001",
        status="measured",
        condition_name=None,
        n_rois=42,
        pixel_size_um=None,
    )
    assert "fov_001" in title
    assert "[measured]" in title
    assert "42 ROIs" in title


def test_build_viewer_title_with_condition():
    """Title should include condition name when provided."""
    title = build_viewer_title(
        fov_name="fov_001",
        status="imported",
        condition_name="control",
        n_rois=10,
        pixel_size_um=None,
    )
    assert "control" in title


def test_build_viewer_title_with_pixel_size():
    """Title should include pixel size when available."""
    title = build_viewer_title(
        fov_name="fov_001",
        status="segmented",
        condition_name=None,
        n_rois=5,
        pixel_size_um=0.325,
    )
    assert "0.325 um/px" in title


def test_build_viewer_title_full():
    """Title with all fields should include all parts separated by pipes."""
    title = build_viewer_title(
        fov_name="fov_002",
        status="measured",
        condition_name="treated",
        n_rois=100,
        pixel_size_um=0.108,
    )
    assert "fov_002 [measured]" in title
    assert "treated" in title
    assert "100 ROIs" in title
    assert "0.108 um/px" in title
    # Verify pipe-separated structure
    assert " | " in title
