"""Tests for percell3.core.schema."""

import sqlite3

import pytest

from percell3.core.exceptions import ExperimentNotFoundError, SchemaVersionError
from percell3.core.schema import EXPECTED_INDEXES, EXPECTED_TABLES, EXPECTED_VERSION, create_schema, open_database


class TestCreateSchema:
    def test_creates_database_file(self, db_path):
        conn = create_schema(db_path, name="Test")
        assert db_path.exists()
        conn.close()

    def test_all_tables_exist(self, db_conn):
        rows = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        tables = {r["name"] for r in rows}
        assert tables >= EXPECTED_TABLES

    def test_all_indexes_exist(self, db_conn):
        rows = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        indexes = {r["name"] for r in rows}
        assert indexes >= EXPECTED_INDEXES

    def test_wal_mode(self, db_conn):
        mode = db_conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, db_conn):
        fk = db_conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_experiment_singleton_row(self, db_conn):
        row = db_conn.execute("SELECT name, description FROM experiments").fetchone()
        assert row["name"] == "Test Experiment"
        assert row["description"] == "A test"

    def test_experiment_has_version(self, db_conn):
        row = db_conn.execute("SELECT percell_version FROM experiments").fetchone()
        assert row["percell_version"] == "4.0.0"

    def test_no_active_measurement_config_column(self, db_conn):
        """Experiments table should NOT have active_measurement_config_id."""
        cols = {
            r["name"]
            for r in db_conn.execute("PRAGMA table_info(experiments)").fetchall()
        }
        assert "active_measurement_config_id" not in cols

    def test_segmentations_table_structure(self, db_conn):
        """segmentations table has global structure with seg_type."""
        cols = {
            r["name"]
            for r in db_conn.execute("PRAGMA table_info(segmentations)").fetchall()
        }
        assert "seg_type" in cols
        assert "source_fov_id" in cols
        assert "width" in cols
        assert "height" in cols
        assert "name" in cols
        # Should NOT have fov_id (global entity)
        assert "fov_id" not in cols

    def test_segmentations_seg_type_constraint(self, db_conn):
        """seg_type CHECK constraint rejects invalid values."""
        db_conn.execute(
            "INSERT INTO conditions (name) VALUES ('c1')"
        )
        db_conn.execute(
            "INSERT INTO bio_reps (name) VALUES ('N1')"
        )
        db_conn.execute(
            "INSERT INTO fovs (display_name, condition_id, bio_rep_id, width, height) "
            "VALUES ('fov1', 1, 1, 100, 100)"
        )
        db_conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO segmentations (name, seg_type, width, height) "
                "VALUES ('bad', 'invalid_type', 100, 100)"
            )

    def test_thresholds_table_structure(self, db_conn):
        """thresholds table has global structure with source metadata."""
        cols = {
            r["name"]
            for r in db_conn.execute("PRAGMA table_info(thresholds)").fetchall()
        }
        assert "source_fov_id" in cols
        assert "source_channel" in cols
        assert "grouping_channel" in cols
        assert "width" in cols
        assert "height" in cols
        assert "name" in cols
        # Should NOT have fov_id or channel_id (global entity)
        assert "fov_id" not in cols
        assert "channel_id" not in cols

    def test_particles_table_uses_fov_and_threshold(self, db_conn):
        """particles table uses fov_id + threshold_id, not cell_id."""
        cols = {
            r["name"]
            for r in db_conn.execute("PRAGMA table_info(particles)").fetchall()
        }
        assert "fov_id" in cols
        assert "threshold_id" in cols
        assert "cell_id" not in cols

    def test_measurements_has_segmentation_id(self, db_conn):
        """measurements table has segmentation_id provenance column."""
        cols = {
            r["name"]
            for r in db_conn.execute("PRAGMA table_info(measurements)").fetchall()
        }
        assert "segmentation_id" in cols
        assert "threshold_id" in cols
        assert "measured_at" in cols
        # Old column name should not exist
        assert "threshold_run_id" not in cols

    def test_fov_config_table_structure(self, db_conn):
        """fov_config table has config_id, fov_id, segmentation_id, threshold_id, scopes."""
        cols = {
            r["name"]
            for r in db_conn.execute("PRAGMA table_info(fov_config)").fetchall()
        }
        assert "config_id" in cols
        assert "fov_id" in cols
        assert "segmentation_id" in cols
        assert "threshold_id" in cols
        assert "scopes" in cols

    def test_analysis_config_table_structure(self, db_conn):
        """analysis_config table has experiment_id FK."""
        cols = {
            r["name"]
            for r in db_conn.execute("PRAGMA table_info(analysis_config)").fetchall()
        }
        assert "experiment_id" in cols
        assert "created_at" in cols

    def test_old_tables_do_not_exist(self, db_conn):
        """segmentation_runs, threshold_runs, measurement_configs should not exist."""
        rows = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {r["name"] for r in rows}
        assert "segmentation_runs" not in tables
        assert "threshold_runs" not in tables
        assert "measurement_configs" not in tables
        assert "measurement_config_entries" not in tables


