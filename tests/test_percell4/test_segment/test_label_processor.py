"""Tests for percell4.segment.label_processor — pure numpy ROI extraction."""

from __future__ import annotations

import numpy as np
import pytest

from percell4.segment.label_processor import (
    extract_rois,
    filter_edge_rois,
    filter_small_rois,
)


def _make_synthetic_labels() -> np.ndarray:
    """Create a 100x100 label image with 3 labeled regions.

    Region 1: 20x20 block at (10,10)-(30,30) — area 400, not touching edge
    Region 2: 15x15 block at (50,50)-(65,65) — area 225, not touching edge
    Region 3: 10x10 block at (0,80)-(10,90) — area 100, touching top edge
    """
    labels = np.zeros((100, 100), dtype=np.int32)
    labels[10:30, 10:30] = 1   # 20x20 = 400 px
    labels[50:65, 50:65] = 2   # 15x15 = 225 px
    labels[0:10, 80:90] = 3    # 10x10 = 100 px, touches top edge
    return labels


class TestExtractRois:
    """Tests for extract_rois()."""

    def test_extract_rois_from_synthetic_labels(self) -> None:
        """Extracts 3 ROIs with correct properties."""
        labels = _make_synthetic_labels()
        rois = extract_rois(labels)

        assert len(rois) == 3

        # Sort by label_id for deterministic checks
        rois_by_id = {r["label_id"]: r for r in rois}

        # Region 1
        r1 = rois_by_id[1]
        assert r1["bbox_y"] == 10
        assert r1["bbox_x"] == 10
        assert r1["bbox_h"] == 20
        assert r1["bbox_w"] == 20
        assert r1["area_px"] == 400

        # Region 2
        r2 = rois_by_id[2]
        assert r2["bbox_y"] == 50
        assert r2["bbox_x"] == 50
        assert r2["bbox_h"] == 15
        assert r2["bbox_w"] == 15
        assert r2["area_px"] == 225

        # Region 3 (edge)
        r3 = rois_by_id[3]
        assert r3["bbox_y"] == 0
        assert r3["bbox_x"] == 80
        assert r3["bbox_h"] == 10
        assert r3["bbox_w"] == 10
        assert r3["area_px"] == 100

    def test_min_area_filtering(self) -> None:
        """ROIs below min_area are excluded."""
        labels = _make_synthetic_labels()
        rois = extract_rois(labels, min_area=200)

        assert len(rois) == 2
        ids = {r["label_id"] for r in rois}
        assert 1 in ids  # 400 px
        assert 2 in ids  # 225 px
        assert 3 not in ids  # 100 px, filtered out

    def test_exclude_edge_rois(self) -> None:
        """Edge-touching ROIs are excluded when exclude_edge=True."""
        labels = _make_synthetic_labels()
        rois = extract_rois(labels, exclude_edge=True)

        assert len(rois) == 2
        ids = {r["label_id"] for r in rois}
        assert 1 in ids
        assert 2 in ids
        assert 3 not in ids  # touches top edge

    def test_exclude_edge_and_min_area(self) -> None:
        """Both filters applied together."""
        labels = _make_synthetic_labels()
        rois = extract_rois(labels, min_area=300, exclude_edge=True)

        assert len(rois) == 1
        assert rois[0]["label_id"] == 1

    def test_empty_image_returns_empty(self) -> None:
        """All-zero label image returns empty list."""
        labels = np.zeros((100, 100), dtype=np.int32)
        rois = extract_rois(labels)
        assert rois == []

    def test_non_2d_raises(self) -> None:
        """3D input raises ValueError."""
        labels = np.zeros((10, 10, 3), dtype=np.int32)
        with pytest.raises(ValueError, match="2D"):
            extract_rois(labels)


class TestFilterEdgeRois:
    """Tests for filter_edge_rois()."""

    def test_removes_edge_touching(self) -> None:
        labels = _make_synthetic_labels()
        filtered, count = filter_edge_rois(labels)
        assert count == 1  # region 3 touches top edge
        assert filtered[5, 85] == 0  # region 3 zeroed

    def test_with_margin(self) -> None:
        labels = _make_synthetic_labels()
        # With margin=11, region 1 at row 10 is within margin
        filtered, count = filter_edge_rois(labels, edge_margin=11)
        assert count >= 2  # at least regions 1 and 3

    def test_empty_image(self) -> None:
        labels = np.zeros((50, 50), dtype=np.int32)
        filtered, count = filter_edge_rois(labels)
        assert count == 0
        np.testing.assert_array_equal(filtered, labels)


class TestFilterSmallRois:
    """Tests for filter_small_rois()."""

    def test_removes_small(self) -> None:
        labels = _make_synthetic_labels()
        filtered, count = filter_small_rois(labels, min_area=200)
        assert count == 1  # region 3 has 100 px
        assert filtered[5, 85] == 0  # region 3 zeroed
        assert filtered[15, 15] == 1  # region 1 preserved

    def test_none_removed_if_all_large(self) -> None:
        labels = _make_synthetic_labels()
        filtered, count = filter_small_rois(labels, min_area=10)
        assert count == 0

    def test_empty_image(self) -> None:
        labels = np.zeros((50, 50), dtype=np.int32)
        filtered, count = filter_small_rois(labels, min_area=100)
        assert count == 0
