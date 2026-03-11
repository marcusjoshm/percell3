"""Tests for schema 6.0.0 lineage features.

Covers:
- Derived FOV creation with lineage_depth and lineage_path
- Multi-generation lineage (root -> child -> grandchild)
- Lineage queries (descendants, ancestors, get_fov_lineage, get_fov_tree)
- FK cascade: deleting FOV cascades to rois/measurements
- FK restrict: cannot delete FOV that is origin for cell_identities
- Cross-lineage measurement queries
- Nullable measurement values (NaN as NULL)
- insert_rois_bulk
- Migration backfill (5.1.0 -> 6.0.0 lineage_path population)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus, SCOPE_WHOLE_ROI
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.exceptions import ExperimentError
from percell4.core.experiment_db import ExperimentDB
from percell4.core.experiment_store import ExperimentStore
from percell4.core.schema import SCHEMA_VERSION

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


# ===========================================================================
# Derived FOV lineage fields
# ===========================================================================


class TestDerivedFovLineage:
    """Verify create_derived_fov sets lineage_depth and lineage_path."""

    def test_derived_fov_has_depth_1(self, populated_store) -> None:
        """First-generation derived FOV has lineage_depth = 1."""
        store, info = populated_store

        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="nan_zero",
            params={"threshold": 0},
            transform_fn=lambda a: a,
        )

        derived = store.db.get_fov(derived_id)
        assert derived["lineage_depth"] == 1

    def test_derived_fov_has_lineage_path(self, populated_store) -> None:
        """Derived FOV lineage_path contains parent hex and self hex."""
        store, info = populated_store

        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="bg_sub",
            params={},
            transform_fn=lambda a: a,
        )

        derived = store.db.get_fov(derived_id)
        path = derived["lineage_path"]
        assert path is not None

        # Path should contain both parent and self hex IDs
        parent_hex = uuid_to_hex(info["fov_id"])
        derived_hex = uuid_to_hex(derived_id)
        assert parent_hex in path
        assert derived_hex in path

    def test_derived_fov_copies_pixel_size_um(self, populated_store) -> None:
        """Derived FOV inherits pixel_size_um from source."""
        store, info = populated_store

        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        source = store.db.get_fov(info["fov_id"])
        derived = store.db.get_fov(derived_id)
        assert derived["pixel_size_um"] == source["pixel_size_um"]

    def test_derived_fov_accepts_display_name(self, populated_store) -> None:
        """create_derived_fov passes display_name to DB."""
        store, info = populated_store

        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
            display_name="My Custom Name",
        )

        derived = store.db.get_fov(derived_id)
        assert derived["display_name"] == "My Custom Name"

    def test_derived_fov_accepts_channel_metadata(self, populated_store) -> None:
        """create_derived_fov passes channel_metadata JSON to DB."""
        store, info = populated_store
        meta = json.dumps({"ch0": {"bg_subtracted": True}})

        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
            channel_metadata=meta,
        )

        derived = store.db.get_fov(derived_id)
        assert derived["channel_metadata"] == meta


# ===========================================================================
# Multi-generation lineage
# ===========================================================================


class TestMultiGenerationLineage:
    """Test root -> child -> grandchild lineage chains."""

    def _make_chain(self, store, info):
        """Create a three-generation chain: root -> child -> grandchild."""
        child_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="bg_sub",
            params={},
            transform_fn=lambda a: a,
        )
        grandchild_id = store.create_derived_fov(
            source_fov_id=child_id,
            derivation_op="nan_zero",
            params={},
            transform_fn=lambda a: a,
        )
        return child_id, grandchild_id

    def test_grandchild_depth_is_2(self, populated_store) -> None:
        """Third-generation FOV has lineage_depth = 2."""
        store, info = populated_store
        _child_id, grandchild_id = self._make_chain(store, info)

        gc = store.db.get_fov(grandchild_id)
        assert gc["lineage_depth"] == 2

    def test_grandchild_path_contains_all_ancestors(self, populated_store) -> None:
        """Grandchild lineage_path includes root, child, and grandchild hex IDs."""
        store, info = populated_store
        child_id, grandchild_id = self._make_chain(store, info)

        gc = store.db.get_fov(grandchild_id)
        path = gc["lineage_path"]

        root_hex = uuid_to_hex(info["fov_id"])
        child_hex = uuid_to_hex(child_id)
        gc_hex = uuid_to_hex(grandchild_id)

        assert root_hex in path
        assert child_hex in path
        assert gc_hex in path

    def test_descendants_returns_all(self, populated_store) -> None:
        """get_descendants from root returns child and grandchild."""
        store, info = populated_store
        child_id, grandchild_id = self._make_chain(store, info)

        descendants = store.db.get_descendants(info["fov_id"])
        desc_ids = {d["id"] for d in descendants}

        assert child_id in desc_ids
        assert grandchild_id in desc_ids

    def test_ancestors_from_grandchild(self, populated_store) -> None:
        """get_ancestors from grandchild returns child and root."""
        store, info = populated_store
        child_id, grandchild_id = self._make_chain(store, info)

        ancestors = store.db.get_ancestors(grandchild_id)
        anc_ids = {a["id"] for a in ancestors}

        assert child_id in anc_ids
        assert info["fov_id"] in anc_ids

    def test_root_has_no_ancestors(self, populated_store) -> None:
        """Root FOV returns empty ancestors list."""
        store, info = populated_store
        self._make_chain(store, info)

        ancestors = store.db.get_ancestors(info["fov_id"])
        assert ancestors == []


# ===========================================================================
# get_fov_lineage (materialized path + CTE fallback)
# ===========================================================================


class TestGetFovLineage:
    """Test the get_fov_lineage method which uses lineage_path when available."""

    def test_lineage_both_directions(self, populated_store) -> None:
        """get_fov_lineage returns both ancestors and descendants."""
        store, info = populated_store

        child_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        lineage = store.db.get_fov_lineage(child_id, direction="both")
        assert "ancestors" in lineage
        assert "descendants" in lineage

        # Child's ancestor is the root
        anc_ids = {a["id"] for a in lineage["ancestors"]}
        assert info["fov_id"] in anc_ids

    def test_lineage_ancestors_only(self, populated_store) -> None:
        """get_fov_lineage(direction='ancestors') omits descendants."""
        store, info = populated_store

        child_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        lineage = store.db.get_fov_lineage(child_id, direction="ancestors")
        assert "ancestors" in lineage
        assert "descendants" not in lineage

    def test_lineage_descendants_only(self, populated_store) -> None:
        """get_fov_lineage(direction='descendants') omits ancestors."""
        store, info = populated_store

        child_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        lineage = store.db.get_fov_lineage(info["fov_id"], direction="descendants")
        assert "descendants" in lineage
        assert "ancestors" not in lineage

        desc_ids = {d["id"] for d in lineage["descendants"]}
        assert child_id in desc_ids


# ===========================================================================
# get_fov_tree (Store-level)
# ===========================================================================


class TestGetFovTree:
    """Test ExperimentStore.get_fov_tree()."""

    def test_fov_tree_structure(self, populated_store) -> None:
        """get_fov_tree returns fov, ancestors, and descendants."""
        store, info = populated_store

        child_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        tree = store.get_fov_tree(info["fov_id"])
        assert tree["fov"]["id"] == info["fov_id"]
        assert tree["ancestors"] == []

        desc_ids = {d["id"] for d in tree["descendants"]}
        assert child_id in desc_ids

    def test_fov_tree_nonexistent_raises(self, populated_store) -> None:
        """get_fov_tree with bad ID raises ExperimentError."""
        store, _info = populated_store
        with pytest.raises(ExperimentError, match="not found"):
            store.get_fov_tree(new_uuid())


# ===========================================================================
# FK CASCADE: delete FOV -> cascades to rois + measurements
# ===========================================================================


class TestFkCascade:
    """Test that ON DELETE CASCADE on rois.fov_id and measurements.roi_id works."""

    @staticmethod
    def _clear_non_cascading_refs(conn, fov_id: bytes) -> None:
        """Remove non-cascading FK references to an FOV so DELETE succeeds.

        Tables like fov_segmentation_assignments and fov_mask_assignments
        reference fovs without CASCADE, so we must delete those rows first.
        """
        conn.execute(
            "DELETE FROM fov_segmentation_assignments WHERE fov_id = ?",
            (fov_id,),
        )
        conn.execute(
            "DELETE FROM fov_mask_assignments WHERE fov_id = ?",
            (fov_id,),
        )
        conn.execute(
            "DELETE FROM threshold_masks WHERE fov_id = ?",
            (fov_id,),
        )

    def test_delete_fov_cascades_rois(self, populated_store) -> None:
        """Deleting an FOV via SQL DELETE cascades to its rois."""
        store, info = populated_store

        # Create a derived FOV (which has ROIs duplicated)
        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        # Verify ROIs exist on derived
        derived_rois = store.db.get_rois(derived_id)
        assert len(derived_rois) > 0

        # Remove non-cascading FK references, then delete the FOV
        conn = store.db.connection
        self._clear_non_cascading_refs(conn, derived_id)
        conn.execute("DELETE FROM fovs WHERE id = ?", (derived_id,))

        # ROIs should be gone (CASCADE from fovs -> rois)
        remaining = store.db.get_rois(derived_id)
        assert remaining == []

    def test_delete_fov_cascades_measurements(self, populated_store) -> None:
        """Deleting an FOV cascades rois, which cascades measurements."""
        store, info = populated_store

        # Create derived FOV and add measurements
        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        # Add measurements to derived ROIs
        derived_rois = store.db.get_rois(derived_id)
        run_id = info["run_id"]
        channels = info["channels"]

        with store.db.transaction():
            for roi in derived_rois:
                for ch in channels:
                    store.db.insert_measurement(
                        id=new_uuid(),
                        roi_id=roi["id"],
                        channel_id=ch["id"],
                        metric="mean",
                        scope=SCOPE_WHOLE_ROI,
                        value=99.0,
                        pipeline_run_id=run_id,
                    )

        # Verify measurements exist
        conn = store.db.connection
        count_before = conn.execute(
            "SELECT COUNT(*) FROM measurements m JOIN rois r ON m.roi_id = r.id "
            "WHERE r.fov_id = ?",
            (derived_id,),
        ).fetchone()[0]
        assert count_before > 0

        # Remove non-cascading refs, then delete the FOV
        self._clear_non_cascading_refs(conn, derived_id)
        conn.execute("DELETE FROM fovs WHERE id = ?", (derived_id,))

        # Measurements via those ROIs should be gone
        # (CASCADE: fovs -> rois -> measurements)
        count_after = conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE roi_id IN "
            "(SELECT id FROM rois WHERE fov_id = ?)",
            (derived_id,),
        ).fetchone()[0]
        assert count_after == 0

    def test_delete_fov_cascades_status_log(self, populated_store) -> None:
        """Deleting an FOV cascades to fov_status_log entries."""
        store, info = populated_store

        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        conn = store.db.connection
        # Verify status log entries exist
        log_count = conn.execute(
            "SELECT COUNT(*) FROM fov_status_log WHERE fov_id = ?",
            (derived_id,),
        ).fetchone()[0]
        assert log_count > 0

        # Remove non-cascading refs, then delete
        self._clear_non_cascading_refs(conn, derived_id)
        conn.execute("DELETE FROM fovs WHERE id = ?", (derived_id,))

        # Status log should be gone (CASCADE from fovs -> fov_status_log)
        log_after = conn.execute(
            "SELECT COUNT(*) FROM fov_status_log WHERE fov_id = ?",
            (derived_id,),
        ).fetchone()[0]
        assert log_after == 0


# ===========================================================================
# FK RESTRICT: cannot delete origin FOV for cell_identities
# ===========================================================================


class TestFkRestrict:
    """Test ON DELETE RESTRICT on cell_identities.origin_fov_id."""

    def test_cannot_delete_origin_fov(self, populated_store) -> None:
        """Deleting FOV that is origin for cell_identities raises IntegrityError."""
        store, info = populated_store

        # info["fov_id"] is the origin_fov for cell_identity_1 and cell_identity_2
        conn = store.db.connection

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM fovs WHERE id = ?", (info["fov_id"],))

    def test_can_delete_derived_fov_without_identity_origin(
        self, populated_store
    ) -> None:
        """Derived FOV (not origin for any cell_identity) can be deleted."""
        store, info = populated_store

        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="test",
            params={},
            transform_fn=lambda a: a,
        )

        # Derived FOV is NOT the origin for any cell_identity (they reference source FOV)
        # Remove non-cascading FK references first
        conn = store.db.connection
        conn.execute(
            "DELETE FROM fov_segmentation_assignments WHERE fov_id = ?",
            (derived_id,),
        )
        conn.execute(
            "DELETE FROM fov_mask_assignments WHERE fov_id = ?",
            (derived_id,),
        )
        conn.execute("DELETE FROM fovs WHERE id = ?", (derived_id,))

        # Verify deleted
        fov = store.db.get_fov(derived_id)
        assert fov is None


# ===========================================================================
# Cross-lineage measurements
# ===========================================================================


class TestCrossLineageMeasurements:
    """Test get_cross_lineage_measurements for a cell identity across FOVs."""

    def test_measurements_across_derived_fovs(self, populated_store) -> None:
        """Measurements for same cell_identity across source and derived FOVs."""
        store, info = populated_store

        # Create derived FOV (ROIs duplicated with same cell_identity_id)
        derived_id = store.create_derived_fov(
            source_fov_id=info["fov_id"],
            derivation_op="bg_sub",
            params={},
            transform_fn=lambda a: a,
        )

        # Add measurements to derived ROIs
        derived_rois = store.db.get_rois(derived_id)
        run_id = info["run_id"]
        channels = info["channels"]

        with store.db.transaction():
            for roi in derived_rois:
                if roi["cell_identity_id"] == info["cell_identity_1"]:
                    for ch in channels:
                        store.db.insert_measurement(
                            id=new_uuid(),
                            roi_id=roi["id"],
                            channel_id=ch["id"],
                            metric="mean",
                            scope=SCOPE_WHOLE_ROI,
                            value=99.0,
                            pipeline_run_id=run_id,
                        )

        # Query cross-lineage measurements for cell_identity_1
        measurements = store.db.get_cross_lineage_measurements(
            info["cell_identity_1"]
        )

        # Should have measurements from both source and derived FOVs
        fov_ids = {m["fov_id"] for m in measurements}
        assert info["fov_id"] in fov_ids
        assert derived_id in fov_ids


# ===========================================================================
# Nullable measurement value (NaN as NULL)
# ===========================================================================


class TestNullableMeasurementValue:
    """Test that measurements.value can be NULL (schema 6.0.0)."""

    def test_insert_null_measurement_value(self, populated_store) -> None:
        """Inserting measurement with value=None succeeds."""
        store, info = populated_store

        m_id = new_uuid()
        with store.db.transaction():
            store.db.insert_measurement(
                id=m_id,
                roi_id=info["roi_1"],
                channel_id=info["channels"][0]["id"],
                metric="median",
                scope=SCOPE_WHOLE_ROI,
                value=None,
                pipeline_run_id=info["run_id"],
            )

        # Read it back
        conn = store.db.connection
        row = conn.execute(
            "SELECT value FROM measurements WHERE id = ?", (m_id,)
        ).fetchone()
        assert row["value"] is None


# ===========================================================================
# insert_rois_bulk
# ===========================================================================


class TestInsertRoisBulk:
    """Test the bulk ROI insertion method."""

    def test_bulk_insert_creates_rois(self, populated_store) -> None:
        """insert_rois_bulk inserts multiple ROIs efficiently."""
        store, info = populated_store

        new_ci_1 = new_uuid()
        new_ci_2 = new_uuid()
        with store.db.transaction():
            store.db.insert_cell_identity(
                new_ci_1, info["fov_id"], info["cell_type"]["id"]
            )
            store.db.insert_cell_identity(
                new_ci_2, info["fov_id"], info["cell_type"]["id"]
            )

        roi_tuples = [
            (
                new_uuid(), info["fov_id"], info["cell_type"]["id"],
                new_ci_1, None, 10, 0, 0, 16, 16, 200,
            ),
            (
                new_uuid(), info["fov_id"], info["cell_type"]["id"],
                new_ci_2, None, 11, 16, 16, 16, 16, 150,
            ),
        ]

        with store.db.transaction():
            count = store.db.insert_rois_bulk(roi_tuples)

        assert count == 2

        # Total ROIs on FOV now includes original 3 (2 cells + 1 particle) + 2 new
        all_rois = store.db.get_rois(info["fov_id"])
        assert len(all_rois) == 5

    def test_bulk_insert_empty_list(self, populated_store) -> None:
        """insert_rois_bulk with empty list returns 0."""
        store, _info = populated_store

        with store.db.transaction():
            count = store.db.insert_rois_bulk([])

        assert count == 0


# ===========================================================================
# New FovInfo fields
# ===========================================================================


class TestNewFovFields:
    """Verify new schema 6.0.0 columns on fovs table."""

    def test_display_name_stored(self, populated_store) -> None:
        """display_name column stores and retrieves correctly."""
        store, info = populated_store

        fov_id = new_uuid()
        with store.db.transaction():
            store.db.insert_fov(
                id=fov_id,
                experiment_id=info["exp_id"],
                display_name="My Display Name",
            )

        fov = store.db.get_fov(fov_id)
        assert fov["display_name"] == "My Display Name"

    def test_channel_metadata_json(self, populated_store) -> None:
        """channel_metadata stores valid JSON."""
        store, info = populated_store
        meta = json.dumps({"ch0": {"wavelength_nm": 488}})

        fov_id = new_uuid()
        with store.db.transaction():
            store.db.insert_fov(
                id=fov_id,
                experiment_id=info["exp_id"],
                channel_metadata=meta,
            )

        fov = store.db.get_fov(fov_id)
        assert json.loads(fov["channel_metadata"]) == {"ch0": {"wavelength_nm": 488}}

    def test_lineage_depth_default_zero(self, populated_store) -> None:
        """lineage_depth defaults to 0 for root FOVs."""
        store, info = populated_store

        fov = store.db.get_fov(info["fov_id"])
        assert fov["lineage_depth"] == 0

    def test_pipeline_run_id_on_fov(self, populated_store) -> None:
        """pipeline_run_id can be set on an FOV."""
        store, info = populated_store

        fov_id = new_uuid()
        with store.db.transaction():
            store.db.insert_fov(
                id=fov_id,
                experiment_id=info["exp_id"],
                pipeline_run_id=info["run_id"],
            )

        fov = store.db.get_fov(fov_id)
        assert fov["pipeline_run_id"] == info["run_id"]


# ===========================================================================
# Schema version
# ===========================================================================


class TestSchemaVersion:
    """Verify schema version is 6.0.0."""

    def test_schema_version_constant(self) -> None:
        assert SCHEMA_VERSION == "6.0.0"

    def test_db_schema_version(self, populated_store) -> None:
        """Experiment schema_version is 6.0.0."""
        store, info = populated_store
        exp = store.db.get_experiment()
        assert exp["schema_version"] == "6.0.0"


# ===========================================================================
# Migration backfill: 5.1.0 -> 6.0.0 lineage_path
# ===========================================================================


class TestMigrationBackfill:
    """Test that migration from 5.1.0 to 6.0.0 backfills lineage_path."""

    def _create_5_1_0_database(self, db_path: Path) -> None:
        """Create a minimal 5.1.0-era database with FOVs (no lineage fields)."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        # Minimal 5.1.0 schema (key tables only)
        conn.executescript("""
            CREATE TABLE experiments (
                id              BLOB(16) PRIMARY KEY,
                name            TEXT NOT NULL,
                schema_version  TEXT NOT NULL DEFAULT '5.1.0',
                config_hash     TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE conditions (
                id              BLOB(16) PRIMARY KEY,
                experiment_id   BLOB(16) NOT NULL REFERENCES experiments,
                name            TEXT NOT NULL,
                UNIQUE(experiment_id, name)
            );

            CREATE TABLE bio_reps (
                id              BLOB(16) PRIMARY KEY,
                experiment_id   BLOB(16) NOT NULL REFERENCES experiments,
                condition_id    BLOB(16) NOT NULL REFERENCES conditions,
                name            TEXT NOT NULL,
                UNIQUE(experiment_id, name)
            );

            CREATE TABLE channels (
                id              BLOB(16) PRIMARY KEY,
                experiment_id   BLOB(16) NOT NULL REFERENCES experiments,
                name            TEXT NOT NULL,
                role            TEXT,
                color           TEXT,
                display_order   INTEGER NOT NULL DEFAULT 0,
                UNIQUE(experiment_id, name)
            );

            CREATE TABLE timepoints (
                id              BLOB(16) PRIMARY KEY,
                experiment_id   BLOB(16) NOT NULL REFERENCES experiments,
                name            TEXT NOT NULL,
                time_seconds    REAL,
                display_order   INTEGER NOT NULL DEFAULT 0,
                UNIQUE(experiment_id, name)
            );

            CREATE TABLE roi_type_definitions (
                id              BLOB(16) PRIMARY KEY,
                experiment_id   BLOB(16) NOT NULL REFERENCES experiments,
                name            TEXT NOT NULL,
                parent_type_id  BLOB(16) REFERENCES roi_type_definitions,
                UNIQUE(experiment_id, name)
            );

            CREATE TABLE pipeline_runs (
                id              BLOB(16) PRIMARY KEY,
                operation_name  TEXT NOT NULL,
                config_snapshot TEXT,
                status          TEXT NOT NULL DEFAULT 'running',
                started_at      TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at    TEXT,
                error_message   TEXT
            );

            CREATE TABLE fovs (
                id              BLOB(16) PRIMARY KEY,
                experiment_id   BLOB(16) NOT NULL REFERENCES experiments,
                condition_id    BLOB(16) REFERENCES conditions,
                bio_rep_id      BLOB(16) REFERENCES bio_reps,
                parent_fov_id   BLOB(16) REFERENCES fovs,
                derivation_op   TEXT,
                derivation_params TEXT,
                status          TEXT NOT NULL DEFAULT 'pending',
                auto_name       TEXT,
                zarr_path       TEXT,
                timepoint_id    BLOB(16) REFERENCES timepoints,
                pixel_size_um   REAL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE cell_identities (
                id              BLOB(16) PRIMARY KEY,
                origin_fov_id   BLOB(16) NOT NULL REFERENCES fovs,
                roi_type_id     BLOB(16) NOT NULL REFERENCES roi_type_definitions,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE rois (
                id                  BLOB(16) PRIMARY KEY,
                fov_id              BLOB(16) NOT NULL REFERENCES fovs,
                roi_type_id         BLOB(16) NOT NULL REFERENCES roi_type_definitions,
                cell_identity_id    BLOB(16) REFERENCES cell_identities,
                parent_roi_id       BLOB(16) REFERENCES rois,
                label_id            INTEGER NOT NULL,
                bbox_y              INTEGER NOT NULL,
                bbox_x              INTEGER NOT NULL,
                bbox_h              INTEGER NOT NULL,
                bbox_w              INTEGER NOT NULL,
                area_px             INTEGER NOT NULL
            );

            CREATE TABLE segmentation_sets (
                id                   BLOB(16) PRIMARY KEY,
                experiment_id        BLOB(16) NOT NULL REFERENCES experiments,
                produces_roi_type_id BLOB(16) NOT NULL REFERENCES roi_type_definitions,
                seg_type             TEXT NOT NULL,
                op_config_name       TEXT,
                source_channel       TEXT,
                model_name           TEXT,
                parameters           TEXT,
                fov_count            INTEGER NOT NULL DEFAULT 0,
                total_roi_count      INTEGER NOT NULL DEFAULT 0,
                created_at           TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE threshold_masks (
                id                  BLOB(16) PRIMARY KEY,
                fov_id              BLOB(16) NOT NULL REFERENCES fovs,
                source_channel      TEXT NOT NULL,
                grouping_channel    TEXT,
                method              TEXT NOT NULL,
                threshold_value     REAL NOT NULL,
                histogram           TEXT,
                zarr_path           TEXT,
                status              TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE fov_segmentation_assignments (
                id                  BLOB(16) PRIMARY KEY,
                fov_id              BLOB(16) NOT NULL REFERENCES fovs,
                segmentation_set_id BLOB(16) NOT NULL REFERENCES segmentation_sets,
                roi_type_id         BLOB(16) NOT NULL REFERENCES roi_type_definitions,
                is_active           INTEGER NOT NULL DEFAULT 1,
                pipeline_run_id     BLOB(16) NOT NULL REFERENCES pipeline_runs,
                assigned_by         TEXT,
                assigned_at         TEXT NOT NULL DEFAULT (datetime('now')),
                deactivated_at      TEXT,
                width               INTEGER,
                height              INTEGER,
                roi_count           INTEGER
            );

            CREATE TABLE fov_mask_assignments (
                id                  BLOB(16) PRIMARY KEY,
                fov_id              BLOB(16) NOT NULL REFERENCES fovs,
                threshold_mask_id   BLOB(16) NOT NULL REFERENCES threshold_masks,
                purpose             TEXT NOT NULL,
                is_active           INTEGER NOT NULL DEFAULT 1,
                pipeline_run_id     BLOB(16) NOT NULL REFERENCES pipeline_runs,
                assigned_by         TEXT,
                assigned_at         TEXT NOT NULL DEFAULT (datetime('now')),
                deactivated_at      TEXT
            );

            CREATE TABLE measurements (
                id              BLOB(16) PRIMARY KEY,
                roi_id          BLOB(16) NOT NULL REFERENCES rois,
                channel_id      BLOB(16) NOT NULL REFERENCES channels,
                metric          TEXT NOT NULL,
                scope           TEXT NOT NULL,
                value           REAL NOT NULL,
                pipeline_run_id BLOB(16) NOT NULL REFERENCES pipeline_runs
            );

            CREATE TABLE intensity_groups (
                id              BLOB(16) PRIMARY KEY,
                experiment_id   BLOB(16) NOT NULL REFERENCES experiments,
                name            TEXT NOT NULL,
                channel_id      BLOB(16) NOT NULL REFERENCES channels,
                group_index     INTEGER,
                lower_bound     REAL,
                upper_bound     REAL,
                color_hex       TEXT,
                pipeline_run_id BLOB(16) NOT NULL REFERENCES pipeline_runs,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE cell_group_assignments (
                id                  BLOB(16) PRIMARY KEY,
                intensity_group_id  BLOB(16) NOT NULL REFERENCES intensity_groups,
                roi_id              BLOB(16) NOT NULL REFERENCES rois,
                pipeline_run_id     BLOB(16) NOT NULL REFERENCES pipeline_runs
            );

            CREATE TABLE fov_status_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fov_id      BLOB(16) NOT NULL REFERENCES fovs,
                old_status  TEXT,
                new_status  TEXT NOT NULL,
                message     TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX idx_measurements_roi_channel_scope
                ON measurements(roi_id, channel_id, scope);
            CREATE UNIQUE INDEX idx_measurements_unique_per_run
                ON measurements(roi_id, channel_id, metric, scope, pipeline_run_id);
            CREATE INDEX idx_fovs_parent
                ON fovs(parent_fov_id) WHERE parent_fov_id IS NOT NULL;
            CREATE INDEX idx_fovs_experiment ON fovs(experiment_id);
            CREATE INDEX idx_fovs_condition ON fovs(condition_id) WHERE condition_id IS NOT NULL;
            CREATE INDEX idx_fovs_status ON fovs(status);
            CREATE INDEX idx_rois_fov ON rois(fov_id);
            CREATE INDEX idx_rois_type ON rois(roi_type_id);
            CREATE UNIQUE INDEX idx_roi_identity_fov
                ON rois(cell_identity_id, fov_id)
                WHERE cell_identity_id IS NOT NULL;
            CREATE UNIQUE INDEX idx_fsa_one_active
                ON fov_segmentation_assignments(fov_id, roi_type_id)
                WHERE is_active = 1;
            CREATE UNIQUE INDEX idx_fma_one_active
                ON fov_mask_assignments(fov_id, threshold_mask_id, purpose)
                WHERE is_active = 1;
            CREATE UNIQUE INDEX idx_fovs_zarr_path
                ON fovs(zarr_path)
                WHERE zarr_path IS NOT NULL AND status NOT IN ('deleted');
        """)

        # Insert test data
        exp_id = new_uuid()
        conn.execute(
            "INSERT INTO experiments (id, name, schema_version) VALUES (?, ?, '5.1.0')",
            (exp_id, "Migration Test"),
        )

        # Root FOV
        root_id = new_uuid()
        conn.execute(
            "INSERT INTO fovs (id, experiment_id, status, auto_name) "
            "VALUES (?, ?, 'imported', 'ROOT')",
            (root_id, exp_id),
        )

        # Child FOV (derived from root)
        child_id = new_uuid()
        conn.execute(
            "INSERT INTO fovs (id, experiment_id, parent_fov_id, status, "
            "derivation_op, auto_name) "
            "VALUES (?, ?, ?, 'imported', 'bg_sub', 'ROOT_bg_sub')",
            (child_id, exp_id, root_id),
        )

        # Grandchild FOV (derived from child)
        grandchild_id = new_uuid()
        conn.execute(
            "INSERT INTO fovs (id, experiment_id, parent_fov_id, status, "
            "derivation_op, auto_name) "
            "VALUES (?, ?, ?, 'imported', 'nan_zero', 'ROOT_bg_sub_nan_zero')",
            (grandchild_id, exp_id, child_id),
        )

        conn.commit()
        conn.close()

        return exp_id, root_id, child_id, grandchild_id

    def test_migration_backfills_root_lineage_path(self, tmp_path: Path) -> None:
        """Root FOV gets lineage_path = /<hex(id)> after migration."""
        db_path = tmp_path / "migration_test.db"
        exp_id, root_id, child_id, gc_id = self._create_5_1_0_database(db_path)

        from percell4.core.migration import migrate_database

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        applied = migrate_database(db_path, conn)
        assert "5.1.0->6.0.0" in applied

        # Check root
        root = conn.execute(
            "SELECT lineage_depth, lineage_path FROM fovs WHERE id = ?",
            (root_id,),
        ).fetchone()
        assert root["lineage_depth"] == 0
        assert root["lineage_path"] is not None
        # Path should contain hex representation of root_id
        assert root_id.hex().upper() in root["lineage_path"].upper()

        conn.close()

    def test_migration_backfills_derived_lineage_path(self, tmp_path: Path) -> None:
        """Derived FOVs get correct lineage_depth and lineage_path after migration."""
        db_path = tmp_path / "migration_test.db"
        exp_id, root_id, child_id, gc_id = self._create_5_1_0_database(db_path)

        from percell4.core.migration import migrate_database

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        migrate_database(db_path, conn)

        # Child should have depth 1
        child = conn.execute(
            "SELECT lineage_depth, lineage_path FROM fovs WHERE id = ?",
            (child_id,),
        ).fetchone()
        assert child["lineage_depth"] == 1
        assert child["lineage_path"] is not None
        assert root_id.hex().upper() in child["lineage_path"].upper()
        assert child_id.hex().upper() in child["lineage_path"].upper()

        # Grandchild should have depth 2
        gc = conn.execute(
            "SELECT lineage_depth, lineage_path FROM fovs WHERE id = ?",
            (gc_id,),
        ).fetchone()
        assert gc["lineage_depth"] == 2
        assert gc["lineage_path"] is not None
        assert root_id.hex().upper() in gc["lineage_path"].upper()
        assert child_id.hex().upper() in gc["lineage_path"].upper()
        assert gc_id.hex().upper() in gc["lineage_path"].upper()

        conn.close()

    def test_migration_schema_version_updated(self, tmp_path: Path) -> None:
        """Schema version is 6.0.0 after migration."""
        db_path = tmp_path / "migration_test.db"
        self._create_5_1_0_database(db_path)

        from percell4.core.migration import migrate_database, get_schema_version

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        migrate_database(db_path, conn)
        assert get_schema_version(conn) == "6.0.0"

        conn.close()

    def test_migration_measurements_value_nullable(self, tmp_path: Path) -> None:
        """After migration, measurements.value accepts NULL."""
        db_path = tmp_path / "migration_test.db"
        exp_id, root_id, child_id, gc_id = self._create_5_1_0_database(db_path)

        from percell4.core.migration import migrate_database

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=OFF")  # For testing column definition
        conn.row_factory = sqlite3.Row

        migrate_database(db_path, conn)

        # Insert a ROI type + ROI + pipeline run so we can insert measurement
        rt_id = new_uuid()
        conn.execute(
            "INSERT INTO roi_type_definitions (id, experiment_id, name) "
            "VALUES (?, ?, 'cell')",
            (rt_id, exp_id),
        )
        ch_id = new_uuid()
        conn.execute(
            "INSERT INTO channels (id, experiment_id, name) VALUES (?, ?, 'GFP')",
            (ch_id, exp_id),
        )
        run_id = new_uuid()
        conn.execute(
            "INSERT INTO pipeline_runs (id, operation_name) VALUES (?, 'test')",
            (run_id,),
        )
        roi_id = new_uuid()
        conn.execute(
            "INSERT INTO rois (id, fov_id, roi_type_id, label_id, "
            "bbox_y, bbox_x, bbox_h, bbox_w, area_px) "
            "VALUES (?, ?, ?, 1, 0, 0, 10, 10, 100)",
            (roi_id, root_id, rt_id),
        )

        # This should succeed with NULL value (would fail on old schema)
        m_id = new_uuid()
        conn.execute(
            "INSERT INTO measurements (id, roi_id, channel_id, metric, scope, "
            "value, pipeline_run_id) "
            "VALUES (?, ?, ?, 'mean', 'whole_roi', NULL, ?)",
            (m_id, roi_id, ch_id, run_id),
        )

        row = conn.execute(
            "SELECT value FROM measurements WHERE id = ?", (m_id,)
        ).fetchone()
        assert row["value"] is None

        conn.close()

    def test_migration_creates_backup(self, tmp_path: Path) -> None:
        """Migration creates a backup file."""
        db_path = tmp_path / "migration_test.db"
        self._create_5_1_0_database(db_path)

        from percell4.core.migration import migrate_database

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        migrate_database(db_path, conn)
        conn.close()

        backup = db_path.with_suffix(".db.pre_migration_backup")
        assert backup.exists()
