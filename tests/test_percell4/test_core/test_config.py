"""Tests for percell4.core.config — TOML config loader with Pydantic v2."""

from __future__ import annotations

from pathlib import Path

import pytest

from percell4.core.config import (
    ChannelSpec,
    ExperimentConfigV1,
    ExperimentMeta,
    RoiTypeConfig,
)
from percell4.core.exceptions import ExperimentError

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, content: str) -> Path:
    """Write TOML content to a temporary file and return its path."""
    p = tmp_path / "experiment.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Valid TOML parsing
# ---------------------------------------------------------------------------


class TestValidParsing:
    """Test successful parsing of valid TOML configs."""

    def test_parse_sample_experiment(self) -> None:
        path = FIXTURES_DIR / "sample_experiment.toml"
        config = ExperimentConfigV1.from_toml(path)

        assert config.experiment.name == "Test Experiment"
        assert config.experiment.description == ""
        assert len(config.channels) == 2
        assert config.channels[0].name == "DAPI"
        assert config.channels[0].role == "nuclear"
        assert config.channels[0].display_order == 0
        assert config.channels[1].name == "GFP"
        assert config.channels[1].role == "signal"
        assert config.channels[1].display_order == 1

    def test_roi_types_from_sample(self) -> None:
        path = FIXTURES_DIR / "sample_experiment.toml"
        config = ExperimentConfigV1.from_toml(path)

        assert len(config.roi_types) == 2
        assert config.roi_types[0].name == "cell"
        assert config.roi_types[0].parent_type is None
        assert config.roi_types[1].name == "particle"
        assert config.roi_types[1].parent_type == "cell"

    def test_op_configs_from_sample(self) -> None:
        path = FIXTURES_DIR / "sample_experiment.toml"
        config = ExperimentConfigV1.from_toml(path)

        assert "cellpose" in config.op_configs
        assert config.op_configs["cellpose"]["model_name"] == "cyto3"
        assert config.op_configs["cellpose"]["diameter"] == 30

    def test_experiment_description(self, tmp_path: Path) -> None:
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "With Description"
description = "A detailed description"

[[channels]]
name = "DAPI"
""",
        )
        config = ExperimentConfigV1.from_toml(path)
        assert config.experiment.description == "A detailed description"


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestDefaults:
    """Test default values for optional fields."""

    def test_default_roi_types(self, tmp_path: Path) -> None:
        """When no [[roi_types]] section, defaults to just 'cell'."""
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "Minimal"

[[channels]]
name = "DAPI"
""",
        )
        config = ExperimentConfigV1.from_toml(path)

        assert len(config.roi_types) == 1
        assert config.roi_types[0].name == "cell"
        assert config.roi_types[0].parent_type is None

    def test_empty_op_configs(self, tmp_path: Path) -> None:
        """When no [op_configs] section, defaults to empty dict."""
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "No OpConfigs"

[[channels]]
name = "DAPI"
""",
        )
        config = ExperimentConfigV1.from_toml(path)
        assert config.op_configs == {}

    def test_channel_defaults(self, tmp_path: Path) -> None:
        """Channel optional fields default correctly."""
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "Minimal Channel"

[[channels]]
name = "DAPI"
""",
        )
        config = ExperimentConfigV1.from_toml(path)
        ch = config.channels[0]
        assert ch.role is None
        assert ch.color is None
        assert ch.display_order == 0


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


class TestMissingRequired:
    """Test that missing required fields raise validation errors."""

    def test_missing_experiment_name(self, tmp_path: Path) -> None:
        path = _write_toml(
            tmp_path,
            """\
[experiment]
description = "No name"

[[channels]]
name = "DAPI"
""",
        )
        with pytest.raises(Exception):  # Pydantic ValidationError
            ExperimentConfigV1.from_toml(path)

    def test_missing_experiment_section(self, tmp_path: Path) -> None:
        path = _write_toml(
            tmp_path,
            """\
[[channels]]
name = "DAPI"
""",
        )
        with pytest.raises(Exception):  # Pydantic ValidationError
            ExperimentConfigV1.from_toml(path)

    def test_missing_channel_name(self, tmp_path: Path) -> None:
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "Bad Channel"

[[channels]]
role = "nuclear"
""",
        )
        with pytest.raises(Exception):  # Pydantic ValidationError
            ExperimentConfigV1.from_toml(path)


# ---------------------------------------------------------------------------
# [[pipelines]] rejection
# ---------------------------------------------------------------------------


class TestPipelinesRejection:
    """Test that [[pipelines]] section is rejected with a clear error."""

    def test_pipelines_raises_experiment_error(self, tmp_path: Path) -> None:
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "With Pipelines"

[[channels]]
name = "DAPI"

[[pipelines]]
name = "bad"
""",
        )
        with pytest.raises(ExperimentError, match=r"\[\[pipelines\]\].*not supported"):
            ExperimentConfigV1.from_toml(path)


# ---------------------------------------------------------------------------
# ROI type hierarchy validation
# ---------------------------------------------------------------------------


class TestRoiTypeHierarchy:
    """Test ROI type hierarchy validation."""

    def test_invalid_parent_type_reference(self, tmp_path: Path) -> None:
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "Bad Parent"

