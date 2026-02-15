"""Shared fixtures for CLI module tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile
from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def experiment(tmp_path: Path) -> ExperimentStore:
    """Create a fresh experiment for CLI testing."""
    store = ExperimentStore.create(tmp_path / "test.percell", name="Test")
    yield store
    store.close()


@pytest.fixture
def experiment_path(experiment: ExperimentStore) -> Path:
    """Path to the test experiment."""
    return experiment.path


@pytest.fixture
def experiment_with_data(experiment: ExperimentStore) -> ExperimentStore:
    """Experiment with channels, conditions, regions, and images."""
    experiment.add_channel("DAPI", role="nuclear")
    experiment.add_channel("GFP")
    experiment.add_condition("control")
    data = np.zeros((64, 64), dtype=np.uint16)
    experiment.add_region(
        "region1", "control", width=64, height=64, pixel_size_um=0.65,
    )
    experiment.write_image("region1", "control", "DAPI", data)
    experiment.write_image("region1", "control", "GFP", data)
    return experiment


@pytest.fixture
def tiff_dir(tmp_path: Path) -> Path:
    """Create a directory with synthetic TIFF files for import testing."""
    d = tmp_path / "tiffs"
    d.mkdir()
    for ch in (0, 1):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tifffile.imwrite(str(d / f"img_ch{ch:02d}_t00.tif"), data)
    return d


@pytest.fixture
def multi_condition_tiff_dir(tmp_path: Path) -> Path:
    """Create TIFFs with multi-condition naming (ctrl_s00, treated_s00)."""
    d = tmp_path / "multi_cond_tiffs"
    d.mkdir()
    for cond in ("ctrl", "treated"):
        for site in ("s00",):
            data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
            tifffile.imwrite(str(d / f"{cond}_{site}_ch00.tif"), data)
    return d
