"""Schema migration runner for .percell databases."""

from __future__ import annotations

import sqlite3

MIGRATIONS: dict[str, list[str]] = {
    "5.0.0->5.1.0": [
        "ALTER TABLE fovs ADD COLUMN pixel_size_um REAL",
        "UPDATE experiments SET schema_version = '5.1.0' WHERE 1=1",
    ],
}

SCHEMA_VERSION = "5.1.0"


def get_schema_version(conn: sqlite3.Connection) -> str:
    """Read current schema version from database.

    The version is stored in the ``experiments`` table's
    ``schema_version`` column (single-experiment-per-DB convention).
    """
    row = conn.execute(
        "SELECT schema_version FROM experiments LIMIT 1"
    ).fetchone()
    if row is None:
        return "unknown"
    # Support both dict-like Row and plain tuple
    try:
        return row["schema_version"]
    except (TypeError, IndexError):
        return row[0]


def run_migrations(
    conn: sqlite3.Connection, current: str, target: str
) -> list[str]:
    """Apply migrations from *current* to *target* version.

    Returns list of applied migration keys.
    """
    applied: list[str] = []
    for key, statements in MIGRATIONS.items():
        from_ver, to_ver = key.split("->")
        if from_ver == current:
            for sql in statements:
                conn.execute(sql)
            applied.append(key)
            current = to_ver
            if current == target:
                break
    return applied
