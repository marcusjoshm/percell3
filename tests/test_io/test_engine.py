"""Tests for percell3.io.engine."""

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell3.core import ExperimentStore
from percell3.io.engine import ImportEngine
from percell3.io.models import (
    ChannelMapping,
    ImportPlan,
    TokenConfig,
    ZTransform,
)


def _make_tiff_dir(base: Path, layout: dict[str, np.ndarray]) -> Path:
    """Create a directory with TIFF files from a layout dict.

    Args:
        base: Parent directory.
        layout: Dict of filename -> numpy array.

    Returns:
        Path to the directory.
    """
    d = base / "tiffs"
    d.mkdir(exist_ok=True)
    for name, data in layout.items():
        tifffile.imwrite(str(d / name), data)
    return d


class TestSingleChannelImport:
    def test_imports_one_region(self, tmp_path):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={"img": "Region1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.regions_imported == 1
            assert result.channels_registered == 1
            assert result.images_written == 1

            # Verify data round-trips
            img = store.read_image_numpy("Region1", "control", "DAPI")
            np.testing.assert_array_equal(img, data)


class TestMultiChannelImport:
    def test_imports_two_channels(self, tmp_path):
        dapi = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        gfp = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {
            "img_ch00.tif": dapi,
            "img_ch01.tif": gfp,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[
                    ChannelMapping(token_value="00", name="DAPI"),
                    ChannelMapping(token_value="01", name="GFP"),
                ],
                region_names={"img": "Region1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.channels_registered == 2
            assert result.images_written == 2

            img_dapi = store.read_image_numpy("Region1", "control", "DAPI")
            img_gfp = store.read_image_numpy("Region1", "control", "GFP")
            np.testing.assert_array_equal(img_dapi, dapi)
            np.testing.assert_array_equal(img_gfp, gfp)


class TestMultiRegionImport:
    def test_imports_two_regions(self, tmp_path):
        r1 = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        r2 = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {
            "region1_ch00.tif": r1,
            "region2_ch00.tif": r2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={},  # use defaults
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.regions_imported == 2


class TestZProjectionImport:
    def test_mip_projection(self, tmp_path):
        z0 = np.ones((32, 32), dtype=np.uint16) * 10
        z1 = np.ones((32, 32), dtype=np.uint16) * 50
        z2 = np.ones((32, 32), dtype=np.uint16) * 30
        tiff_dir = _make_tiff_dir(tmp_path, {
            "img_ch00_z00.tif": z0,
            "img_ch00_z01.tif": z1,
            "img_ch00_z02.tif": z2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={"img": "Region1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.images_written == 1
            img = store.read_image_numpy("Region1", "control", "DAPI")
            assert img[0, 0] == 50  # max of 10, 50, 30


class TestChannelMapping:
    def test_renames_channels(self, tmp_path):
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[
                    ChannelMapping(token_value="00", name="DAPI", color="#0000FF"),
                ],
                region_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            engine.execute(plan, store)

            channels = store.get_channels()
            assert len(channels) == 1
            assert channels[0].name == "DAPI"


class TestRegionRenaming:
    def test_renames_regions(self, tmp_path):
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"myregion_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={"myregion": "Well_A1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            engine.execute(plan, store)

            regions = store.get_regions(condition="control")
            assert len(regions) == 1
            assert regions[0].name == "Well_A1"


class TestIncrementalImport:
    def test_skip_existing_region(self, tmp_path):
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={"img": "Region1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()

            # First import
            r1 = engine.execute(plan, store)
            assert r1.regions_imported == 1
            assert r1.skipped == 0

            # Second import — region already exists
            r2 = engine.execute(plan, store)
            assert r2.regions_imported == 0
            assert r2.skipped == 1
            assert any("already exists" in w for w in r2.warnings)


class TestProgressCallback:
    def test_callback_called(self, tmp_path):
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={"img": "Region1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            calls = []
            engine = ImportEngine()
            engine.execute(plan, store, progress_callback=lambda c, t, n: calls.append((c, t, n)))

            assert len(calls) == 1
            assert calls[0] == (1, 1, "Region1")


class TestMultiConditionImport:
    def test_imports_two_conditions(self, tmp_path):
        """Files from 2 conditions via condition_map are imported correctly."""
        d1 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        d2 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {
            "ctrl_s00_ch00.tif": d1,
            "treated_s00_ch00.tif": d2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="default",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={"ctrl_s00": "s00", "treated_s00": "s00"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
                condition_map={
                    "ctrl_s00": "ctrl",
                    "treated_s00": "treated",
                },
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.regions_imported == 2
            assert result.channels_registered == 1

            conds = store.get_conditions()
            assert "ctrl" in conds
            assert "treated" in conds

            regions_ctrl = store.get_regions(condition="ctrl")
            regions_treated = store.get_regions(condition="treated")
            assert len(regions_ctrl) == 1
            assert len(regions_treated) == 1
            assert regions_ctrl[0].name == "s00"
            assert regions_treated[0].name == "s00"

    def test_condition_map_empty_uses_fallback(self, tmp_path):
        """When condition_map is empty, single condition field is used."""
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
                condition_map={},
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.regions_imported == 1
            conds = store.get_conditions()
            assert conds == ["control"]

    def test_skip_existing_per_condition(self, tmp_path):
        """Same region name in different conditions doesn't conflict."""
        d1 = np.zeros((32, 32), dtype=np.uint16)
        d2 = np.ones((32, 32), dtype=np.uint16) * 100
        tiff_dir = _make_tiff_dir(tmp_path, {
            "ctrl_s00_ch00.tif": d1,
            "treated_s00_ch00.tif": d2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="default",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={"ctrl_s00": "s00", "treated_s00": "s00"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
                condition_map={
                    "ctrl_s00": "ctrl",
                    "treated_s00": "treated",
                },
            )
            engine = ImportEngine()

            # First import — both regions imported
            r1 = engine.execute(plan, store)
            assert r1.regions_imported == 2
            assert r1.skipped == 0

            # Second import — both regions skipped
            r2 = engine.execute(plan, store)
            assert r2.regions_imported == 0
            assert r2.skipped == 2


class TestEdgeCases:
    def test_invalid_source_path(self, tmp_path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=Path("/nonexistent"),
                condition="control",
                channel_mappings=[],
                region_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            with pytest.raises(FileNotFoundError):
                engine.execute(plan, store)

    def test_empty_directory(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=d,
                condition="control",
                channel_mappings=[],
                region_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            with pytest.raises(ValueError, match="No TIFF"):
                engine.execute(plan, store)

    def test_elapsed_seconds_populated(self, tmp_path):
        data = np.zeros((16, 16), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                region_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)
            assert result.elapsed_seconds >= 0
