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
        assert row["percell_version"] == "3.3.0"


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
        conn.execute("UPDATE experiments SET percell_version = '3.3.99'")
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


class TestMigration32To33:
    """Tests for schema migration from 3.2.0 to 3.3.0."""

    def _create_v32_database(self, db_path):
        """Create a database with 3.2.0 schema (old measurements table)."""
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE experiments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                percell_version TEXT NOT NULL DEFAULT '3.2.0',
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
                condition_id INTEGER NOT NULL REFERENCES conditions(id),
                name TEXT NOT NULL DEFAULT 'N1',
                UNIQUE(condition_id, name)
            );

            CREATE TABLE fovs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                bio_rep_id INTEGER NOT NULL REFERENCES bio_reps(id),
                timepoint_id INTEGER REFERENCES timepoints(id),
                width INTEGER,
                height INTEGER,
                pixel_size_um REAL,
                source_file TEXT,
                UNIQUE(name, bio_rep_id, timepoint_id)
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
                UNIQUE(cell_id, channel_id, metric)
            );

            CREATE TABLE threshold_runs (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL REFERENCES channels(id),
                method TEXT NOT NULL,
                parameters TEXT,
                threshold_value REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE analysis_runs (
                id INTEGER PRIMARY KEY,
                plugin_name TEXT NOT NULL,
                parameters TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                cell_count INTEGER,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            );

            CREATE TABLE tags (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                color TEXT
            );

            CREATE TABLE cell_tags (
                cell_id INTEGER NOT NULL REFERENCES cells(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                PRIMARY KEY (cell_id, tag_id)
            );

            CREATE TABLE particles (
                id INTEGER PRIMARY KEY,
                cell_id INTEGER NOT NULL REFERENCES cells(id),
                threshold_run_id INTEGER NOT NULL REFERENCES threshold_runs(id),
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
                eccentricity REAL,
                solidity REAL,
                major_axis_length REAL,
                minor_axis_length REAL,
                mean_intensity REAL,
                max_intensity REAL,
                integrated_intensity REAL,
                UNIQUE(cell_id, threshold_run_id, label_value)
            );

            CREATE INDEX IF NOT EXISTS idx_cells_fov ON cells(fov_id);
            CREATE INDEX IF NOT EXISTS idx_cells_fov_valid ON cells(fov_id, is_valid);
            CREATE INDEX IF NOT EXISTS idx_cells_segmentation ON cells(segmentation_id);
            CREATE INDEX IF NOT EXISTS idx_cells_area ON cells(area_pixels);
            CREATE INDEX IF NOT EXISTS idx_measurements_cell ON measurements(cell_id);
            CREATE INDEX IF NOT EXISTS idx_measurements_channel ON measurements(channel_id);
            CREATE INDEX IF NOT EXISTS idx_measurements_metric ON measurements(metric);
            CREATE INDEX IF NOT EXISTS idx_bio_reps_condition ON bio_reps(condition_id);
            CREATE INDEX IF NOT EXISTS idx_fovs_bio_rep ON fovs(bio_rep_id);
            CREATE INDEX IF NOT EXISTS idx_particles_cell ON particles(cell_id);
            CREATE INDEX IF NOT EXISTS idx_particles_run ON particles(threshold_run_id);

            INSERT INTO experiments (name, percell_version) VALUES ('OldExperiment', '3.2.0');
        """)
        conn.commit()
        return conn

    def test_migration_updates_version(self, tmp_path):
        """Migration updates percell_version from 3.2.0 to 3.3.0."""
        db_path = tmp_path / "old.db"
        old_conn = self._create_v32_database(db_path)
        old_conn.close()

        conn = open_database(db_path)
        row = conn.execute("SELECT percell_version FROM experiments").fetchone()
        assert row["percell_version"] == "3.3.0"
        conn.close()

    def test_migration_adds_scope_column(self, tmp_path):
        """Migration adds scope column to measurements table."""
        db_path = tmp_path / "old.db"
        old_conn = self._create_v32_database(db_path)
        old_conn.close()

        conn = open_database(db_path)
        # Check scope column exists
        cols = conn.execute("PRAGMA table_info(measurements)").fetchall()
        col_names = [c["name"] for c in cols]
        assert "scope" in col_names
        assert "threshold_run_id" in col_names
        conn.close()

    def test_migration_preserves_existing_measurements(self, tmp_path):
        """Migration preserves existing measurement data with scope='whole_cell'."""
        db_path = tmp_path / "old.db"
        old_conn = self._create_v32_database(db_path)
        # Add test data
        old_conn.execute("INSERT INTO channels (id, name) VALUES (1, 'GFP')")
        old_conn.execute("INSERT INTO conditions (id, name) VALUES (1, 'ctrl')")
        old_conn.execute(
            "INSERT INTO bio_reps (id, name, condition_id) VALUES (1, 'N1', 1)"
        )
        old_conn.execute(
            "INSERT INTO fovs (id, name, bio_rep_id) VALUES (1, 'FOV_001', 1)"
        )
        old_conn.execute(
            "INSERT INTO segmentation_runs (id, channel_id, model_name) "
            "VALUES (1, 1, 'test')"
        )
        old_conn.execute(
            "INSERT INTO cells (id, fov_id, segmentation_id, label_value, "
            "centroid_x, centroid_y, bbox_x, bbox_y, bbox_w, bbox_h, area_pixels) "
            "VALUES (1, 1, 1, 1, 10, 20, 0, 0, 50, 50, 100)"
        )
        old_conn.execute(
            "INSERT INTO measurements (cell_id, channel_id, metric, value) "
            "VALUES (1, 1, 'mean_intensity', 42.5)"
        )
        old_conn.commit()
        old_conn.close()

        conn = open_database(db_path)
        row = conn.execute(
            "SELECT cell_id, metric, value, scope, threshold_run_id "
            "FROM measurements WHERE cell_id = 1"
        ).fetchone()
        assert row["cell_id"] == 1
        assert row["metric"] == "mean_intensity"
        assert row["value"] == 42.5
        assert row["scope"] == "whole_cell"
        assert row["threshold_run_id"] is None
        conn.close()

    def test_migration_new_unique_constraint(self, tmp_path):
        """After migration, same cell/channel/metric can exist with different scopes."""
        db_path = tmp_path / "old.db"
        old_conn = self._create_v32_database(db_path)
        # Add minimal data
        old_conn.execute("INSERT INTO channels (id, name) VALUES (1, 'GFP')")
        old_conn.execute("INSERT INTO conditions (id, name) VALUES (1, 'ctrl')")
        old_conn.execute(
            "INSERT INTO bio_reps (id, name, condition_id) VALUES (1, 'N1', 1)"
        )
        old_conn.execute(
            "INSERT INTO fovs (id, name, bio_rep_id) VALUES (1, 'FOV_001', 1)"
        )
        old_conn.execute(
            "INSERT INTO segmentation_runs (id, channel_id, model_name) "
            "VALUES (1, 1, 'test')"
        )
        old_conn.execute(
            "INSERT INTO cells (id, fov_id, segmentation_id, label_value, "
            "centroid_x, centroid_y, bbox_x, bbox_y, bbox_w, bbox_h, area_pixels) "
            "VALUES (1, 1, 1, 1, 10, 20, 0, 0, 50, 50, 100)"
        )
        old_conn.commit()
        old_conn.close()

        conn = open_database(db_path)
        # Insert same cell/channel/metric with different scopes — should not conflict
        conn.execute(
            "INSERT INTO measurements (cell_id, channel_id, metric, value, scope) "
            "VALUES (1, 1, 'mean_intensity', 42.5, 'whole_cell')"
        )
        conn.execute(
            "INSERT INTO measurements (cell_id, channel_id, metric, value, scope) "
            "VALUES (1, 1, 'mean_intensity', 30.0, 'mask_inside')"
        )
        conn.execute(
            "INSERT INTO measurements (cell_id, channel_id, metric, value, scope) "
            "VALUES (1, 1, 'mean_intensity', 12.5, 'mask_outside')"
        )
        conn.commit()

        rows = conn.execute(
            "SELECT scope, value FROM measurements WHERE cell_id = 1 ORDER BY scope"
        ).fetchall()
        assert len(rows) == 3
        scopes = {r["scope"] for r in rows}
        assert scopes == {"whole_cell", "mask_inside", "mask_outside"}
        conn.close()

    def test_migration_check_constraint(self, tmp_path):
        """After migration, invalid scope values are rejected."""
        db_path = tmp_path / "old.db"
        old_conn = self._create_v32_database(db_path)
        old_conn.execute("INSERT INTO channels (id, name) VALUES (1, 'GFP')")
        old_conn.execute("INSERT INTO conditions (id, name) VALUES (1, 'ctrl')")
        old_conn.execute(
            "INSERT INTO bio_reps (id, name, condition_id) VALUES (1, 'N1', 1)"
        )
        old_conn.execute(
            "INSERT INTO fovs (id, name, bio_rep_id) VALUES (1, 'FOV_001', 1)"
        )
        old_conn.execute(
            "INSERT INTO segmentation_runs (id, channel_id, model_name) "
            "VALUES (1, 1, 'test')"
        )
        old_conn.execute(
            "INSERT INTO cells (id, fov_id, segmentation_id, label_value, "
            "centroid_x, centroid_y, bbox_x, bbox_y, bbox_w, bbox_h, area_pixels) "
            "VALUES (1, 1, 1, 1, 10, 20, 0, 0, 50, 50, 100)"
        )
        old_conn.commit()
        old_conn.close()

        conn = open_database(db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO measurements (cell_id, channel_id, metric, value, scope) "
                "VALUES (1, 1, 'mean_intensity', 42.5, 'invalid_scope')"
            )
        conn.close()

    def test_migration_indexes_recreated(self, tmp_path):
        """Migration recreates measurement indexes after table swap."""
        db_path = tmp_path / "old.db"
        old_conn = self._create_v32_database(db_path)
        old_conn.close()

        conn = open_database(db_path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_measurements_%'"
        ).fetchall()
        idx_names = {r["name"] for r in rows}
        assert "idx_measurements_cell" in idx_names
        assert "idx_measurements_channel" in idx_names
        assert "idx_measurements_metric" in idx_names
        conn.close()
