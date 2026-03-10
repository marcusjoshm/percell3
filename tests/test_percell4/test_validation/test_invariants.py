"""Cross-store invariant tests — verify database integrity after
building a complete mini-experiment.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from percell4.core.db_types import new_uuid
from percell4.core.experiment_db import ExperimentDB
from percell4.core.schema import SCHEMA_VERSION


@pytest.fixture()
def mini_experiment(tmp_path: Path) -> ExperimentDB:
    """Build a complete mini-experiment with all entity relationships.

    Creates: experiment -> condition -> bio_rep, channels, roi_type,
    pipeline_run -> fov -> cell_identity -> roi -> measurement.
    """
    db = ExperimentDB(tmp_path / "experiment.db")
    db.open()

    exp_id = new_uuid()
    cond_id = new_uuid()
    bio_rep_id = new_uuid()
    ch_id = new_uuid()
    roi_type_id = new_uuid()
    fov_id = new_uuid()
    ci_id = new_uuid()
    roi_id = new_uuid()
    seg_set_id = new_uuid()
    pipeline_run_id = new_uuid()
    measurement_id = new_uuid()

    with db.transaction():
        db.insert_experiment(exp_id, "Test", schema_version=SCHEMA_VERSION)
        db.insert_condition(cond_id, exp_id, "control")
        db.insert_bio_rep(bio_rep_id, exp_id, cond_id, "rep1")
        db.insert_channel(ch_id, exp_id, "DAPI", role="nuclear")
        db.insert_roi_type_definition(roi_type_id, exp_id, "cell")
        db.insert_pipeline_run(pipeline_run_id, "segmentation")
        db.insert_fov(
            id=fov_id,
            experiment_id=exp_id,
            condition_id=cond_id,
            bio_rep_id=bio_rep_id,
            status="pending",
            auto_name="FOV_001",
            zarr_path="fovs/test001",
        )
        db.insert_cell_identity(ci_id, fov_id, roi_type_id)
        db.insert_roi(
            id=roi_id,
            fov_id=fov_id,
            roi_type_id=roi_type_id,
            cell_identity_id=ci_id,
            parent_roi_id=None,
            label_id=1,
            bbox_y=0,
            bbox_x=0,
            bbox_h=50,
            bbox_w=50,
            area_px=2000,
        )
        db.insert_segmentation_set(
            seg_set_id, exp_id, roi_type_id, "cellpose",
            source_channel="DAPI", model_name="cyto3",
        )
        db.assign_segmentation(
            [fov_id], seg_set_id, roi_type_id, pipeline_run_id,
            assigned_by="test",
        )
        db.insert_measurement(
            measurement_id, roi_id, ch_id, "mean",
            "whole_roi", 42.5, pipeline_run_id,
        )

    yield db
    db.close()


def test_foreign_key_integrity(mini_experiment: ExperimentDB) -> None:
    """PRAGMA foreign_key_check returns empty (no FK violations)."""
    violations = mini_experiment.connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()
    assert violations == [], (
        f"Foreign key violations found: {[tuple(v) for v in violations]}"
    )


def test_no_orphaned_measurements(mini_experiment: ExperimentDB) -> None:
    """Every measurement.roi_id must exist in the rois table."""
    orphans = mini_experiment.connection.execute(
        "SELECT m.id FROM measurements m "
        "LEFT JOIN rois r ON m.roi_id = r.id "
        "WHERE r.id IS NULL"
    ).fetchall()
    assert orphans == [], (
        f"Found {len(orphans)} measurements with orphaned roi_id"
    )


def test_all_uuids_correct_length(mini_experiment: ExperimentDB) -> None:
    """Every BLOB(16) column value must have length exactly 16."""
    conn = mini_experiment.connection

    # Tables with BLOB(16) columns and their column names
    blob_columns: dict[str, list[str]] = {
        "experiments": ["id"],
        "conditions": ["id", "experiment_id"],
        "bio_reps": ["id", "experiment_id", "condition_id"],
        "channels": ["id", "experiment_id"],
        "timepoints": ["id", "experiment_id"],
        "roi_type_definitions": ["id", "experiment_id", "parent_type_id"],
        "pipeline_runs": ["id"],
        "fovs": [
            "id", "experiment_id", "condition_id", "bio_rep_id",
            "parent_fov_id", "timepoint_id",
        ],
        "cell_identities": ["id", "origin_fov_id", "roi_type_id"],
        "rois": [
            "id", "fov_id", "roi_type_id", "cell_identity_id",
            "parent_roi_id",
        ],
        "segmentation_sets": ["id", "experiment_id", "produces_roi_type_id"],
        "threshold_masks": ["id", "fov_id"],
        "fov_segmentation_assignments": [
            "id", "fov_id", "segmentation_set_id", "roi_type_id",
            "pipeline_run_id",
        ],
        "fov_mask_assignments": [
            "id", "fov_id", "threshold_mask_id", "pipeline_run_id",
        ],
        "measurements": [
            "id", "roi_id", "channel_id", "pipeline_run_id",
        ],
        "intensity_groups": [
            "id", "experiment_id", "channel_id", "pipeline_run_id",
        ],
        "cell_group_assignments": [
            "id", "intensity_group_id", "roi_id", "pipeline_run_id",
        ],
    }

    violations: list[str] = []
    for table, columns in blob_columns.items():
        for col in columns:
            rows = conn.execute(
                f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL"
            ).fetchall()
            for row in rows:
                val = row[col]
                if not isinstance(val, bytes) or len(val) != 16:
                    violations.append(
                        f"{table}.{col} rowid={row['rowid']}: "
                        f"expected 16 bytes, got "
                        f"{type(val).__name__}({len(val) if isinstance(val, bytes) else '?'})"
                    )

    assert not violations, (
        "UUID columns with incorrect length:\n" + "\n".join(violations)
    )
