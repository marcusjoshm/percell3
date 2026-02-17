"""Tests for percell3.core.schema."""

import sqlite3

import pytest

from percell3.core.exceptions import ExperimentNotFoundError
from percell3.core.schema import EXPECTED_INDEXES, EXPECTED_TABLES, create_schema, open_database


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
        assert row["percell_version"] == "3.1.0"


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
