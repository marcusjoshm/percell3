"""Tests for percell3.io.serialization — YAML round-trip for ImportPlan."""

from pathlib import Path

import pytest

from percell3.io.models import (
    ChannelMapping,
    ImportPlan,
    TokenConfig,
    ZTransform,
)


def _make_plan(source_path: Path) -> ImportPlan:
    """Create a fully populated ImportPlan for testing."""
    return ImportPlan(
        source_path=source_path,
        condition="control",
        channel_mappings=[
            ChannelMapping(token_value="00", name="DAPI", role="nucleus", color="#0000FF"),
            ChannelMapping(token_value="01", name="GFP"),
        ],
        region_names={"region1": "Well_A1", "region2": "Well_A2"},
        z_transform=ZTransform(method="mip"),
        pixel_size_um=0.65,
        token_config=TokenConfig(
            channel=r"_ch(\d+)",
            timepoint=r"_t(\d+)",
            z_slice=r"_z(\d+)",
            region=r"^([a-z]+\d+)",
        ),
    )


class TestRoundTrip:
    def test_full_plan_round_trips(self, tmp_path):
        plan = _make_plan(tmp_path / "tiffs")
        yaml_path = tmp_path / "plan.yaml"

        plan.to_yaml(yaml_path)
        loaded = ImportPlan.from_yaml(yaml_path)

        assert loaded.source_path == plan.source_path
        assert loaded.condition == plan.condition
        assert loaded.pixel_size_um == plan.pixel_size_um
        assert loaded.z_transform == plan.z_transform
        assert loaded.token_config == plan.token_config
        assert loaded.region_names == plan.region_names
        assert len(loaded.channel_mappings) == 2
        assert loaded.channel_mappings[0].name == "DAPI"
        assert loaded.channel_mappings[0].role == "nucleus"
        assert loaded.channel_mappings[0].color == "#0000FF"
        assert loaded.channel_mappings[1].name == "GFP"
        assert loaded.channel_mappings[1].role is None

    def test_z_transform_with_slice_index(self, tmp_path):
        plan = ImportPlan(
            source_path=tmp_path / "tiffs",
            condition="treated",
            channel_mappings=[],
            region_names={},
            z_transform=ZTransform(method="slice", slice_index=3),
            pixel_size_um=None,
            token_config=TokenConfig(),
        )
        yaml_path = tmp_path / "plan.yaml"

        plan.to_yaml(yaml_path)
        loaded = ImportPlan.from_yaml(yaml_path)

        assert loaded.z_transform.method == "slice"
        assert loaded.z_transform.slice_index == 3

    def test_missing_optional_fields_get_defaults(self, tmp_path):
        """A YAML with only required fields should load with defaults."""
        yaml_path = tmp_path / "plan.yaml"
        yaml_path.write_text(
            "source_path: /some/path\n"
            "condition: control\n"
            "z_transform:\n"
            "  method: mip\n"
            "token_config:\n"
            "  channel: '_ch(\\d+)'\n"
        )

        loaded = ImportPlan.from_yaml(yaml_path)
        assert loaded.source_path == Path("/some/path")
        assert loaded.condition == "control"
        assert loaded.pixel_size_um is None
        assert loaded.channel_mappings == []
        assert loaded.region_names == {}
        assert loaded.z_transform.slice_index is None


class TestConditionMapSerialization:
    def test_condition_map_round_trips(self, tmp_path):
        plan = ImportPlan(
            source_path=tmp_path / "tiffs",
            condition="default",
            channel_mappings=[],
            region_names={"ctrl_s00": "s00", "treated_s00": "s00"},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(),
            condition_map={"ctrl_s00": "ctrl", "treated_s00": "treated"},
        )
        yaml_path = tmp_path / "plan.yaml"

        plan.to_yaml(yaml_path)
        loaded = ImportPlan.from_yaml(yaml_path)

        assert loaded.condition_map == {"ctrl_s00": "ctrl", "treated_s00": "treated"}

    def test_empty_condition_map_not_written(self, tmp_path):
        plan = ImportPlan(
            source_path=tmp_path / "tiffs",
            condition="control",
            channel_mappings=[],
            region_names={},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(),
            condition_map={},
        )
        yaml_path = tmp_path / "plan.yaml"

        plan.to_yaml(yaml_path)
        loaded = ImportPlan.from_yaml(yaml_path)

        assert loaded.condition_map == {}

    def test_old_yaml_without_condition_map_loads(self, tmp_path):
        """YAML files from before condition_map was added still load."""
        yaml_path = tmp_path / "plan.yaml"
        yaml_path.write_text(
            "source_path: /some/path\n"
            "condition: control\n"
            "z_transform:\n"
            "  method: mip\n"
            "token_config:\n"
            "  channel: '_ch(\\d+)'\n"
        )

        loaded = ImportPlan.from_yaml(yaml_path)
        assert loaded.condition_map == {}


class TestErrorHandling:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ImportPlan.from_yaml(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text("[not: a: valid: yaml: {{{")
        with pytest.raises(Exception):
            ImportPlan.from_yaml(yaml_path)

    def test_missing_required_key_raises(self, tmp_path):
        yaml_path = tmp_path / "incomplete.yaml"
        yaml_path.write_text("source_path: /some/path\n")
        with pytest.raises(ValueError, match="missing required key"):
            ImportPlan.from_yaml(yaml_path)


class TestTokenConfigSerialization:
    def test_custom_region_pattern_preserved(self, tmp_path):
        plan = ImportPlan(
            source_path=tmp_path / "tiffs",
            condition="ctrl",
            channel_mappings=[],
            region_names={},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(region=r"^(well_[A-Z]\d+)"),
        )
        yaml_path = tmp_path / "plan.yaml"

        plan.to_yaml(yaml_path)
        loaded = ImportPlan.from_yaml(yaml_path)

        assert loaded.token_config.region == r"^(well_[A-Z]\d+)"

    def test_default_token_config_without_region(self, tmp_path):
        plan = ImportPlan(
            source_path=tmp_path / "tiffs",
            condition="ctrl",
            channel_mappings=[],
            region_names={},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(),  # region=None by default
        )
        yaml_path = tmp_path / "plan.yaml"

        plan.to_yaml(yaml_path)
        loaded = ImportPlan.from_yaml(yaml_path)

        assert loaded.token_config.region is None
