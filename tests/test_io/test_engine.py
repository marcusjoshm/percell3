"""Tests for percell3.io.engine."""

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell3.core import ExperimentStore
from percell3.io.engine import ImportEngine
from percell3.io.engine import build_tile_grid, stitch_tiles
from percell3.io.models import (
    ChannelMapping,
    ImportPlan,
    TileConfig,
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
    def test_imports_one_fov(self, tmp_path):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"img": "FOV1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 1
            assert result.channels_registered == 1
            assert result.images_written == 1

            # Verify data round-trips
            fov = store.get_fovs(condition="control")[0]
            img = store.read_image_numpy(fov.id, "DAPI")
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
                fov_names={"img": "FOV1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.channels_registered == 2
            assert result.images_written == 2

            fov = store.get_fovs(condition="control")[0]
            img_dapi = store.read_image_numpy(fov.id, "DAPI")
            img_gfp = store.read_image_numpy(fov.id, "GFP")
            np.testing.assert_array_equal(img_dapi, dapi)
            np.testing.assert_array_equal(img_gfp, gfp)


class TestMultiFOVImport:
    def test_imports_two_fovs(self, tmp_path):
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
                fov_names={},  # use defaults
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 2


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
                fov_names={"img": "FOV1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.images_written == 1
            fov = store.get_fovs(condition="control")[0]
            img = store.read_image_numpy(fov.id, "DAPI")
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
                fov_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            engine.execute(plan, store)

            channels = store.get_channels()
            assert len(channels) == 1
            assert channels[0].name == "DAPI"


class TestFOVRenaming:
    def test_renames_fovs(self, tmp_path):
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"myregion_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"myregion": "Well_A1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            engine.execute(plan, store)

            fovs = store.get_fovs(condition="control")
            assert len(fovs) == 1
            assert fovs[0].display_name == "control_N1_Well_A1"


class TestIncrementalImport:
    def test_skip_existing_fov(self, tmp_path):
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"img": "FOV1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()

            # First import
            r1 = engine.execute(plan, store)
            assert r1.fovs_imported == 1
            assert r1.skipped == 0

            # Second import — FOV already exists
            r2 = engine.execute(plan, store)
            assert r2.fovs_imported == 0
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
                fov_names={"img": "FOV1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            calls = []
            engine = ImportEngine()
            engine.execute(plan, store, progress_callback=lambda c, t, n: calls.append((c, t, n)))

            assert len(calls) == 1
            assert calls[0] == (1, 1, "control_N1_FOV1")


class TestMultiConditionImport:
    def test_imports_two_conditions(self, tmp_path):
        """Files from 2 conditions via condition_map are imported correctly."""
        d1 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        d2 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {
            "ctrl_fov1_ch00.tif": d1,
            "treated_fov1_ch00.tif": d2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="default",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"ctrl_fov1": "fov1", "treated_fov1": "fov1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
                condition_map={
                    "ctrl_fov1": "ctrl",
                    "treated_fov1": "treated",
                },
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 2
            assert result.channels_registered == 1

            conds = store.get_conditions()
            assert "ctrl" in conds
            assert "treated" in conds

            fovs_ctrl = store.get_fovs(condition="ctrl")
            fovs_treated = store.get_fovs(condition="treated")
            assert len(fovs_ctrl) == 1
            assert len(fovs_treated) == 1
            assert fovs_ctrl[0].display_name == "ctrl_N1_fov1"
            assert fovs_treated[0].display_name == "treated_N1_fov1"

    def test_condition_map_empty_uses_fallback(self, tmp_path):
        """When condition_map is empty, single condition field is used."""
        data = np.zeros((32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
                condition_map={},
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 1
            conds = store.get_conditions()
            assert conds == ["control"]

    def test_skip_existing_per_condition(self, tmp_path):
        """Same FOV name in different conditions doesn't conflict."""
        d1 = np.zeros((32, 32), dtype=np.uint16)
        d2 = np.ones((32, 32), dtype=np.uint16) * 100
        tiff_dir = _make_tiff_dir(tmp_path, {
            "ctrl_fov1_ch00.tif": d1,
            "treated_fov1_ch00.tif": d2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="default",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"ctrl_fov1": "fov1", "treated_fov1": "fov1"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
                condition_map={
                    "ctrl_fov1": "ctrl",
                    "treated_fov1": "treated",
                },
            )
            engine = ImportEngine()

            # First import — both FOVs imported
            r1 = engine.execute(plan, store)
            assert r1.fovs_imported == 2
            assert r1.skipped == 0

            # Second import — both FOVs skipped
            r2 = engine.execute(plan, store)
            assert r2.fovs_imported == 0
            assert r2.skipped == 2


class TestBioRepMap:
    def test_per_group_bio_rep(self, tmp_path):
        """bio_rep_map assigns different bio reps per FOV token."""
        d1 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        d2 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {
            "fov_a_ch00.tif": d1,
            "fov_b_ch00.tif": d2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="default",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"fov_a": "FOV_001", "fov_b": "FOV_001"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
                condition_map={"fov_a": "ctrl", "fov_b": "treated"},
                bio_rep_map={"fov_a": "N1", "fov_b": "N2"},
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 2
            fovs_ctrl = store.get_fovs(condition="ctrl", bio_rep="N1")
            fovs_treated = store.get_fovs(condition="treated", bio_rep="N2")
            assert len(fovs_ctrl) == 1
            assert len(fovs_treated) == 1

    def test_skips_unassigned_groups(self, tmp_path):
        """Groups not in condition_map are skipped when condition_map is non-empty."""
        d1 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        d2 = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {
            "assigned_ch00.tif": d1,
            "skipped_ch00.tif": d2,
        })

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=tiff_dir,
                condition="default",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"assigned": "FOV_001"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.65,
                token_config=TokenConfig(),
                condition_map={"assigned": "ctrl"},
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 1
            assert result.skipped == 1


class TestEdgeCases:
    def test_invalid_source_path(self, tmp_path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=Path("/nonexistent"),
                condition="control",
                channel_mappings=[],
                fov_names={},
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
                fov_names={},
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
                fov_names={},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=None,
                token_config=TokenConfig(),
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)
            assert result.elapsed_seconds >= 0


# ---------------------------------------------------------------------------
# Tile Grid Mapping
# ---------------------------------------------------------------------------


class TestBuildTileGrid:
    def test_row_by_row_right_and_down_2x2(self):
        config = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="right_and_down")
        positions = build_tile_grid(config)
        assert positions == [(0, 0), (0, 1), (1, 0), (1, 1)]

    def test_row_by_row_right_and_down_3x3(self):
        config = TileConfig(grid_rows=3, grid_cols=3, grid_type="row_by_row", order="right_and_down")
        positions = build_tile_grid(config)
        assert positions == [
            (0, 0), (0, 1), (0, 2),
            (1, 0), (1, 1), (1, 2),
            (2, 0), (2, 1), (2, 2),
        ]

    def test_row_by_row_left_and_down(self):
        config = TileConfig(grid_rows=2, grid_cols=3, grid_type="row_by_row", order="left_and_down")
        positions = build_tile_grid(config)
        assert positions == [
            (0, 2), (0, 1), (0, 0),
            (1, 2), (1, 1), (1, 0),
        ]

    def test_row_by_row_right_and_up(self):
        config = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="right_and_up")
        positions = build_tile_grid(config)
        assert positions == [(1, 0), (1, 1), (0, 0), (0, 1)]

    def test_snake_by_row_right_and_down_3x3(self):
        config = TileConfig(grid_rows=3, grid_cols=3, grid_type="snake_by_row", order="right_and_down")
        positions = build_tile_grid(config)
        assert positions == [
            (0, 0), (0, 1), (0, 2),
            (1, 2), (1, 1), (1, 0),  # reversed
            (2, 0), (2, 1), (2, 2),
        ]

    def test_column_by_column_right_and_down(self):
        config = TileConfig(grid_rows=3, grid_cols=3, grid_type="column_by_column", order="right_and_down")
        positions = build_tile_grid(config)
        # s0->(0,0), s1->(1,0), s2->(2,0), s3->(0,1), s4->(1,1), ...
        assert positions == [
            (0, 0), (1, 0), (2, 0),
            (0, 1), (1, 1), (2, 1),
            (0, 2), (1, 2), (2, 2),
        ]

    def test_snake_by_column_right_and_down(self):
        config = TileConfig(grid_rows=3, grid_cols=3, grid_type="snake_by_column", order="right_and_down")
        positions = build_tile_grid(config)
        # col 0: top-down, col 1: bottom-up, col 2: top-down
        assert positions == [
            (0, 0), (1, 0), (2, 0),
            (2, 1), (1, 1), (0, 1),  # reversed
            (0, 2), (1, 2), (2, 2),
        ]

    def test_1x1_grid(self):
        config = TileConfig(grid_rows=1, grid_cols=1, grid_type="row_by_row", order="right_and_down")
        positions = build_tile_grid(config)
        assert positions == [(0, 0)]

    def test_all_positions_unique(self):
        """Every grid_type x order combo must produce unique positions."""
        for gt in ("row_by_row", "column_by_column", "snake_by_row", "snake_by_column"):
            for order in ("right_and_down", "left_and_down", "right_and_up", "left_and_up"):
                config = TileConfig(grid_rows=3, grid_cols=4, grid_type=gt, order=order)
                positions = build_tile_grid(config)
                assert len(positions) == 12
                assert len(set(positions)) == 12, f"Duplicate positions for {gt} + {order}"


# ---------------------------------------------------------------------------
# Tile Stitching (unit-level)
# ---------------------------------------------------------------------------


class TestStitchTiles:
    def test_2x2_grid(self):
        """2x2 grid of 32x32 tiles produces 64x64 output."""
        tiles = [
            np.full((32, 32), i, dtype=np.uint16)
            for i in range(4)
        ]
        config = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="right_and_down")
        result = stitch_tiles(tiles, config)

        assert result.shape == (64, 64)
        assert result.dtype == np.uint16
        # Top-left = tile 0 (value 0)
        assert result[0, 0] == 0
        # Top-right = tile 1 (value 1)
        assert result[0, 32] == 1
        # Bottom-left = tile 2 (value 2)
        assert result[32, 0] == 2
        # Bottom-right = tile 3 (value 3)
        assert result[32, 32] == 3

    def test_3x2_snake(self):
        """3 cols x 2 rows snake_by_row layout."""
        tiles = [
            np.full((16, 16), i * 10, dtype=np.uint16)
            for i in range(6)
        ]
        config = TileConfig(grid_rows=2, grid_cols=3, grid_type="snake_by_row", order="right_and_down")
        result = stitch_tiles(tiles, config)

        assert result.shape == (32, 48)
        # Row 0: tiles 0, 1, 2 (left-to-right)
        assert result[0, 0] == 0    # tile 0
        assert result[0, 16] == 10  # tile 1
        assert result[0, 32] == 20  # tile 2
        # Row 1: tiles 3, 4, 5 (right-to-left: 3->(1,2), 4->(1,1), 5->(1,0))
        assert result[16, 32] == 30  # tile 3 at (1,2)
        assert result[16, 16] == 40  # tile 4 at (1,1)
        assert result[16, 0] == 50   # tile 5 at (1,0)

    def test_tile_count_mismatch_raises(self):
        tiles = [np.zeros((32, 32), dtype=np.uint16)] * 3
        config = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="right_and_down")
        with pytest.raises(ValueError, match="Expected 4 tiles"):
            stitch_tiles(tiles, config)

    def test_tile_dimension_mismatch_raises(self):
        tiles = [
            np.zeros((32, 32), dtype=np.uint16),
            np.zeros((32, 32), dtype=np.uint16),
            np.zeros((32, 32), dtype=np.uint16),
            np.zeros((32, 16), dtype=np.uint16),  # wrong width
        ]
        config = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="right_and_down")
        with pytest.raises(ValueError, match="Tile 3 has shape"):
            stitch_tiles(tiles, config)


# ---------------------------------------------------------------------------
# Tile Stitching (engine integration)
# ---------------------------------------------------------------------------


class TestTileStitchImport:
    def test_2x2_tile_stitch_import(self, tmp_path):
        """Import 2x2 tiles for 1 channel → single stitched FOV."""
        d = tmp_path / "tiffs"
        d.mkdir()
        tile_data = []
        for i in range(4):
            data = np.full((32, 32), (i + 1) * 50, dtype=np.uint16)
            tile_data.append(data)
            tifffile.imwrite(str(d / f"FOV1_s{i:02d}_ch00.tif"), data)

        tile_config = TileConfig(
            grid_rows=2, grid_cols=2,
            grid_type="row_by_row", order="right_and_down",
        )

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=d,
                condition="control",
                channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
                fov_names={"FOV1": "FOV_001"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.5,
                token_config=TokenConfig(),
                tile_config=tile_config,
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 1
            assert result.images_written == 1

            fov = store.get_fovs(condition="control")[0]
            assert fov.width == 64
            assert fov.height == 64

            img = store.read_image_numpy(fov.id, "DAPI")
            assert img.shape == (64, 64)
            # Verify tile placement
            assert img[0, 0] == 50    # tile s00 at (0,0)
            assert img[0, 32] == 100  # tile s01 at (0,1)
            assert img[32, 0] == 150  # tile s02 at (1,0)
            assert img[32, 32] == 200 # tile s03 at (1,1)

    def test_multichannel_tile_stitch(self, tmp_path):
        """Each channel is stitched independently with the same grid layout."""
        d = tmp_path / "tiffs"
        d.mkdir()
        for ch in range(2):
            for s in range(4):
                val = (ch + 1) * 100 + (s + 1) * 10
                data = np.full((16, 16), val, dtype=np.uint16)
                tifffile.imwrite(str(d / f"FOV1_s{s:02d}_ch{ch:02d}.tif"), data)

        tile_config = TileConfig(
            grid_rows=2, grid_cols=2,
            grid_type="row_by_row", order="right_and_down",
        )

        with ExperimentStore.create(tmp_path / "test.percell") as store:
            plan = ImportPlan(
                source_path=d,
                condition="control",
                channel_mappings=[
                    ChannelMapping(token_value="00", name="DAPI"),
                    ChannelMapping(token_value="01", name="GFP"),
                ],
                fov_names={"FOV1": "FOV_001"},
                z_transform=ZTransform(method="mip"),
                pixel_size_um=0.5,
                token_config=TokenConfig(),
                tile_config=tile_config,
            )
            engine = ImportEngine()
            result = engine.execute(plan, store)

            assert result.fovs_imported == 1
            assert result.images_written == 2

            fov = store.get_fovs(condition="control")[0]
            dapi = store.read_image_numpy(fov.id, "DAPI")
            gfp = store.read_image_numpy(fov.id, "GFP")
            # ch0: s00=110, s01=120, s02=130, s03=140
            assert dapi[0, 0] == 110
            assert dapi[0, 16] == 120
            # ch1: s00=210, s01=220, s02=230, s03=240
            assert gfp[0, 0] == 210
            assert gfp[0, 16] == 220
