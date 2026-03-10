"""Tests for ImageCalculatorPlugin — pixel arithmetic creates derived FOVs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.plugins.image_calculator import ImageCalculatorPlugin

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def calc_store(tmp_path: Path):
    """Create an ExperimentStore with one FOV for calculator tests."""
    percell_dir = tmp_path / "calc.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    exp_id = exp["id"]

    # Create FOV: DAPI=100, GFP=50
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)
    channel_arrays = {
        0: np.ones((32, 32), dtype=np.uint16) * 100,
        1: np.ones((32, 32), dtype=np.uint16) * 50,
    }
    zarr_path = store.layers.write_image_channels(fov_hex, channel_arrays)

    with store.transaction():
        store.insert_fov(
            id=fov_id,
            experiment_id=exp_id,
            status="pending",
            auto_name="FOV_CALC",
            zarr_path=zarr_path,
        )
        store.set_fov_status(fov_id, FovStatus.imported, "test")

    yield store, {"fov_id": fov_id, "exp_id": exp_id}
    store.close()


def test_add_single_channel(calc_store) -> None:
    """Single-channel add with constant creates correct derived FOV."""
    store, info = calc_store

    plugin = ImageCalculatorPlugin()
    result = plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        mode="single_channel",
        operation="add",
        channel_a="DAPI",
        constant=50.0,
    )

    assert result.derived_fovs_created == 1
    assert not result.errors

    # Find derived FOV
    all_fovs = store.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    assert len(derived) == 1

    derived_hex = uuid_to_hex(derived[0]["id"])
    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)
    # 100 + 50 = 150
    assert ch0[0, 0] == 150


def test_subtract_two_channel(calc_store) -> None:
    """Two-channel subtract creates correct derived FOV."""
    store, info = calc_store

    plugin = ImageCalculatorPlugin()
    result = plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        mode="two_channel",
        operation="subtract",
        channel_a="DAPI",
        channel_b="GFP",
    )

    assert result.derived_fovs_created == 1

    all_fovs = store.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_hex = uuid_to_hex(derived[0]["id"])

    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)
    # 100 - 50 = 50
    assert ch0[0, 0] == 50

    # Channel B should be zeroed
    ch1 = store.layers.read_image_channel_numpy(derived_hex, 1)
    assert ch1[0, 0] == 0


def test_requires_mode(calc_store) -> None:
    """Raises without mode parameter."""
    store, info = calc_store
    plugin = ImageCalculatorPlugin()
    with pytest.raises(RuntimeError, match="mode"):
        plugin.run(
            store,
            fov_ids=[info["fov_id"]],
            operation="add",
            channel_a="DAPI",
        )


def test_requires_constant_for_single_channel(calc_store) -> None:
    """Single-channel mode requires constant."""
    store, info = calc_store
    plugin = ImageCalculatorPlugin()
    with pytest.raises(RuntimeError, match="constant"):
        plugin.run(
            store,
            fov_ids=[info["fov_id"]],
            mode="single_channel",
            operation="add",
            channel_a="DAPI",
        )