class TestOpenDatabase:
    def test_open_existing(self, db_path):
        create_schema(db_path, name="Test").close()
        conn = open_database(db_path)
        name = conn.execute("SELECT name FROM experiments").fetchone()["name"]
        assert name == "Test"
        conn.close()

    def test_open_nonexistent_raises(self, tmp_path):
        with pytest.raises(ExperimentNotFoundError):
            open_database(tmp_path / "nope.db")

    def test_old_version_raises(self, tmp_path):
        """Opening a database with an old schema version raises SchemaVersionError."""
        db_path = tmp_path / "old.db"
        conn = create_schema(db_path, name="Old")
        conn.execute("UPDATE experiments SET percell_version = '2.0.0'")
        conn.commit()
        conn.close()

        with pytest.raises(SchemaVersionError, match="version mismatch"):
            open_database(db_path)

    def test_compatible_patch_version_ok(self, tmp_path):
        """Different patch version with same major should open fine."""
        db_path = tmp_path / "patch.db"
        conn = create_schema(db_path, name="Patch")
        conn.execute("UPDATE experiments SET percell_version = '4.0.99'")
        conn.commit()
        conn.close()

        conn = open_database(db_path)
        conn.close()

    def test_current_version_ok(self, tmp_path):
        """Database with current version should open fine."""
        db_path = tmp_path / "current.db"
        create_schema(db_path, name="Current").close()
        conn = open_database(db_path)
        conn.close()


class TestEnsureMissingTables:
    """Tests for _ensure_tables creating missing tables on open."""

    def test_missing_tables_created(self, tmp_path):
        """Opening a database missing some tables creates them."""
        db_path = tmp_path / "nop.db"
        # Create a minimal 4.0.0 database WITHOUT particles, tags, configs, etc.
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE experiments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                percell_version TEXT NOT NULL DEFAULT '4.0.0',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE channels (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                role TEXT,
                excitation_nm REAL,
                emission_nm REAL,
                color TEXT,
                is_segmentation INTEGER NOT NULL DEFAULT 0,
                display_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE conditions (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE timepoints (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                time_seconds REAL,
                display_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE bio_reps (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE fovs (
                id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL UNIQUE,
                condition_id INTEGER NOT NULL REFERENCES conditions(id),
                bio_rep_id INTEGER NOT NULL REFERENCES bio_reps(id),
                timepoint_id INTEGER REFERENCES timepoints(id),
                width INTEGER,
                height INTEGER,
                pixel_size_um REAL,
                source_file TEXT
            );

            INSERT INTO experiments (name, percell_version) VALUES ('Test', '4.0.0');
        """)
        conn.commit()
        conn.close()

        # Open — should create missing tables automatically
        conn = open_database(db_path)
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "segmentations" in tables
        assert "thresholds" in tables
        assert "particles" in tables
        assert "fov_status_cache" in tables
        assert "fov_tags" in tables
        assert "analysis_config" in tables
        assert "fov_config" in tables
        assert tables >= EXPECTED_TABLES
        conn.close()
