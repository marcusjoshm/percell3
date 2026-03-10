"""Tests for percell4.core.experiment_db — ExperimentDB CRUD + transactions."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from percell4.core.db_types import new_uuid
from percell4.core.exceptions import InvalidStatusTransition, MergeConflictError
from percell4.core.experiment_db import ExperimentDB
from percell4.core.schema import SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Return a path to a temporary database file."""
    return tmp_path / "test_experiment.db"


@pytest.fixture()
def db(db_path: Path) -> ExperimentDB:
    """Return an open ExperimentDB instance (auto-closed after test)."""
    database = ExperimentDB(db_path)
    database.open()
    yield database
    database.close()


def _setup_experiment(db: ExperimentDB) -> bytes:
    """Insert a minimal experiment and return its ID."""
    eid = new_uuid()
    db.insert_experiment(eid, "test_experiment")
    return eid


def _setup_condition(db: ExperimentDB, eid: bytes) -> bytes:
    """Insert a minimal condition and return its ID."""
    cid = new_uuid()
    db.insert_condition(cid, eid, "control")
    return cid


def _setup_channel(db: ExperimentDB, eid: bytes, name: str = "GFP") -> bytes:
    """Insert a minimal channel and return its ID."""
    chid = new_uuid()
    db.insert_channel(chid, eid, name)
    return chid


def _setup_roi_type(
    db: ExperimentDB,
    eid: bytes,
    name: str = "cell",
    parent_type_id: bytes | None = None,
) -> bytes:
    """Insert an ROI type definition and return its ID."""
    rtid = new_uuid()
    db.insert_roi_type_definition(rtid, eid, name, parent_type_id)
    return rtid


def _setup_fov(
    db: ExperimentDB,
    eid: bytes,
    *,
    condition_id: bytes | None = None,
    status: str = "imported",
) -> bytes:
    """Insert a minimal FOV and return its ID."""
    fid = new_uuid()
    db.insert_fov(fid, eid, condition_id=condition_id, status=status)
    return fid


def _setup_pipeline_run(db: ExperimentDB) -> bytes:
    """Insert a minimal pipeline run and return its ID."""
    prid = new_uuid()
    db.insert_pipeline_run(prid, "test_op")
    return prid


def _setup_roi(
    db: ExperimentDB,
    fov_id: bytes,
    roi_type_id: bytes,
    *,
    cell_identity_id: bytes | None = None,
    parent_roi_id: bytes | None = None,
    label_id: int = 1,
) -> bytes:
    """Insert a minimal ROI and return its ID."""
    rid = new_uuid()
    db.insert_roi(
        rid, fov_id, roi_type_id, cell_identity_id, parent_roi_id,
        label_id, 0, 0, 10, 10, 100,
    )
    return rid


# ===================================================================
# 1. Connection lifecycle
# ===================================================================


class TestConnectionLifecycle:
    """Test open/close and context manager."""

    def test_open_and_close(self, db_path: Path) -> None:
        database = ExperimentDB(db_path)
        database.open()
        assert database.connection is not None
        database.close()
        assert database._conn is None

    def test_context_manager(self, db_path: Path) -> None:
        with ExperimentDB(db_path) as database:
            assert database.connection is not None
        assert database._conn is None

    def test_connection_raises_when_not_open(self, db_path: Path) -> None:
        database = ExperimentDB(db_path)
        with pytest.raises(RuntimeError, match="not open"):
            _ = database.connection

    def test_close_when_already_closed(self, db_path: Path) -> None:
        database = ExperimentDB(db_path)
        database.close()  # should not raise

    def test_schema_created_on_open(self, db: ExperimentDB) -> None:
        rows = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        table_names = {r["name"] for r in rows}
        assert "experiments" in table_names
        assert "fovs" in table_names
        assert "rois" in table_names
        assert "measurements" in table_names


# ===================================================================
# 2. Transactions
# ===================================================================


class TestTransactions:
    """Test transaction commit, rollback, and SAVEPOINT nesting."""

    def test_transaction_commits(self, db: ExperimentDB) -> None:
        eid = new_uuid()
        with db.transaction():
            db.insert_experiment(eid, "committed_exp")
        row = db.get_experiment()
        assert row is not None
        assert row["name"] == "committed_exp"

    def test_transaction_rollback_on_exception(
        self, db: ExperimentDB
    ) -> None:
        eid = new_uuid()
        with pytest.raises(ValueError):
            with db.transaction():
                db.insert_experiment(eid, "will_rollback")
                raise ValueError("force rollback")
        row = db.get_experiment()
        assert row is None

    def test_savepoint_nesting_commit(self, db: ExperimentDB) -> None:
        eid = new_uuid()
        with db.transaction():
            db.insert_experiment(eid, "outer")
            with db.transaction():
                cid = new_uuid()
                db.insert_condition(cid, eid, "inner_condition")
        # Both should be committed
        row = db.get_experiment()
        assert row is not None
        conditions = db.get_conditions(eid)
        assert len(conditions) == 1
        assert conditions[0]["name"] == "inner_condition"

    def test_savepoint_inner_rollback_preserves_outer(
        self, db: ExperimentDB
    ) -> None:
        eid = new_uuid()
        with db.transaction():
            db.insert_experiment(eid, "outer_preserved")
            with pytest.raises(ValueError):
                with db.transaction():
                    db.insert_condition(new_uuid(), eid, "will_be_rolled_back")
                    raise ValueError("inner fail")
            # Outer is still valid, inner was rolled back
        row = db.get_experiment()
        assert row is not None
        assert row["name"] == "outer_preserved"
        conditions = db.get_conditions(eid)
        assert len(conditions) == 0

    def test_multiple_savepoint_nesting(self, db: ExperimentDB) -> None:
        eid = new_uuid()
        with db.transaction():
            db.insert_experiment(eid, "deep_nesting")
            with db.transaction():
                db.insert_condition(new_uuid(), eid, "level_2")
                with db.transaction():
                    db.insert_condition(new_uuid(), eid, "level_3")
        conditions = db.get_conditions(eid)
        assert len(conditions) == 2

    def test_in_transaction_flag_reset_after_commit(
        self, db: ExperimentDB
    ) -> None:
        eid = new_uuid()
        with db.transaction():
            db.insert_experiment(eid, "test")
        assert not db._in_transaction

    def test_in_transaction_flag_reset_after_rollback(
        self, db: ExperimentDB
    ) -> None:
        with pytest.raises(ValueError):
            with db.transaction():
                raise ValueError("fail")
        assert not db._in_transaction


# ===================================================================
# 3. Experiment CRUD
# ===================================================================


class TestExperimentCRUD:
    """Test experiment insert and get."""

    def test_insert_experiment_returns_count(self, db: ExperimentDB) -> None:
        count = db.insert_experiment(new_uuid(), "exp1")
        assert count == 1

    def test_get_experiment(self, db: ExperimentDB) -> None:
        eid = new_uuid()
        with db.transaction():
            db.insert_experiment(eid, "my_experiment", config_hash="abc123")
        row = db.get_experiment()
        assert row is not None
        assert row["id"] == eid
        assert row["name"] == "my_experiment"
        assert row["schema_version"] == "5.1.0"
        assert row["config_hash"] == "abc123"

    def test_get_experiment_empty_db(self, db: ExperimentDB) -> None:
        row = db.get_experiment()
        assert row is None


# ===================================================================
# 4. Condition CRUD
# ===================================================================


