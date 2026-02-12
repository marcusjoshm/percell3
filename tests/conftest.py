"""Shared test fixtures for PerCell 3."""

import numpy as np
import pytest


@pytest.fixture
def tmp_experiment(tmp_path):
    """Create a temporary .percell directory path."""
    return tmp_path / "test.percell"
