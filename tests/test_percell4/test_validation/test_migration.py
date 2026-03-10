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
    """Schema version reads back as 5.0.0 from a freshly created DB."""
    version = get_schema_version(db_with_experiment.connection)
    assert version == "5.0.0"


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
    test_key = "5.0.0->5.1.0"
    MIGRATIONS[test_key] = [
        "ALTER TABLE experiments ADD COLUMN test_col TEXT",
        "UPDATE experiments SET schema_version = '5.1.0'",
    ]
    try:
        applied = run_migrations(
            db_with_experiment.connection, "5.0.0", "5.1.0"
        )
        assert applied == [test_key]

        # Verify the ALTER actually ran
        row = db_with_experiment.connection.execute(
            "SELECT test_col FROM experiments LIMIT 1"
        ).fetchone()
        assert row is not None  # column exists

        # Verify version was updated
        version = get_schema_version(db_with_experiment.connection)
        assert version == "5.1.0"
    finally:
        # Clean up the mock migration
        MIGRATIONS.pop(test_key, None)
