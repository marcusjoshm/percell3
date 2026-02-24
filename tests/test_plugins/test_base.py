"""Tests for AnalysisPlugin ABC, PluginInfo, and PluginResult."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult


class TestPluginInfo:
    """Tests for the PluginInfo dataclass."""

    def test_required_fields(self) -> None:
        info = PluginInfo(name="test", version="1.0.0", description="A test plugin")
        assert info.name == "test"
        assert info.version == "1.0.0"
        assert info.description == "A test plugin"
        assert info.author == ""
        assert info.required_channels is None

    def test_all_fields(self) -> None:
        info = PluginInfo(
            name="test",
            version="2.0.0",
            description="Full",
            author="Tester",
            required_channels=["DAPI", "GFP"],
        )
        assert info.author == "Tester"
        assert info.required_channels == ["DAPI", "GFP"]

    def test_frozen(self) -> None:
        info = PluginInfo(name="test", version="1.0.0", description="Frozen")
        with pytest.raises(AttributeError):
            info.name = "changed"  # type: ignore[misc]


class TestPluginResult:
    """Tests for the PluginResult dataclass."""

    def test_defaults(self) -> None:
        result = PluginResult(measurements_written=10, cells_processed=5)
        assert result.measurements_written == 10
        assert result.cells_processed == 5
        assert result.custom_outputs == {}
        assert result.warnings == []

    def test_with_outputs_and_warnings(self) -> None:
        result = PluginResult(
            measurements_written=100,
            cells_processed=50,
            custom_outputs={"csv": "/path/to/export.csv"},
            warnings=["Skipped 3 particles with zero ring pixels"],
        )
        assert result.custom_outputs == {"csv": "/path/to/export.csv"}
        assert len(result.warnings) == 1

    def test_frozen(self) -> None:
        result = PluginResult(measurements_written=0, cells_processed=0)
        with pytest.raises(AttributeError):
            result.measurements_written = 5  # type: ignore[misc]


class TestAnalysisPluginABC:
    """Tests for the AnalysisPlugin abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            AnalysisPlugin()  # type: ignore[abstract]

    def test_subclass_must_implement_info(self) -> None:
        class Incomplete(AnalysisPlugin):
            def validate(self, store):
                return []

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                return PluginResult(measurements_written=0, cells_processed=0)

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_validate(self) -> None:
        class Incomplete(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="t", version="1", description="t")

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                return PluginResult(measurements_written=0, cells_processed=0)

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_run(self) -> None:
        class Incomplete(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="t", version="1", description="t")

            def validate(self, store):
                return []

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_complete_subclass_works(self) -> None:
        class Complete(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="complete", version="1.0.0", description="Complete plugin")

            def validate(self, store):
                return []

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                return PluginResult(measurements_written=0, cells_processed=0)

        plugin = Complete()
        assert plugin.info().name == "complete"
        assert plugin.validate(MagicMock()) == []
        assert plugin.get_parameter_schema() == {}

    def test_get_parameter_schema_default_empty(self) -> None:
        class Minimal(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="m", version="1", description="m")

            def validate(self, store):
                return []

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                return PluginResult(measurements_written=0, cells_processed=0)

        assert Minimal().get_parameter_schema() == {}

    def test_get_parameter_schema_override(self) -> None:
        class WithSchema(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="s", version="1", description="s")

            def validate(self, store):
                return []

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                return PluginResult(measurements_written=0, cells_processed=0)

            def get_parameter_schema(self):
                return {"type": "object", "properties": {"channel": {"type": "string"}}}

        schema = WithSchema().get_parameter_schema()
        assert schema["type"] == "object"
        assert "channel" in schema["properties"]
