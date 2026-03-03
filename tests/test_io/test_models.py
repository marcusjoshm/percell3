"""Tests for percell3.io.models."""

from pathlib import Path

from percell3.io.models import (
    ChannelMapping,
    DiscoveredFile,
    ImportPlan,
    ImportResult,
    ScanResult,
    TileConfig,
    TokenConfig,
    ZTransform,
)


class TestTokenConfig:
    def test_defaults(self):
        tc = TokenConfig()
        assert tc.channel == r"_ch(\d+)"
        assert tc.timepoint == r"_t(\d+)"
        assert tc.z_slice == r"_z(\d+)"
        assert tc.fov is None
        assert tc.series == r"_s(\d+)"

    def test_series_disabled(self):
        tc = TokenConfig(series=None)
        assert tc.series is None

    def test_custom_series_pattern(self):
        tc = TokenConfig(series=r"_tile(\d+)")
        assert tc.series == r"_tile(\d+)"

    def test_invalid_series_regex_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid regex"):
            TokenConfig(series=r"_s([\d+")

    def test_custom_patterns(self):
        tc = TokenConfig(channel=r"_C(\d+)", fov=r"_r(\d+)")
        assert tc.channel == r"_C(\d+)"
        assert tc.fov == r"_r(\d+)"

    def test_frozen(self):
        tc = TokenConfig()
        import pytest

        with pytest.raises(AttributeError):
            tc.channel = "new"  # type: ignore[misc]

    def test_invalid_regex_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid regex"):
            TokenConfig(channel=r"_ch([\d+")

    def test_excessively_long_pattern_raises(self):
        import pytest

        with pytest.raises(ValueError, match="exceeds max length"):
            TokenConfig(channel="a" * 201)

    def test_none_fov_skips_validation(self):
        tc = TokenConfig(fov=None)
        assert tc.fov is None


class TestTileConfig:
    def test_construction(self):
        tc = TileConfig(
            grid_rows=3, grid_cols=4,
            grid_type="row_by_row", order="right_and_down",
        )
        assert tc.grid_rows == 3
        assert tc.grid_cols == 4
        assert tc.total_tiles == 12

    def test_all_valid_grid_types(self):
        for gt in ("row_by_row", "column_by_column", "snake_by_row", "snake_by_column"):
            tc = TileConfig(grid_rows=2, grid_cols=2, grid_type=gt, order="right_and_down")
            assert tc.grid_type == gt

    def test_all_valid_orders(self):
        for order in ("right_and_down", "left_and_down", "right_and_up", "left_and_up"):
            tc = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order=order)
            assert tc.order == order

    def test_invalid_grid_type_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid grid_type"):
            TileConfig(grid_rows=2, grid_cols=2, grid_type="zigzag", order="right_and_down")

    def test_invalid_order_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid tile order"):
            TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="diagonal")

    def test_zero_rows_raises(self):
        import pytest

        with pytest.raises(ValueError, match="grid_rows must be >= 1"):
            TileConfig(grid_rows=0, grid_cols=2, grid_type="row_by_row", order="right_and_down")

    def test_zero_cols_raises(self):
        import pytest

        with pytest.raises(ValueError, match="grid_cols must be >= 1"):
            TileConfig(grid_rows=2, grid_cols=0, grid_type="row_by_row", order="right_and_down")

    def test_frozen(self):
        import pytest

        tc = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="right_and_down")
        with pytest.raises(AttributeError):
            tc.grid_rows = 3  # type: ignore[misc]


class TestDiscoveredFile:
    def test_construction(self):
        df = DiscoveredFile(
            path=Path("/tmp/img_ch00.tif"),
            tokens={"channel": "00"},
            shape=(256, 256),
            dtype="uint16",
            pixel_size_um=0.65,
        )
        assert df.dtype == "uint16"
        assert df.shape == (256, 256)


class TestScanResult:
    def test_construction(self):
        sr = ScanResult(
            source_path=Path("/tmp"),
            files=[],
            channels=["00", "01"],
            fovs=["r1"],
            timepoints=[],
            z_slices=[],
            pixel_size_um=0.65,
            warnings=[],
        )
        assert sr.channels == ["00", "01"]
        assert sr.fovs == ["r1"]
        assert sr.tiles == []

    def test_with_tiles(self):
        sr = ScanResult(
            source_path=Path("/tmp"),
            files=[],
            channels=[],
            fovs=[],
            timepoints=[],
            z_slices=[],
            pixel_size_um=None,
            warnings=[],
            tiles=["00", "01", "02", "03"],
        )
        assert sr.tiles == ["00", "01", "02", "03"]


class TestChannelMapping:
    def test_construction(self):
        cm = ChannelMapping(token_value="00", name="DAPI", color="#0000FF")
        assert cm.token_value == "00"
        assert cm.name == "DAPI"

    def test_optional_fields(self):
        cm = ChannelMapping(token_value="01", name="GFP")
        assert cm.role is None
        assert cm.color is None


class TestZTransform:
    def test_mip(self):
        zt = ZTransform(method="mip")
        assert zt.method == "mip"
        assert zt.slice_index is None

    def test_slice(self):
        zt = ZTransform(method="slice", slice_index=5)
        assert zt.slice_index == 5

    def test_all_valid_methods(self):
        import pytest

        for method in ("mip", "sum", "mean", "keep"):
            zt = ZTransform(method=method)
            assert zt.method == method
        zt = ZTransform(method="slice", slice_index=0)
        assert zt.method == "slice"

    def test_invalid_method_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid Z-transform method"):
            ZTransform(method="invalid")

    def test_slice_without_index_raises(self):
        import pytest

        with pytest.raises(ValueError, match="slice_index is required"):
            ZTransform(method="slice")


class TestImportPlan:
    def test_construction(self):
        plan = ImportPlan(
            source_path=Path("/tmp/data"),
            condition="control",
            channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
            fov_names={"r1": "FOV_1"},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=0.65,
            token_config=TokenConfig(),
        )
        assert plan.condition == "control"
        assert len(plan.channel_mappings) == 1

    def test_mutable(self):
        """ImportPlan is mutable (not frozen) for user editing."""
        plan = ImportPlan(
            source_path=Path("/tmp"),
            condition="ctrl",
            channel_mappings=[],
            fov_names={},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(),
        )
        plan.condition = "treated"
        assert plan.condition == "treated"

    def test_tile_config_default_none(self):
        plan = ImportPlan(
            source_path=Path("/tmp"),
            condition="ctrl",
            channel_mappings=[],
            fov_names={},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(),
        )
        assert plan.tile_config is None

    def test_tile_config_set(self):
        tc = TileConfig(grid_rows=2, grid_cols=3, grid_type="row_by_row", order="right_and_down")
        plan = ImportPlan(
            source_path=Path("/tmp"),
            condition="ctrl",
            channel_mappings=[],
            fov_names={},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(),
            tile_config=tc,
        )
        assert plan.tile_config is not None
        assert plan.tile_config.total_tiles == 6


class TestImportResult:
    def test_construction(self):
        ir = ImportResult(
            fovs_imported=3,
            channels_registered=2,
            images_written=6,
            skipped=0,
        )
        assert ir.fovs_imported == 3
        assert ir.warnings == []
        assert ir.elapsed_seconds == 0.0