[[channels]]
name = "DAPI"

[[roi_types]]
name = "cell"

[[roi_types]]
name = "particle"
parent_type = "nonexistent"
""",
        )
        with pytest.raises(
            ExperimentError, match="references unknown parent_type 'nonexistent'"
        ):
            ExperimentConfigV1.from_toml(path)

    def test_circular_parent_type_ab(self, tmp_path: Path) -> None:
        """A -> B -> A cycle should be detected."""
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "Circular"

[[channels]]
name = "DAPI"

[[roi_types]]
name = "A"
parent_type = "B"

[[roi_types]]
name = "B"
parent_type = "A"
""",
        )
        with pytest.raises(
            ExperimentError, match="Circular parent_type reference"
        ):
            ExperimentConfigV1.from_toml(path)

    def test_circular_self_reference(self, tmp_path: Path) -> None:
        """A -> A self-reference should be detected."""
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "Self Ref"

[[channels]]
name = "DAPI"

[[roi_types]]
name = "A"
parent_type = "A"
""",
        )
        with pytest.raises(
            ExperimentError, match="Circular parent_type reference"
        ):
            ExperimentConfigV1.from_toml(path)

    def test_valid_deep_hierarchy(self, tmp_path: Path) -> None:
        """A valid 3-level hierarchy should parse without error."""
        path = _write_toml(
            tmp_path,
            """\
[experiment]
name = "Deep"

[[channels]]
name = "DAPI"

[[roi_types]]
name = "cell"

[[roi_types]]
name = "organelle"
parent_type = "cell"

[[roi_types]]
name = "granule"
parent_type = "organelle"
""",
        )
        config = ExperimentConfigV1.from_toml(path)
        assert len(config.roi_types) == 3


# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------


class TestSizeLimits:
    """Test enforcement of count and size limits."""

    def test_too_many_channels(self, tmp_path: Path) -> None:
        """More than 100 channels should fail validation."""
        channel_lines = "\n".join(
            f'[[channels]]\nname = "ch{i}"' for i in range(101)
        )
        path = _write_toml(
            tmp_path,
            f"""\
[experiment]
name = "Too Many Channels"

{channel_lines}
""",
        )
        with pytest.raises(Exception):  # Pydantic ValidationError (max_length)
            ExperimentConfigV1.from_toml(path)

    def test_exactly_100_channels_ok(self, tmp_path: Path) -> None:
        """Exactly 100 channels should succeed."""
        channel_lines = "\n".join(
            f'[[channels]]\nname = "ch{i}"' for i in range(100)
        )
        path = _write_toml(
            tmp_path,
            f"""\
[experiment]
name = "Max Channels"

{channel_lines}
""",
        )
        config = ExperimentConfigV1.from_toml(path)
        assert len(config.channels) == 100

    def test_too_many_roi_types(self, tmp_path: Path) -> None:
        """More than 50 roi_types should fail."""
        roi_lines = "\n".join(
            f'[[roi_types]]\nname = "type{i}"' for i in range(51)
        )
        path = _write_toml(
            tmp_path,
            f"""\
[experiment]
name = "Too Many ROI Types"

[[channels]]
name = "DAPI"

{roi_lines}
""",
        )
        with pytest.raises(ExperimentError, match="Too many roi_types"):
            ExperimentConfigV1.from_toml(path)

    def test_exactly_50_roi_types_ok(self, tmp_path: Path) -> None:
        """Exactly 50 roi_types should succeed."""
        roi_lines = "\n".join(
            f'[[roi_types]]\nname = "type{i}"' for i in range(50)
        )
        path = _write_toml(
            tmp_path,
            f"""\
[experiment]
name = "Max ROI Types"

[[channels]]
name = "DAPI"

{roi_lines}
""",
        )
        config = ExperimentConfigV1.from_toml(path)
        assert len(config.roi_types) == 50

    def test_op_configs_too_large(self, tmp_path: Path) -> None:
        """op_configs exceeding 100KB should fail."""
        # Generate a large value string (> 100KB)
        big_value = "x" * 100_001
        path = _write_toml(
            tmp_path,
            f"""\
[experiment]
name = "Big OpConfigs"

[[channels]]
name = "DAPI"

[op_configs.big]
data = "{big_value}"
""",
        )
        with pytest.raises(ExperimentError, match="op_configs too large"):
            ExperimentConfigV1.from_toml(path)


# ---------------------------------------------------------------------------
# Model classes are importable
# ---------------------------------------------------------------------------


class TestModelsImportable:
    """Verify that all config model classes are importable."""

    def test_experiment_meta(self) -> None:
        meta = ExperimentMeta(name="test")
        assert meta.name == "test"
        assert meta.description == ""

    def test_channel_spec(self) -> None:
        ch = ChannelSpec(name="DAPI")
        assert ch.name == "DAPI"
        assert ch.role is None
        assert ch.color is None
        assert ch.display_order == 0

    def test_roi_type_config(self) -> None:
        rt = RoiTypeConfig(name="cell")
        assert rt.name == "cell"
        assert rt.parent_type is None