class TestConditionCRUD:
    """Test condition insert and get."""

    def test_insert_and_get_condition(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cid = _setup_condition(db, eid)
        row = db.get_condition(cid)
        assert row is not None
        assert row["name"] == "control"
        assert row["experiment_id"] == eid

    def test_get_conditions(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            db.insert_condition(new_uuid(), eid, "ctrl")
            db.insert_condition(new_uuid(), eid, "treated")
        conditions = db.get_conditions(eid)
        assert len(conditions) == 2
        names = {c["name"] for c in conditions}
        assert names == {"ctrl", "treated"}

    def test_get_condition_not_found(self, db: ExperimentDB) -> None:
        row = db.get_condition(new_uuid())
        assert row is None


# ===================================================================
# 5. Bio Rep CRUD
# ===================================================================


class TestBioRepCRUD:
    """Test bio_rep insert and get."""

    def test_insert_and_get_bio_rep(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cid = _setup_condition(db, eid)
            brid = new_uuid()
            db.insert_bio_rep(brid, eid, cid, "rep_1")
        row = db.get_bio_rep(brid)
        assert row is not None
        assert row["name"] == "rep_1"
        assert row["condition_id"] == cid

    def test_get_bio_reps(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cid = _setup_condition(db, eid)
            db.insert_bio_rep(new_uuid(), eid, cid, "rep_1")
            db.insert_bio_rep(new_uuid(), eid, cid, "rep_2")
        reps = db.get_bio_reps(eid)
        assert len(reps) == 2

    def test_get_bio_rep_not_found(self, db: ExperimentDB) -> None:
        row = db.get_bio_rep(new_uuid())
        assert row is None


# ===================================================================
# 6. Channel CRUD
# ===================================================================


class TestChannelCRUD:
    """Test channel insert and get."""

    def test_insert_and_get_channel(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            chid = new_uuid()
            db.insert_channel(
                chid, eid, "DAPI", role="nuclear", color="#0000FF",
                display_order=1,
            )
        row = db.get_channel(chid)
        assert row is not None
        assert row["name"] == "DAPI"
        assert row["role"] == "nuclear"
        assert row["color"] == "#0000FF"
        assert row["display_order"] == 1

    def test_get_channels_ordered(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            db.insert_channel(new_uuid(), eid, "RFP", display_order=2)
            db.insert_channel(new_uuid(), eid, "GFP", display_order=1)
            db.insert_channel(new_uuid(), eid, "DAPI", display_order=0)
        channels = db.get_channels(eid)
        assert len(channels) == 3
        assert channels[0]["name"] == "DAPI"
        assert channels[1]["name"] == "GFP"
        assert channels[2]["name"] == "RFP"

    def test_get_channel_not_found(self, db: ExperimentDB) -> None:
        row = db.get_channel(new_uuid())
        assert row is None


# ===================================================================
# 7. Timepoint CRUD
# ===================================================================


class TestTimepointCRUD:
    """Test timepoint insert and get."""

    def test_insert_and_get_timepoints(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            db.insert_timepoint(new_uuid(), eid, "t0", time_seconds=0.0)
            db.insert_timepoint(
                new_uuid(), eid, "t1", time_seconds=60.0, display_order=1,
            )
        timepoints = db.get_timepoints(eid)
        assert len(timepoints) == 2
        assert timepoints[0]["name"] == "t0"
        assert timepoints[1]["name"] == "t1"
        assert timepoints[1]["time_seconds"] == 60.0


# ===================================================================
# 8. FOV CRUD
# ===================================================================


class TestFovCRUD:
    """Test FOV insert and get."""

    def test_insert_and_get_fov(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = new_uuid()
            db.insert_fov(
                fid, eid, status="imported", auto_name="FOV_001",
                zarr_path="images/fov001",
            )
        row = db.get_fov(fid)
        assert row is not None
        assert row["status"] == "imported"
        assert row["auto_name"] == "FOV_001"
        assert row["zarr_path"] == "images/fov001"

    def test_get_fovs(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            _setup_fov(db, eid)
            _setup_fov(db, eid)
        fovs = db.get_fovs(eid)
        assert len(fovs) == 2

    def test_get_fovs_by_status(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            _setup_fov(db, eid, status="imported")
            _setup_fov(db, eid, status="imported")
            _setup_fov(db, eid, status="segmented")
        imported = db.get_fovs_by_status(eid, "imported")
        assert len(imported) == 2
        segmented = db.get_fovs_by_status(eid, "segmented")
        assert len(segmented) == 1

    def test_get_fov_not_found(self, db: ExperimentDB) -> None:
        row = db.get_fov(new_uuid())
        assert row is None

    def test_fov_with_derivation_params(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            parent_fov = _setup_fov(db, eid)
            fid = new_uuid()
            db.insert_fov(
                fid, eid,
                parent_fov_id=parent_fov,
                derivation_op="bg_subtract",
                derivation_params='{"method": "gaussian"}',
                status="imported",
            )
        row = db.get_fov(fid)
        assert row is not None
        assert row["derivation_op"] == "bg_subtract"
        assert row["derivation_params"] == '{"method": "gaussian"}'
        assert row["parent_fov_id"] == parent_fov


# ===================================================================
# 9. ROI Type Definition CRUD
# ===================================================================


class TestRoiTypeDefinitionCRUD:
    """Test ROI type definition insert and get."""

    def test_insert_and_get(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid, "cell")
        row = db.get_roi_type_definition(rtid)
        assert row is not None
        assert row["name"] == "cell"
        assert row["parent_type_id"] is None

    def test_hierarchical_types(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cell_type = _setup_roi_type(db, eid, "cell")
            particle_type = _setup_roi_type(
                db, eid, "particle", parent_type_id=cell_type,
            )
        row = db.get_roi_type_definition(particle_type)
        assert row is not None
        assert row["parent_type_id"] == cell_type

    def test_get_roi_type_definitions(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            _setup_roi_type(db, eid, "cell")
            _setup_roi_type(db, eid, "particle")
        types = db.get_roi_type_definitions(eid)
        assert len(types) == 2


# ===================================================================
# 10. Cell Identity CRUD
# ===================================================================


class TestCellIdentityCRUD:
    """Test cell identity insert and get."""

    def test_insert_and_get(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            ci_id = new_uuid()
            db.insert_cell_identity(ci_id, fid, rtid)
        row = db.get_cell_identity(ci_id)
        assert row is not None
        assert row["origin_fov_id"] == fid
        assert row["roi_type_id"] == rtid

    def test_get_cell_identity_not_found(self, db: ExperimentDB) -> None:
        row = db.get_cell_identity(new_uuid())
        assert row is None


# ===================================================================
# 11. ROI CRUD
# ===================================================================


class TestRoiCRUD:
    """Test ROI insert and get."""

    def test_insert_and_get_rois(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            rid = _setup_roi(db, fid, rtid)
        rois = db.get_rois(fid)
        assert len(rois) == 1
        assert rois[0]["id"] == rid
        assert rois[0]["label_id"] == 1
        assert rois[0]["area_px"] == 100

    def test_get_rois_by_fov_and_type(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cell_type = _setup_roi_type(db, eid, "cell")
            particle_type = _setup_roi_type(
                db, eid, "particle", parent_type_id=cell_type,
            )
            fid = _setup_fov(db, eid)
            _setup_roi(db, fid, cell_type, label_id=1)
            _setup_roi(db, fid, cell_type, label_id=2)
            _setup_roi(db, fid, particle_type, label_id=3)

        cells = db.get_rois_by_fov_and_type(fid, cell_type)
        assert len(cells) == 2
        particles = db.get_rois_by_fov_and_type(fid, particle_type)
        assert len(particles) == 1


# ===================================================================
# 12. Segmentation Set CRUD
# ===================================================================


class TestSegmentationSetCRUD:
    """Test segmentation set insert and get."""

    def test_insert_and_get(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            ssid = new_uuid()
            db.insert_segmentation_set(
                ssid, eid, rtid, "cellpose",
                source_channel="GFP",
                model_name="cyto2",
                parameters='{"diameter": 30}',
            )
        row = db.get_segmentation_set(ssid)
        assert row is not None
        assert row["seg_type"] == "cellpose"
        assert row["source_channel"] == "GFP"
        assert row["model_name"] == "cyto2"
        assert row["parameters"] == '{"diameter": 30}'

    def test_get_segmentation_set_not_found(self, db: ExperimentDB) -> None:
        row = db.get_segmentation_set(new_uuid())
        assert row is None


# ===================================================================
# 13. Threshold Mask CRUD
# ===================================================================


class TestThresholdMaskCRUD:
    """Test threshold mask insert and get."""

    def test_insert_and_get(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid)
            tmid = new_uuid()
            db.insert_threshold_mask(
                tmid, fid, "GFP",
                method="otsu", threshold_value=128.5,
            )
        masks = db.get_threshold_masks(fid)
        assert len(masks) == 1
        assert masks[0]["source_channel"] == "GFP"
        assert masks[0]["threshold_value"] == 128.5
        assert masks[0]["status"] == "pending"

    def test_threshold_mask_with_grouping(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid)
            tmid = new_uuid()
            db.insert_threshold_mask(
                tmid, fid, "GFP",
                grouping_channel="RFP",
                method="manual",
                threshold_value=200.0,
                zarr_path="masks/gfp_mask",
            )
        masks = db.get_threshold_masks(fid)
        assert masks[0]["grouping_channel"] == "RFP"
        assert masks[0]["zarr_path"] == "masks/gfp_mask"


# ===================================================================
# 14. Pipeline Run CRUD
# ===================================================================


class TestPipelineRunCRUD:
    """Test pipeline run insert and complete."""

    def test_insert_pipeline_run(self, db: ExperimentDB) -> None:
        with db.transaction():
            prid = new_uuid()
            count = db.insert_pipeline_run(prid, "segmentation")
        assert count == 1

    def test_complete_pipeline_run(self, db: ExperimentDB) -> None:
        with db.transaction():
            prid = new_uuid()
            db.insert_pipeline_run(prid, "segmentation")
        with db.transaction():
            count = db.complete_pipeline_run(prid, status="completed")
        assert count == 1
        row = db.connection.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (prid,)
        ).fetchone()
        assert row["status"] == "completed"
        assert row["completed_at"] is not None

    def test_complete_pipeline_run_failed(self, db: ExperimentDB) -> None:
        with db.transaction():
            prid = new_uuid()
            db.insert_pipeline_run(prid, "segmentation")
        with db.transaction():
            db.complete_pipeline_run(
                prid, status="failed", error_message="OOM",
            )
        row = db.connection.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (prid,)
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == "OOM"

    def test_pipeline_run_with_config(self, db: ExperimentDB) -> None:
        with db.transaction():
            prid = new_uuid()
            db.insert_pipeline_run(
                prid, "segmentation",
                config_snapshot='{"model": "cyto2"}',
            )
        row = db.connection.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (prid,)
        ).fetchone()
        assert row["config_snapshot"] == '{"model": "cyto2"}'


# ===================================================================
# 15. Measurement CRUD
# ===================================================================


class TestMeasurementCRUD:
    """Test measurement insert (single and bulk)."""

    def test_insert_measurement(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            chid = _setup_channel(db, eid)
            rid = _setup_roi(db, fid, rtid)
            prid = _setup_pipeline_run(db)
            mid = new_uuid()
            count = db.insert_measurement(
                mid, rid, chid, "mean", "whole_roi", 42.5, prid,
            )
        assert count == 1

    def test_bulk_measurement_insert(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            chid = _setup_channel(db, eid)
            rid = _setup_roi(db, fid, rtid)
            prid = _setup_pipeline_run(db)

            measurements = [
                (new_uuid(), rid, chid, "mean", "whole_roi", 42.5, prid),
                (new_uuid(), rid, chid, "max", "whole_roi", 100.0, prid),
                (new_uuid(), rid, chid, "min", "whole_roi", 5.0, prid),
            ]
            count = db.add_measurements_bulk(measurements)
        assert count == 3

    def test_bulk_measurement_empty_list(self, db: ExperimentDB) -> None:
        with db.transaction():
            count = db.add_measurements_bulk([])
        assert count == 0


# ===================================================================
# 16. Intensity Group CRUD
# ===================================================================


class TestIntensityGroupCRUD:
    """Test intensity group insert and get."""

    def test_insert_and_get(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            chid = _setup_channel(db, eid)
            prid = _setup_pipeline_run(db)
            igid = new_uuid()
            db.insert_intensity_group(
                igid, eid, "high", chid, prid,
                group_index=0, lower_bound=100.0, upper_bound=255.0,
                color_hex="#FF0000",
            )
        groups = db.get_intensity_groups(eid)
        assert len(groups) == 1
        assert groups[0]["name"] == "high"
        assert groups[0]["lower_bound"] == 100.0
        assert groups[0]["color_hex"] == "#FF0000"


# ===================================================================
# 17. Cell Group Assignment CRUD
# ===================================================================


class TestCellGroupAssignmentCRUD:
    """Test cell group assignment insert."""

    def test_insert(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            chid = _setup_channel(db, eid)
            rid = _setup_roi(db, fid, rtid)
            prid = _setup_pipeline_run(db)
            igid = new_uuid()
            db.insert_intensity_group(igid, eid, "high", chid, prid)
            cga_id = new_uuid()
            count = db.insert_cell_group_assignment(
                cga_id, igid, rid, prid,
            )
        assert count == 1


# ===================================================================
# 18. Convenience queries: get_cells, get_rois_by_type
# ===================================================================


class TestConvenienceQueries:
    """Test get_cells and get_rois_by_type."""

    def test_get_cells_filters_top_level_types(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cell_type = _setup_roi_type(db, eid, "cell")
            particle_type = _setup_roi_type(
                db, eid, "particle", parent_type_id=cell_type,
            )
            fid = _setup_fov(db, eid)
            # Insert 2 cells and 3 particles
            _setup_roi(db, fid, cell_type, label_id=1)
            _setup_roi(db, fid, cell_type, label_id=2)
            _setup_roi(db, fid, particle_type, label_id=3)
            _setup_roi(db, fid, particle_type, label_id=4)
            _setup_roi(db, fid, particle_type, label_id=5)

        cells = db.get_cells(fid)
        assert len(cells) == 2
        # All returned ROIs should be of the cell type
        for cell in cells:
            assert cell["roi_type_id"] == cell_type

    def test_get_rois_by_type_name(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cell_type = _setup_roi_type(db, eid, "cell")
            particle_type = _setup_roi_type(
                db, eid, "particle", parent_type_id=cell_type,
            )
            fid = _setup_fov(db, eid)
            _setup_roi(db, fid, cell_type, label_id=1)
            _setup_roi(db, fid, particle_type, label_id=2)
            _setup_roi(db, fid, particle_type, label_id=3)

        cells = db.get_rois_by_type(fid, "cell")
        assert len(cells) == 1
        particles = db.get_rois_by_type(fid, "particle")
        assert len(particles) == 2

    def test_get_cells_empty_fov(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid)
        cells = db.get_cells(fid)
        assert len(cells) == 0


# ===================================================================
# 19. Batch safety: _batch_in_query
# ===================================================================


class TestBatchSafety:
    """Test that IN queries are chunked to avoid SQLite's 999-param limit."""

    def test_batch_in_query_small(self, db: ExperimentDB) -> None:
        """Verify _batch_in_query works for small lists."""
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            roi_ids = []
            for i in range(5):
                rid = _setup_roi(db, fid, rtid, label_id=i + 1)
                roi_ids.append(rid)

        results = db._batch_in_query(
            "SELECT * FROM rois WHERE id IN ({placeholders})",
            (),
            roi_ids,
        )
        assert len(results) == 5

    def test_batch_in_query_over_999(self, db: ExperimentDB) -> None:
        """Insert >999 ROIs and verify batch query returns them all."""
        n = 1050  # Exceeds SQLite's 999-parameter limit
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            roi_ids = []
            for i in range(n):
                rid = new_uuid()
                db.insert_roi(
                    rid, fid, rtid, None, None,
                    i + 1, 0, 0, 10, 10, 100,
                )
                roi_ids.append(rid)

        results = db._batch_in_query(
            "SELECT * FROM rois WHERE id IN ({placeholders})",
            (),
            roi_ids,
        )
        assert len(results) == n

    def test_batch_in_query_with_params_before(
        self, db: ExperimentDB
    ) -> None:
        """Verify params_before are passed correctly."""
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            roi_ids = []
            for i in range(3):
                rid = _setup_roi(db, fid, rtid, label_id=i + 1)
                roi_ids.append(rid)

        results = db._batch_in_query(
            "SELECT * FROM rois WHERE fov_id = ? AND id IN ({placeholders})",
            (fid,),
            roi_ids,
        )
        assert len(results) == 3


# ===================================================================
# 20. Write operation return counts
# ===================================================================


class TestReturnCounts:
    """Verify all write operations return the correct rowcount."""

    def test_insert_experiment_count(self, db: ExperimentDB) -> None:
        assert db.insert_experiment(new_uuid(), "e") == 1

    def test_insert_condition_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
        assert db.insert_condition(new_uuid(), eid, "c") == 1

    def test_insert_bio_rep_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            cid = _setup_condition(db, eid)
        assert db.insert_bio_rep(new_uuid(), eid, cid, "r") == 1

    def test_insert_channel_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
        assert db.insert_channel(new_uuid(), eid, "GFP") == 1

    def test_insert_timepoint_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
        assert db.insert_timepoint(new_uuid(), eid, "t0") == 1

    def test_insert_fov_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
        assert db.insert_fov(new_uuid(), eid) == 1

    def test_insert_roi_type_definition_count(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
        assert db.insert_roi_type_definition(new_uuid(), eid, "cell") == 1

    def test_insert_cell_identity_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
        assert db.insert_cell_identity(new_uuid(), fid, rtid) == 1

    def test_insert_roi_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
        assert db.insert_roi(
            new_uuid(), fid, rtid, None, None, 1, 0, 0, 10, 10, 100,
        ) == 1

    def test_insert_segmentation_set_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
        assert db.insert_segmentation_set(
            new_uuid(), eid, rtid, "cellpose",
        ) == 1

    def test_insert_threshold_mask_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid)
        assert db.insert_threshold_mask(new_uuid(), fid, "GFP") == 1

    def test_insert_pipeline_run_count(self, db: ExperimentDB) -> None:
        assert db.insert_pipeline_run(new_uuid(), "test") == 1

    def test_complete_pipeline_run_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            prid = new_uuid()
            db.insert_pipeline_run(prid, "test")
        assert db.complete_pipeline_run(prid) == 1

    def test_insert_measurement_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            chid = _setup_channel(db, eid)
            rid = _setup_roi(db, fid, rtid)
            prid = _setup_pipeline_run(db)
        assert db.insert_measurement(
            new_uuid(), rid, chid, "mean", "whole_roi", 1.0, prid,
        ) == 1

    def test_insert_intensity_group_count(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            chid = _setup_channel(db, eid)
            prid = _setup_pipeline_run(db)
        assert db.insert_intensity_group(
            new_uuid(), eid, "high", chid, prid,
        ) == 1

    def test_insert_cell_group_assignment_count(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            rtid = _setup_roi_type(db, eid)
            fid = _setup_fov(db, eid)
            chid = _setup_channel(db, eid)
            rid = _setup_roi(db, fid, rtid)
            prid = _setup_pipeline_run(db)
            igid = new_uuid()
            db.insert_intensity_group(igid, eid, "high", chid, prid)
        assert db.insert_cell_group_assignment(
            new_uuid(), igid, rid, prid,
        ) == 1


# ===================================================================
# 21. Hexagonal boundary test
# ===================================================================


class TestHexagonalBoundary:
    """Verify experiment_db.py does not import zarr, numpy, or dask."""

    def test_no_prohibited_imports(self) -> None:
        """Parse experiment_db.py AST and check for forbidden imports."""
        source_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "src" / "percell4" / "core" / "experiment_db.py"
        )
        source = source_path.read_text()
        tree = ast.parse(source, filename=str(source_path))

        prohibited = {"zarr", "numpy", "dask", "np", "da"}
        violations: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_module = alias.name.split(".")[0]
                    if top_module in prohibited:
                        violations.append(
                            f"import {alias.name} (line {node.lineno})"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_module = node.module.split(".")[0]
                    if top_module in prohibited:
                        violations.append(
                            f"from {node.module} import ... "
                            f"(line {node.lineno})"
                        )

        assert not violations, (
            f"Hexagonal boundary violation in experiment_db.py: "
            f"{violations}"
        )


# ===================================================================
# Helper for assignment tests: full experiment scaffolding
# ===================================================================


def _setup_full_experiment(db: ExperimentDB) -> dict[str, bytes]:
    """Create a complete experiment with condition, channel, ROI type,
    FOV, segmentation set, pipeline run, and ROI.

    Returns a dict of IDs keyed by entity name.
    """
    from percell4.core.db_types import new_uuid

    eid = _setup_experiment(db)
    cid = _setup_condition(db, eid)
    ch1 = _setup_channel(db, eid, "GFP")
    ch2 = _setup_channel(db, eid, "RFP")
    rtid = _setup_roi_type(db, eid, "cell")
    fid = _setup_fov(db, eid, condition_id=cid, status="imported")
    prid = _setup_pipeline_run(db)
    ssid = new_uuid()
    db.insert_segmentation_set(ssid, eid, rtid, "cellpose")
    rid = _setup_roi(db, fid, rtid, label_id=1)
    return {
        "experiment_id": eid,
        "condition_id": cid,
        "channel_gfp": ch1,
        "channel_rfp": ch2,
        "roi_type_id": rtid,
        "fov_id": fid,
        "pipeline_run_id": prid,
        "seg_set_id": ssid,
        "roi_id": rid,
    }


# ===================================================================
# 22. Assignment methods
# ===================================================================


class TestAssignSegmentation:
    """Test assign_segmentation creates/deactivates assignments."""

    def test_new_assignment_returns_new_assignment_reason(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            results = db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
        assert len(results) == 1
        assert results[0].reason == "new_assignment"
        assert results[0].fov_id == ids["fov_id"]
        assert results[0].roi_type_id == ids["roi_type_id"]
        assert len(results[0].channel_ids) == 2  # GFP + RFP

    def test_reassignment_deactivates_old(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            # First assignment
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            # Second assignment (reassignment)
            prid2 = _setup_pipeline_run(db)
            results = db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                prid2,
            )
        assert results[0].reason == "reassignment"
        # Verify only one active assignment remains
        active = db.get_active_assignments(ids["fov_id"])
        assert len(active["segmentation"]) == 1

    def test_multiple_fovs(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            fov2 = _setup_fov(db, ids["experiment_id"], status="imported")
            results = db.assign_segmentation(
                [ids["fov_id"], fov2],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
        assert len(results) == 2
        assert results[0].fov_id == ids["fov_id"]
        assert results[1].fov_id == fov2


class TestAssignMask:
    """Test assign_mask creates/deactivates mask assignments."""

    def test_new_mask_assignment(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            tmid = new_uuid()
            db.insert_threshold_mask(tmid, ids["fov_id"], "GFP")
            # Assign segmentation first (needed for roi_type_id lookup)
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            results = db.assign_mask(
                [ids["fov_id"]],
                tmid,
                "measurement_scope",
                ids["pipeline_run_id"],
            )
        assert len(results) == 1
        assert results[0].reason == "new_assignment"

    def test_mask_non_measurement_purpose_returns_empty(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            tmid = new_uuid()
            db.insert_threshold_mask(tmid, ids["fov_id"], "GFP")
            results = db.assign_mask(
                [ids["fov_id"]],
                tmid,
                "background_estimation",
                ids["pipeline_run_id"],
            )
        # No MeasurementNeeded for non-measurement_scope
        assert len(results) == 0

    def test_mask_reassignment(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            tmid = new_uuid()
            db.insert_threshold_mask(tmid, ids["fov_id"], "GFP")
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            db.assign_mask(
                [ids["fov_id"]], tmid, "measurement_scope",
                ids["pipeline_run_id"],
            )
            prid2 = _setup_pipeline_run(db)
            results = db.assign_mask(
                [ids["fov_id"]], tmid, "measurement_scope", prid2,
            )
        assert results[0].reason == "reassignment"


class TestGetActiveAssignments:
    """Test get_active_assignments returns both seg and mask."""

    def test_returns_both_types(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            tmid = new_uuid()
            db.insert_threshold_mask(tmid, ids["fov_id"], "GFP")
            db.assign_mask(
                [ids["fov_id"]], tmid, "background_estimation",
                ids["pipeline_run_id"],
            )
        result = db.get_active_assignments(ids["fov_id"])
        assert "segmentation" in result
        assert "mask" in result
        assert len(result["segmentation"]) == 1
        assert len(result["mask"]) == 1

    def test_empty_for_unassigned_fov(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid)
        result = db.get_active_assignments(fid)
        assert len(result["segmentation"]) == 0
        assert len(result["mask"]) == 0


class TestDeactivateAssignment:
    """Test deactivate_assignment for both tables."""

    def test_deactivate_seg_assignment(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
        active = db.get_active_assignments(ids["fov_id"])
        aid = active["segmentation"][0]["id"]
        with db.transaction():
            count = db.deactivate_assignment(
                "fov_segmentation_assignments", aid,
            )
        assert count == 1
        active = db.get_active_assignments(ids["fov_id"])
        assert len(active["segmentation"]) == 0

    def test_deactivate_mask_assignment(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            tmid = new_uuid()
            db.insert_threshold_mask(tmid, ids["fov_id"], "GFP")
            db.assign_mask(
                [ids["fov_id"]], tmid, "background_estimation",
                ids["pipeline_run_id"],
            )
        active = db.get_active_assignments(ids["fov_id"])
        aid = active["mask"][0]["id"]
        with db.transaction():
            count = db.deactivate_assignment(
                "fov_mask_assignments", aid,
            )
        assert count == 1
        active = db.get_active_assignments(ids["fov_id"])
        assert len(active["mask"]) == 0

    def test_invalid_table_raises(self, db: ExperimentDB) -> None:
        with pytest.raises(ValueError, match="table must be one of"):
            db.deactivate_assignment("bad_table", new_uuid())


# ===================================================================
# 23. FOV Status Machine
# ===================================================================


class TestFovStatusMachine:
    """Test get_fov_status, set_fov_status, and mark_descendants_stale."""

    def test_get_fov_status(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid, status="imported")
        assert db.get_fov_status(fid) == "imported"

    def test_get_fov_status_not_found(self, db: ExperimentDB) -> None:
        with pytest.raises(ValueError, match="FOV not found"):
            db.get_fov_status(new_uuid())

    def test_valid_transition_succeeds(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid, status="imported")
        with db.transaction():
            db.set_fov_status(fid, "segmented", message="cellpose done")
        assert db.get_fov_status(fid) == "segmented"
        # Check log entry
        log = db.connection.execute(
            "SELECT * FROM fov_status_log WHERE fov_id = ?", (fid,)
        ).fetchall()
        assert len(log) == 1
        assert log[0]["old_status"] == "imported"
        assert log[0]["new_status"] == "segmented"
        assert log[0]["message"] == "cellpose done"

    def test_invalid_transition_raises(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fid = _setup_fov(db, eid, status="imported")
        with pytest.raises(
            InvalidStatusTransition,
            match="Cannot transition from 'imported' to 'measured'",
        ):
            with db.transaction():
                db.set_fov_status(fid, "measured")

    def test_mark_descendants_stale_propagates(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            root = _setup_fov(db, eid, status="imported")
            child = new_uuid()
            db.insert_fov(
                child, eid, parent_fov_id=root, status="segmented",
            )
            grandchild = new_uuid()
            db.insert_fov(
                grandchild, eid, parent_fov_id=child, status="measured",
            )
        with db.transaction():
            count = db.mark_descendants_stale(root)
        assert count == 2
        assert db.get_fov_status(child) == "stale"
        assert db.get_fov_status(grandchild) == "stale"

    def test_mark_descendants_stale_skips_deleted(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            root = _setup_fov(db, eid, status="imported")
            child_active = new_uuid()
            db.insert_fov(
                child_active, eid, parent_fov_id=root, status="segmented",
            )
            child_deleted = new_uuid()
            db.insert_fov(
                child_deleted, eid, parent_fov_id=root, status="deleting",
            )
            child_pending = new_uuid()
            db.insert_fov(
                child_pending, eid, parent_fov_id=root, status="pending",
            )
        with db.transaction():
            count = db.mark_descendants_stale(root)
        assert count == 1  # Only child_active
        assert db.get_fov_status(child_active) == "stale"
        assert db.get_fov_status(child_deleted) == "deleting"
        assert db.get_fov_status(child_pending) == "pending"

    def test_mark_descendants_stale_returns_count(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            root = _setup_fov(db, eid, status="imported")
        with db.transaction():
            count = db.mark_descendants_stale(root)
        assert count == 0  # No descendants


# ===================================================================
# 24. Lineage Queries
# ===================================================================


class TestLineageQueries:
    """Test get_descendants, get_ancestors, check_no_cycle."""

    def test_get_descendants_tree(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            root = _setup_fov(db, eid, status="imported")
            child1 = new_uuid()
            db.insert_fov(child1, eid, parent_fov_id=root, status="imported")
            child2 = new_uuid()
            db.insert_fov(child2, eid, parent_fov_id=root, status="imported")
            grandchild = new_uuid()
            db.insert_fov(
                grandchild, eid, parent_fov_id=child1, status="imported",
            )
        descendants = db.get_descendants(root)
        assert len(descendants) == 3
        desc_ids = {d["id"] for d in descendants}
        assert desc_ids == {child1, child2, grandchild}
        # Check depths
        depth_map = {d["id"]: d["depth"] for d in descendants}
        assert depth_map[child1] == 1
        assert depth_map[child2] == 1
        assert depth_map[grandchild] == 2

    def test_get_ancestors_chain(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            root = _setup_fov(db, eid, status="imported")
            child = new_uuid()
            db.insert_fov(child, eid, parent_fov_id=root, status="imported")
            grandchild = new_uuid()
            db.insert_fov(
                grandchild, eid, parent_fov_id=child, status="imported",
            )
        ancestors = db.get_ancestors(grandchild)
        assert len(ancestors) == 2
        assert ancestors[0]["id"] == child   # depth 1
        assert ancestors[1]["id"] == root    # depth 2

    def test_get_ancestors_root_has_none(self, db: ExperimentDB) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            root = _setup_fov(db, eid, status="imported")
        ancestors = db.get_ancestors(root)
        assert len(ancestors) == 0

    def test_depth_guard_prevents_deep_recursion(
        self, db: ExperimentDB
    ) -> None:
        """Build a chain longer than MAX_LINEAGE_DEPTH and verify
        the query stops at the guard depth."""
        from percell4.core.constants import MAX_LINEAGE_DEPTH

        with db.transaction():
            eid = _setup_experiment(db)
            depth = MAX_LINEAGE_DEPTH + 10
            chain = [_setup_fov(db, eid, status="imported")]
            for _ in range(depth):
                fid = new_uuid()
                db.insert_fov(
                    fid, eid, parent_fov_id=chain[-1], status="imported",
                )
                chain.append(fid)
        # Descendants of root should be capped
        descendants = db.get_descendants(chain[0])
        assert len(descendants) <= MAX_LINEAGE_DEPTH

    def test_check_no_cycle_detects_direct_cycle(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            root = _setup_fov(db, eid, status="imported")
            child = new_uuid()
            db.insert_fov(child, eid, parent_fov_id=root, status="imported")
        # Trying to make root's parent be child would create a cycle
        assert db.check_no_cycle(root, child) is False

    def test_check_no_cycle_allows_valid_parent(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fov_a = _setup_fov(db, eid, status="imported")
            fov_b = _setup_fov(db, eid, status="imported")
        assert db.check_no_cycle(fov_a, fov_b) is True

    def test_check_no_cycle_self_reference(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            eid = _setup_experiment(db)
            fov = _setup_fov(db, eid, status="imported")
        assert db.check_no_cycle(fov, fov) is False


# ===================================================================
# 25. Active Measurements Query
# ===================================================================


class TestActiveMeasurements:
    """Test get_active_measurements and get_active_measurements_pivot."""

    def test_returns_only_active_pipeline_measurements(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            # Assign segmentation
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            # Insert measurement from the active pipeline run
            db.insert_measurement(
                new_uuid(), ids["roi_id"], ids["channel_gfp"],
                "mean", "whole_roi", 42.0, ids["pipeline_run_id"],
            )
            # Insert measurement from a different (non-active) run
            other_run = _setup_pipeline_run(db)
            db.insert_measurement(
                new_uuid(), ids["roi_id"], ids["channel_gfp"],
                "max", "whole_roi", 99.0, other_run,
            )

        results = db.get_active_measurements(ids["fov_id"])
        assert len(results) == 1
        assert results[0]["value"] == 42.0
        assert results[0]["metric"] == "mean"

    def test_after_reassignment_returns_new_measurements(
        self, db: ExperimentDB
    ) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            # First assignment
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            db.insert_measurement(
                new_uuid(), ids["roi_id"], ids["channel_gfp"],
                "mean", "whole_roi", 42.0, ids["pipeline_run_id"],
            )
            # Reassign with a new pipeline run
            prid2 = _setup_pipeline_run(db)
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                prid2,
            )
            db.insert_measurement(
                new_uuid(), ids["roi_id"], ids["channel_gfp"],
                "mean", "whole_roi", 100.0, prid2,
            )

        results = db.get_active_measurements(ids["fov_id"])
        assert len(results) == 1
        assert results[0]["value"] == 100.0

    def test_mixed_provenance_invariant(self, db: ExperimentDB) -> None:
        """Verify no two active measurements for the same
        (roi_id, scope) come from different pipeline_run_ids."""
        with db.transaction():
            ids = _setup_full_experiment(db)
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            # Multiple metrics, all from same pipeline run
            for metric, val in [("mean", 10.0), ("max", 20.0), ("min", 1.0)]:
                db.insert_measurement(
                    new_uuid(), ids["roi_id"], ids["channel_gfp"],
                    metric, "whole_roi", val, ids["pipeline_run_id"],
                )

        results = db.get_active_measurements(ids["fov_id"])
        # Group by (roi_id, scope) — all pipeline_run_ids should be identical
        from collections import defaultdict
        groups: dict[tuple, set] = defaultdict(set)
        for r in results:
            key = (r["roi_id"], r["scope"])
            groups[key].add(r["pipeline_run_id"])
        for key, run_ids in groups.items():
            assert len(run_ids) == 1, (
                f"Mixed provenance for {key}: {len(run_ids)} pipeline runs"
            )

    def test_pivot_returns_all_fovs(self, db: ExperimentDB) -> None:
        with db.transaction():
            ids = _setup_full_experiment(db)
            db.assign_segmentation(
                [ids["fov_id"]],
                ids["seg_set_id"],
                ids["roi_type_id"],
                ids["pipeline_run_id"],
            )
            db.insert_measurement(
                new_uuid(), ids["roi_id"], ids["channel_gfp"],
                "mean", "whole_roi", 42.0, ids["pipeline_run_id"],
            )
        results = db.get_active_measurements_pivot([ids["fov_id"]])
        assert len(results) == 1
        assert results[0]["value"] == 42.0
        assert results[0]["label_id"] == 1


# ===================================================================
# 27. Merge
# ===================================================================


def _create_populated_db(db_path: Path, *, status: str = "imported") -> Path:
    """Create a fully populated test database at the given path.

    Inserts experiment, condition, channel, roi_type, FOV, pipeline_run,
    ROI, and measurement. Returns the path for use as a merge source.
    """
    database = ExperimentDB(db_path)
    database.open()
    try:
        eid = new_uuid()
        database.insert_experiment(eid, "source_experiment")
        cid = new_uuid()
        database.insert_condition(cid, eid, "control")
        chid = new_uuid()
        database.insert_channel(chid, eid, "GFP")
        rtid = new_uuid()
        database.insert_roi_type_definition(rtid, eid, "cell")
        fid = new_uuid()
        database.insert_fov(fid, eid, condition_id=cid, status=status,
                            zarr_path=f"data/{fid.hex()}")
        prid = new_uuid()
        database.insert_pipeline_run(prid, "import_op")
        ssid = new_uuid()
        database.insert_segmentation_set(ssid, eid, rtid, "cellpose")
        ciid = new_uuid()
        database.insert_cell_identity(ciid, fid, rtid)
        rid = new_uuid()
        database.insert_roi(rid, fid, rtid, ciid, None, 1, 0, 0, 10, 10, 100)
        mid = new_uuid()
        database.insert_measurement(
            mid, rid, chid, "mean", "whole_roi", 42.0, prid
        )

        # Add a status log entry
        database.connection.execute(
            "INSERT INTO fov_status_log (fov_id, old_status, new_status, message) "
            "VALUES (?, ?, ?, ?)",
            (fid, None, status, "initial import"),
        )
        database.connection.commit()
    finally:
        database.close()
    return db_path


class TestMerge:
    """Test merge_experiment with various scenarios."""

    def test_merge_no_conflicts(self, tmp_path: Path) -> None:
        """Merge two DBs with completely different UUIDs — all rows inserted."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        # Create target
        _create_populated_db(target_path)

        # Create source with different UUIDs
        _create_populated_db(source_path)

        target = ExperimentDB(target_path)
        target.open()
        try:
            result = target.merge_experiment(source_path)

            # Verify rows were inserted
            assert result["tables"]["experiments"] >= 0  # OR IGNORE may skip
            assert result["tables"]["fovs"] >= 1
            assert result["tables"]["rois"] >= 1
            assert result["tables"]["measurements"] >= 1
            assert result["tables"]["fov_status_log"] >= 1
            assert len(result["conflicts"]) == 0

            # Verify we now have 2 experiments
            rows = target.connection.execute(
                "SELECT COUNT(*) as cnt FROM experiments"
            ).fetchone()
            assert rows["cnt"] == 2

            # Verify we now have 2 FOVs
            fov_count = target.connection.execute(
                "SELECT COUNT(*) as cnt FROM fovs"
            ).fetchone()
            assert fov_count["cnt"] == 2
        finally:
            target.close()

    def test_merge_duplicate_uuid_same_content(self, tmp_path: Path) -> None:
        """INSERT OR IGNORE handles duplicate UUIDs with same content gracefully."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        # Create target
        _create_populated_db(target_path)

        # Copy target as source (identical content, same UUIDs)
        import shutil
        shutil.copy2(target_path, source_path)

        target = ExperimentDB(target_path)
        target.open()
        try:
            result = target.merge_experiment(source_path)

            # All inserts should be ignored (0 new rows)
            # experiments, conditions, channels, etc. all duplicates
            for table, count in result["tables"].items():
                if table == "fov_status_log":
                    # INTEGER PK — duplicates get new IDs
                    continue
                assert count == 0, (
                    f"Expected 0 new rows for {table}, got {count}"
                )
            assert len(result["conflicts"]) == 0
        finally:
            target.close()

    def test_merge_schema_version_mismatch(self, tmp_path: Path) -> None:
        """Raises MergeConflictError when schema versions differ."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        _create_populated_db(target_path)
        _create_populated_db(source_path)

        # Manually update source schema version to something different
        conn = sqlite3.connect(str(source_path))
        conn.execute(
            "UPDATE experiments SET schema_version = '99.0.0'"
        )
        conn.commit()
        conn.close()

        target = ExperimentDB(target_path)
        target.open()
        try:
            with pytest.raises(MergeConflictError, match="Schema version mismatch"):
                target.merge_experiment(source_path)
        finally:
            target.close()

    def test_merge_excludes_pending_fovs(self, tmp_path: Path) -> None:
        """FOVs with status 'pending' are not merged."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        _create_populated_db(target_path)
        _create_populated_db(source_path, status="pending")

        target = ExperimentDB(target_path)
        target.open()
        try:
            result = target.merge_experiment(source_path)

            # No FOVs inserted (the source FOV is pending)
            assert result["tables"]["fovs"] == 0

            # Target should still only have its original FOV
            fov_count = target.connection.execute(
                "SELECT COUNT(*) as cnt FROM fovs"
            ).fetchone()
            assert fov_count["cnt"] == 1
        finally:
            target.close()

    def test_merge_excludes_deleting_fovs(self, tmp_path: Path) -> None:
        """FOVs with status 'deleting' are not merged."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        _create_populated_db(target_path)

        # Create source with a deleting FOV
        # We need to manually create because _create_populated_db
        # can't insert 'deleting' status directly (CHECK constraint
        # allows it, but the status machine normally controls flow).
        source_db = ExperimentDB(source_path)
        source_db.open()
        try:
            eid = new_uuid()
            source_db.insert_experiment(eid, "source_exp")
            fid = new_uuid()
            source_db.insert_fov(
                fid, eid, status="imported",
                zarr_path=f"data/{fid.hex()}"
            )
            # Transition to deleting: imported -> deleting is valid
            source_db.set_fov_status(fid, "deleting")
            source_db.connection.commit()
        finally:
            source_db.close()

        target = ExperimentDB(target_path)
        target.open()
        try:
            result = target.merge_experiment(source_path)
            assert result["tables"]["fovs"] == 0
        finally:
            target.close()

    def test_merge_fov_status_log_no_pk_collision(
        self, tmp_path: Path
    ) -> None:
        """INTEGER PKs get new auto-assigned IDs, no collision."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        _create_populated_db(target_path)
        _create_populated_db(source_path)

        target = ExperimentDB(target_path)
        target.open()
        try:
            # Count log entries before merge
            before = target.connection.execute(
                "SELECT COUNT(*) as cnt FROM fov_status_log"
            ).fetchone()["cnt"]

            result = target.merge_experiment(source_path)

            after = target.connection.execute(
                "SELECT COUNT(*) as cnt FROM fov_status_log"
            ).fetchone()["cnt"]

            # New entries were added
            assert after > before
            assert result["tables"]["fov_status_log"] >= 1

            # Verify no duplicate PKs
            pk_count = target.connection.execute(
                "SELECT COUNT(DISTINCT id) as cnt FROM fov_status_log"
            ).fetchone()["cnt"]
            assert pk_count == after  # all PKs unique
        finally:
            target.close()

    def test_merge_post_fk_check_passes(self, tmp_path: Path) -> None:
        """PRAGMA foreign_key_check is clean after a well-formed merge."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        _create_populated_db(target_path)
        _create_populated_db(source_path)

        target = ExperimentDB(target_path)
        target.open()
        try:
            result = target.merge_experiment(source_path)
            assert len(result["fk_violations"]) == 0
        finally:
            target.close()

    def test_merge_zarr_path_uniqueness_warning(
        self, tmp_path: Path
    ) -> None:
        """Duplicate zarr_path detected and reported as a warning."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        shared_zarr = "data/shared_fov"

        # Create target with a specific zarr_path
        target_db = ExperimentDB(target_path)
        target_db.open()
        try:
            eid = new_uuid()
            target_db.insert_experiment(eid, "target_exp")
            cid = new_uuid()
            target_db.insert_condition(cid, eid, "control")
            chid = new_uuid()
            target_db.insert_channel(chid, eid, "GFP")
            fid = new_uuid()
            target_db.insert_fov(
                fid, eid, condition_id=cid, status="imported",
                zarr_path=shared_zarr,
            )
            target_db.connection.commit()
        finally:
            target_db.close()

        # Create source with the same zarr_path
        source_db = ExperimentDB(source_path)
        source_db.open()
        try:
            eid2 = new_uuid()
            source_db.insert_experiment(eid2, "source_exp")
            cid2 = new_uuid()
            source_db.insert_condition(cid2, eid2, "control")
            chid2 = new_uuid()
            source_db.insert_channel(chid2, eid2, "GFP")
            fid2 = new_uuid()
            source_db.insert_fov(
                fid2, eid2, condition_id=cid2, status="imported",
                zarr_path=shared_zarr,
            )
            source_db.connection.commit()
        finally:
            source_db.close()

        # Now merge — the unique index on zarr_path will cause OR IGNORE
        # to skip the duplicate FOV. So we need to drop the unique index
        # first to allow both in, OR we check the warning path differently.
        # Actually, the target has idx_fovs_zarr_path as a UNIQUE index
        # WHERE zarr_path IS NOT NULL AND status NOT IN ('deleted').
        # INSERT OR IGNORE will skip the conflicting row. So the warning
        # detection sees only 1 row (the target's). Let's test with
        # a different approach: insert the source FOV directly.

        # Actually let's test the warning path by disabling the unique index
        # scenario and instead checking that when 2 FOVs end up with same
        # zarr_path, the warning fires. We'll do this by giving them different
        # zarr_paths initially, then updating one after merge.
        # Simpler: use target DB that already has 2 FOVs with same zarr_path.

        # Better approach: the unique index prevents INSERT OR IGNORE from
        # adding the dup. The zarr_path check still finds it if we manually
        # insert. Let's just verify the check works with a manual setup.
        target_db = ExperimentDB(target_path)
        target_db.open()
        try:
            # Drop the unique partial index so we can insert a duplicate
            target_db.connection.execute(
                "DROP INDEX IF EXISTS idx_fovs_zarr_path"
            )
            eid_orig = target_db.connection.execute(
                "SELECT id FROM experiments LIMIT 1"
            ).fetchone()["id"]
            fid_dup = new_uuid()
            target_db.connection.execute(
                "INSERT INTO fovs (id, experiment_id, status, zarr_path) "
                "VALUES (?, ?, 'imported', ?)",
                (fid_dup, eid_orig, shared_zarr),
            )
            target_db.connection.commit()

            # Now merge the source — the post-merge zarr_path check should
            # detect the duplicates already in the target
            result = target_db.merge_experiment(source_path)

            zarr_warnings = [
                w for w in result["warnings"] if "zarr_path" in w
            ]
            assert len(zarr_warnings) >= 1
            assert shared_zarr in zarr_warnings[0]
        finally:
            target_db.close()

    def test_merge_assignment_conflict_resolution(
        self, tmp_path: Path
    ) -> None:
        """Duplicate active segmentation assignments resolved by deactivating the older one."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        # Shared IDs for the FOV and ROI type (to create a conflict)
        shared_fov_id = new_uuid()
        shared_eid = new_uuid()
        shared_cid = new_uuid()
        shared_rtid = new_uuid()
        shared_chid = new_uuid()

        # Create target with a segmentation assignment
        target_db = ExperimentDB(target_path)
        target_db.open()
        try:
            target_db.insert_experiment(shared_eid, "shared_exp")
            target_db.insert_condition(shared_cid, shared_eid, "control")
            target_db.insert_channel(shared_chid, shared_eid, "GFP")
            target_db.insert_roi_type_definition(shared_rtid, shared_eid, "cell")
            target_db.insert_fov(
                shared_fov_id, shared_eid, condition_id=shared_cid,
                status="imported", zarr_path="data/fov1",
            )
            prid1 = new_uuid()
            target_db.insert_pipeline_run(prid1, "seg_op")
            ssid1 = new_uuid()
            target_db.insert_segmentation_set(ssid1, shared_eid, shared_rtid, "cellpose")

            # Create assignment with an early timestamp
            assign_id1 = new_uuid()
            target_db.connection.execute(
                "INSERT INTO fov_segmentation_assignments "
                "(id, fov_id, segmentation_set_id, roi_type_id, is_active, "
                " pipeline_run_id, assigned_at) "
                "VALUES (?, ?, ?, ?, 1, ?, '2025-01-01 00:00:00')",
                (assign_id1, shared_fov_id, ssid1, shared_rtid, prid1),
            )
            target_db.connection.commit()
        finally:
            target_db.close()

        # Create source with same shared entities but a different assignment
        source_db = ExperimentDB(source_path)
        source_db.open()
        try:
            source_db.insert_experiment(shared_eid, "shared_exp")
            source_db.insert_condition(shared_cid, shared_eid, "control")
            source_db.insert_channel(shared_chid, shared_eid, "GFP")
            source_db.insert_roi_type_definition(shared_rtid, shared_eid, "cell")
            source_db.insert_fov(
                shared_fov_id, shared_eid, condition_id=shared_cid,
                status="imported", zarr_path="data/fov1",
            )
            prid2 = new_uuid()
            source_db.insert_pipeline_run(prid2, "seg_op_v2")
            ssid2 = new_uuid()
            source_db.insert_segmentation_set(ssid2, shared_eid, shared_rtid, "cellpose")

            # Create assignment with a later timestamp
            assign_id2 = new_uuid()
            source_db.connection.execute(
                "INSERT INTO fov_segmentation_assignments "
                "(id, fov_id, segmentation_set_id, roi_type_id, is_active, "
                " pipeline_run_id, assigned_at) "
                "VALUES (?, ?, ?, ?, 1, ?, '2025-06-01 00:00:00')",
                (assign_id2, shared_fov_id, ssid2, shared_rtid, prid2),
            )
            source_db.connection.commit()
        finally:
            source_db.close()

        # Merge — the unique partial index will prevent the 2nd active
        # assignment from being inserted via OR IGNORE. We need to drop
        # the unique index on the target to allow both through.
        target_db = ExperimentDB(target_path)
        target_db.open()
        try:
            # Drop the partial unique index so both active assignments coexist
            target_db.connection.execute(
                "DROP INDEX IF EXISTS idx_fsa_one_active"
            )
            target_db.connection.commit()

            result = target_db.merge_experiment(source_path)

            # The older assignment should have been deactivated
            deactivate_warnings = [
                w for w in result["warnings"]
                if "Deactivated duplicate segmentation" in w
            ]
            assert len(deactivate_warnings) >= 1

            # Verify only 1 active assignment remains for this (fov, roi_type)
            active_count = target_db.connection.execute(
                "SELECT COUNT(*) as cnt FROM fov_segmentation_assignments "
                "WHERE fov_id = ? AND roi_type_id = ? AND is_active = 1",
                (shared_fov_id, shared_rtid),
            ).fetchone()["cnt"]
            assert active_count == 1

            # The surviving active assignment should be the newer one
            surviving = target_db.connection.execute(
                "SELECT id, assigned_at FROM fov_segmentation_assignments "
                "WHERE fov_id = ? AND roi_type_id = ? AND is_active = 1",
                (shared_fov_id, shared_rtid),
            ).fetchone()
            assert surviving["assigned_at"] == "2025-06-01 00:00:00"
        finally:
            target_db.close()

    def test_merge_attach_parameter_binding(self, tmp_path: Path) -> None:
        """Path with special characters works — no SQL injection via parameter binding."""
        # Create a path with spaces and special chars
        special_dir = tmp_path / "path with spaces & 'quotes'"
        special_dir.mkdir()
        source_path = special_dir / "source.db"
        target_path = tmp_path / "target.db"

        _create_populated_db(target_path)
        _create_populated_db(source_path)

        target = ExperimentDB(target_path)
        target.open()
        try:
            # Should not raise — parameter binding handles special chars
            result = target.merge_experiment(source_path)
            assert "tables" in result
            assert "conflicts" in result
        finally:
            target.close()

    def test_merge_detach_on_error(self, tmp_path: Path) -> None:
        """Source DB is detached even if the merge fails partway through."""
        target_path = tmp_path / "target.db"
        source_path = tmp_path / "source.db"

        _create_populated_db(target_path)
        _create_populated_db(source_path)

        # Corrupt the source by removing a table that merge_experiment
        # tries to read from
        conn = sqlite3.connect(str(source_path))
        conn.execute("DROP TABLE measurements")
        conn.commit()
        conn.close()

        target = ExperimentDB(target_path)
        target.open()
        try:
            with pytest.raises(Exception):
                target.merge_experiment(source_path)

            # Verify source is detached (should be able to ATTACH again)
            # If not detached, this would raise "database source is already in use"
            target.connection.execute(
                "ATTACH ? AS source", (str(source_path),)
            )
            target.connection.execute("DETACH source")

            # Verify FK is re-enabled
            fk_state = target.connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()
            assert fk_state[0] == 1
        finally:
            target.close()
