"""Shared fixtures for core module tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from percell3.core.schema import create_schema


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "experiment.db"


@pytest.fixture
def db_conn(db_path: Path) -> sqlite3.Connection:
    """A fresh database connection with the full schema."""
    conn = create_schema(db_path, name="Test Experiment", description="A test")
    yield conn
    conn.close()
