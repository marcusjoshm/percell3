"""Tests for cell group tag export integration."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from percell3.core.experiment_store import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord


@pytest.fixture
def store_with_groups(tmp_path: Path) -> ExperimentStore:
    """Experiment with cells, measurements, and group tags."""
    store = ExperimentStore.create(tmp_path / "groups.percell")
    store.add_channel("GFP")
    store.add_condition("ctrl")
    fov_id = store.add_fov("ctrl", width=128, height=128)
    seg_id = store.add_segmentation_run("GFP", "cyto3")

    # Create 4 cells
    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=i,
            centroid_x=50.0 + i * 10, centroid_y=50.0,
            bbox_x=40 + i * 10, bbox_y=40, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        )
        for i in range(1, 5)
    ]
    cell_ids = store.add_cells(cells)

    # Add measurements
    ch = store.get_channel("GFP")
    measurements = [
        MeasurementRecord(
            cell_id=cid, channel_id=ch.id, metric="mean_intensity",
            value=100.0 + cid * 10,
        )
        for cid in cell_ids
    ]
    store.add_measurements(measurements)

    # Tag cells with group tags: cells 1,2 = g1, cells 3,4 = g2
    tag_g1_id = store.add_tag("group:GFP:mean_intensity:g1")
    tag_g2_id = store.add_tag("group:GFP:mean_intensity:g2")
    store.tag_cells(cell_ids[:2], "group:GFP:mean_intensity:g1")
    store.tag_cells(cell_ids[2:], "group:GFP:mean_intensity:g2")

    store._test_cell_ids = cell_ids
    store._test_fov_id = fov_id
    yield store
    store.close()


@pytest.fixture
def store_no_groups(tmp_path: Path) -> ExperimentStore:
    """Experiment with cells and measurements but no group tags."""
    store = ExperimentStore.create(tmp_path / "nogroups.percell")
    store.add_channel("GFP")
    store.add_condition("ctrl")
    fov_id = store.add_fov("ctrl", width=128, height=128)
    seg_id = store.add_segmentation_run("GFP", "cyto3")

    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=i,
            centroid_x=50.0, centroid_y=50.0,
            bbox_x=40, bbox_y=40, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        )
        for i in range(1, 3)
    ]
    cell_ids = store.add_cells(cells)

    ch = store.get_channel("GFP")
    measurements = [
        MeasurementRecord(
            cell_id=cid, channel_id=ch.id, metric="mean_intensity",
            value=100.0,
        )
        for cid in cell_ids
    ]
    store.add_measurements(measurements)

    store._test_cell_ids = cell_ids
    yield store
    store.close()


class TestGetCellGroupTags:
    """Tests for ExperimentStore.get_cell_group_tags()."""

    def test_single_grouping_uses_simple_column(
        self, store_with_groups: ExperimentStore,
    ):
        cell_ids = store_with_groups._test_cell_ids
        tags = store_with_groups.get_cell_group_tags(cell_ids)
        assert len(tags) == 4
        # Single grouping → column name is "group"
        for cid in cell_ids[:2]:
            assert tags[cid] == {"group": "g1"}
        for cid in cell_ids[2:]:
            assert tags[cid] == {"group": "g2"}

    def test_no_groups_returns_empty(self, store_no_groups: ExperimentStore):
        cell_ids = store_no_groups._test_cell_ids
        tags = store_no_groups.get_cell_group_tags(cell_ids)
        assert tags == {}

    def test_empty_cell_ids(self, store_with_groups: ExperimentStore):
        tags = store_with_groups.get_cell_group_tags([])
        assert tags == {}

    def test_multiple_groupings_use_qualified_columns(
        self, store_with_groups: ExperimentStore,
    ):
        """When multiple (channel, metric) groupings exist, use qualified names."""
        cell_ids = store_with_groups._test_cell_ids
        # Add a second grouping on a different channel/metric
        store_with_groups.add_tag("group:RFP:area_um2:g1")
        store_with_groups.tag_cells(cell_ids[:2], "group:RFP:area_um2:g1")

        tags = store_with_groups.get_cell_group_tags(cell_ids)
        # Cells 1,2 should have two group columns
        for cid in cell_ids[:2]:
            assert "group_GFP_mean_intensity" in tags[cid]
            assert "group_RFP_area_um2" in tags[cid]


class TestGroupsInWideCsv:
    """Tests for group columns in get_measurement_pivot()."""

    def test_pivot_includes_group_column(
        self, store_with_groups: ExperimentStore,
    ):
        pivot = store_with_groups.get_measurement_pivot()
        assert "group" in pivot.columns
        g1_rows = pivot[pivot["group"] == "g1"]
        g2_rows = pivot[pivot["group"] == "g2"]
        assert len(g1_rows) == 2
        assert len(g2_rows) == 2

    def test_pivot_without_groups_has_no_group_column(
        self, store_no_groups: ExperimentStore,
    ):
        pivot = store_no_groups.get_measurement_pivot()
        assert "group" not in pivot.columns

    def test_csv_export_includes_group(
        self, store_with_groups: ExperimentStore, tmp_path: Path,
    ):
        csv_path = tmp_path / "test_export.csv"
        store_with_groups.export_csv(csv_path)
        df = pd.read_csv(csv_path)
        assert "group" in df.columns
        assert set(df["group"].unique()) == {"g1", "g2"}


class TestGroupsInPrismExport:
    """Tests for group-based column splitting in export_prism_csv()."""

    def test_prism_columns_split_by_group(
        self, store_with_groups: ExperimentStore, tmp_path: Path,
    ):
        out_dir = tmp_path / "prism_export"
        result = store_with_groups.export_prism_csv(out_dir)
        assert result["files_written"] > 0

        # Read the exported CSV
        csv_path = out_dir / "GFP" / "mean_intensity.csv"
        assert csv_path.exists()
        df = pd.read_csv(csv_path)
        # Columns should include group info
        col_names = list(df.columns)
        # Should have columns like ctrl_N1_g1 and ctrl_N1_g2
        assert any("g1" in c for c in col_names)
        assert any("g2" in c for c in col_names)

    def test_prism_no_groups_normal_columns(
        self, store_no_groups: ExperimentStore, tmp_path: Path,
    ):
        out_dir = tmp_path / "prism_export"
        result = store_no_groups.export_prism_csv(out_dir)
        if result["files_written"] > 0:
            csv_path = out_dir / "GFP" / "mean_intensity.csv"
            df = pd.read_csv(csv_path)
            # Normal column format: ctrl_N1
            col_names = list(df.columns)
            assert not any("group" in c.lower() for c in col_names)
