"""Shared fixtures for IO module tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell3.core import ExperimentStore


@pytest.fixture
def tiff_dir(tmp_path: Path) -> Path:
    """Create a directory with synthetic TIFF files.

    Layout: img_ch00_t00.tif, img_ch01_t00.tif (2 channels, 1 timepoint)
    """
    d = tmp_path / "tiffs"
    d.mkdir()
    for ch in (0, 1):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tifffile.imwrite(str(d / f"img_ch{ch:02d}_t00.tif"), data)
    return d


@pytest.fixture
def tiff_dir_multichannel_multiregion(tmp_path: Path) -> Path:
    """Create a directory with multiple regions and channels.

    Layout: region1_ch00.tif, region1_ch01.tif, region2_ch00.tif, region2_ch01.tif
    """
    d = tmp_path / "tiffs"
    d.mkdir()
    for region in ("region1", "region2"):
        for ch in (0, 1):
            data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
            tifffile.imwrite(str(d / f"{region}_ch{ch:02d}.tif"), data)
    return d


@pytest.fixture
def tiff_dir_with_z(tmp_path: Path) -> Path:
    """Create a directory with Z-stack TIFF files.

    Layout: img_ch00_z00.tif, img_ch00_z01.tif, img_ch00_z02.tif
    """
    d = tmp_path / "tiffs"
    d.mkdir()
    for z in range(3):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tifffile.imwrite(str(d / f"img_ch00_z{z:02d}.tif"), data)
    return d


@pytest.fixture
def experiment_store(tmp_path: Path) -> ExperimentStore:
    """Create a fresh ExperimentStore for import testing."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    yield store
    store.close()
