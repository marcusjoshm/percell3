"""Migration runner tests — verify schema versioning and migration mechanics."""

from __future__ import annotations

from pathlib import Path

import pytest

from percell4.core.db_types import new_uuid
from percell4.core.experiment_db import ExperimentDB
from percell4.core.migration import (
    MIGRATIONS,
    SCHEMA_VERSION,
    get_schema_version,
    run_migrations,
)


@pytest.fixture()
def db_with_experiment(tmp_path: Path) -> ExperimentDB:
    """Create a DB with a single experiment record."""
    db = ExperimentDB(tmp_path / "experiment.db")
    db.open()
    with db.transaction():
        db.insert_experiment(new_uuid(), "Migration Test")
    yield db
    db.close()


def test_get_schema_version(db_with_experiment: ExperimentDB) -> None:
    """Schema version reads back as 5.1.0 from a freshly created DB."""
    version = get_schema_version(db_with_experiment.connection)
    assert version == "5.1.0"


def test_get_schema_version_empty_db(tmp_path: Path) -> None:
    """Returns 'unknown' if experiments table is empty."""
    db = ExperimentDB(tmp_path / "empty.db")
    db.open()
    try:
        # Delete the experiment so the table is empty
        version = get_schema_version(db.connection)
        assert version == "unknown"
    finally:
        db.close()


def test_run_migrations_empty(db_with_experiment: ExperimentDB) -> None:
    """No migrations to apply when current == target, returns empty list."""
    applied = run_migrations(
        db_with_experiment.connection, SCHEMA_VERSION, SCHEMA_VERSION
    )
    assert applied == []


def test_run_migrations_applies(db_with_experiment: ExperimentDB) -> None:
    """A mock migration is discovered and applied correctly."""
    # Temporarily add a mock migration
    test_key = "5.1.0->5.2.0"
    MIGRATIONS[test_key] = [
        "ALTER TABLE experiments ADD COLUMN test_col TEXT",
        "UPDATE experiments SET schema_version = '5.2.0'",
    ]
    try:
        applied = run_migrations(
            db_with_experiment.connection, "5.1.0", "5.2.0"
        )
        assert applied == [test_key]

        # Verify the ALTER actually ran
        row = db_with_experiment.connection.execute(
            "SELECT test_col FROM experiments LIMIT 1"
        ).fetchone()
        assert row is not None  # column exists

        # Verify version was updated
        version = get_schema_version(db_with_experiment.connection)
        assert version == "5.2.0"
    finally:
        # Clean up the mock migration
        MIGRATIONS.pop(test_key, None)


def test_migration_5_0_0_to_5_1_0_exists() -> None:
    """The 5.0.0->5.1.0 migration key is present in MIGRATIONS."""
    assert "5.0.0->5.1.0" in MIGRATIONS


def test_migration_5_0_0_to_5_1_0_adds_pixel_size_um(tmp_path: Path) -> None:
    """Applying the 5.0.0->5.1.0 migration adds pixel_size_um to fovs.

    This simulates an existing database created at schema 5.0.0 (without
    pixel_size_um) and verifies the migration adds the column.
    """
    import sqlite3

    from percell4.core.schema import _configure_connection

    # Create a minimal 5.0.0 database without pixel_size_um
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    _configure_connection(conn)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS experiments ("
        "  id BLOB(16) PRIMARY KEY, name TEXT NOT NULL, "
        "  schema_version TEXT NOT NULL DEFAULT '5.0.0', "
        "  created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fovs ("
        "  id BLOB(16) PRIMARY KEY, experiment_id BLOB(16) NOT NULL, "
        "  status TEXT NOT NULL DEFAULT 'pending', "
        "  created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    from percell4.core.db_types import new_uuid

    eid = new_uuid()
    conn.execute(
        "INSERT INTO experiments (id, name) VALUES (?, ?)",
        (eid, "Old Experiment"),
    )
    conn.commit()

    # Apply migration
    applied = run_migrations(conn, "5.0.0", "5.1.0")
    assert applied == ["5.0.0->5.1.0"]
    conn.commit()

    # Verify pixel_size_um column exists and works
    fid = new_uuid()
    conn.execute(
        "INSERT INTO fovs (id, experiment_id, pixel_size_um) VALUES (?, ?, ?)",
        (fid, eid, 0.65),
    )
    row = conn.execute(
        "SELECT pixel_size_um FROM fovs WHERE id = ?", (fid,)
    ).fetchone()
    assert row[0] == pytest.approx(0.65)

    # Verify version bumped
    version = get_schema_version(conn)
    assert version == "5.1.0"
    conn.close()
