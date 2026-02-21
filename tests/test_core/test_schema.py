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
        assert row["percell_version"] == "3.4.0"


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
        """Different patch version with same major.minor should open fine."""
        db_path = tmp_path / "patch.db"
        conn = create_schema(db_path, name="Patch")
        conn.execute("UPDATE experiments SET percell_version = '3.4.99'")
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
        # Create a minimal 3.4.0 database WITHOUT particles, tags, etc.
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE experiments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                percell_version TEXT NOT NULL DEFAULT '3.4.0',
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

            CREATE TABLE segmentation_runs (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL REFERENCES channels(id),
                model_name TEXT NOT NULL,
                parameters TEXT,
                cell_count INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE cells (
                id INTEGER PRIMARY KEY,
                fov_id INTEGER NOT NULL REFERENCES fovs(id),
                segmentation_id INTEGER NOT NULL REFERENCES segmentation_runs(id),
                label_value INTEGER NOT NULL,
                centroid_x REAL NOT NULL,
                centroid_y REAL NOT NULL,
                bbox_x INTEGER NOT NULL,
                bbox_y INTEGER NOT NULL,
                bbox_w INTEGER NOT NULL,
                bbox_h INTEGER NOT NULL,
                area_pixels REAL NOT NULL,
                area_um2 REAL,
                perimeter REAL,
                circularity REAL,
                is_valid INTEGER NOT NULL DEFAULT 1,
                UNIQUE(fov_id, segmentation_id, label_value)
            );

            CREATE TABLE measurements (
                id INTEGER PRIMARY KEY,
                cell_id INTEGER NOT NULL REFERENCES cells(id),
                channel_id INTEGER NOT NULL REFERENCES channels(id),
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                scope TEXT NOT NULL DEFAULT 'whole_cell',
                threshold_run_id INTEGER REFERENCES threshold_runs(id),
                UNIQUE(cell_id, channel_id, metric, scope),
                CHECK(scope IN ('whole_cell', 'mask_inside', 'mask_outside'))
            );

            CREATE TABLE threshold_runs (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL REFERENCES channels(id),
                method TEXT NOT NULL,
                parameters TEXT,
                threshold_value REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            INSERT INTO experiments (name, percell_version) VALUES ('Test', '3.4.0');
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
        assert "particles" in tables
        assert "fov_status_cache" in tables
        assert "fov_tags" in tables
        assert tables >= EXPECTED_TABLES
        conn.close()
