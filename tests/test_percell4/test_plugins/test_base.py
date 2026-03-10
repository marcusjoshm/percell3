"""Tests for plugin ABCs and PluginResult dataclass."""

from __future__ import annotations

import pytest

from percell4.plugins.base import AnalysisPlugin, PluginResult, VisualizationPlugin


# ---------------------------------------------------------------------------
# PluginResult
# ---------------------------------------------------------------------------


def test_plugin_result_creation() -> None:
    """PluginResult with explicit values."""
    result = PluginResult(
        fovs_processed=3,
        rois_processed=10,
        measurements_added=50,
        derived_fovs_created=2,
        errors=["something went wrong"],
    )
    assert result.fovs_processed == 3
    assert result.rois_processed == 10
    assert result.measurements_added == 50
    assert result.derived_fovs_created == 2
    assert result.errors == ["something went wrong"]


def test_plugin_result_defaults() -> None:
    """PluginResult with all defaults."""
    result = PluginResult()
    assert result.fovs_processed == 0
    assert result.rois_processed == 0
    assert result.measurements_added == 0
    assert result.derived_fovs_created == 0
    assert result.errors == []


def test_plugin_result_frozen() -> None:
    """PluginResult is immutable."""
    result = PluginResult()
    with pytest.raises(AttributeError):
        result.fovs_processed = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


def test_analysis_plugin_abc_enforcement() -> None:
    """Cannot instantiate AnalysisPlugin without implementing run()."""
    with pytest.raises(TypeError, match="run"):
        AnalysisPlugin()  # type: ignore[abstract]


def test_visualization_plugin_abc_enforcement() -> None:
    """Cannot instantiate VisualizationPlugin without implementing launch()."""
    with pytest.raises(TypeError, match="launch"):
        VisualizationPlugin()  # type: ignore[abstract]


def test_analysis_plugin_concrete_subclass() -> None:
    """A concrete subclass with run() can be instantiated."""

    class ConcretePlugin(AnalysisPlugin):
        name = "test"
        description = "test plugin"

        def run(self, store, fov_ids, roi_ids=None, on_progress=None, **kwargs):
            return PluginResult()

    plugin = ConcretePlugin()
    assert plugin.name == "test"
    assert plugin.description == "test plugin"


def test_visualization_plugin_concrete_subclass() -> None:
    """A concrete subclass with launch() can be instantiated."""

    class ConcreteViz(VisualizationPlugin):
        name = "test_viz"
        description = "test viz plugin"

        def launch(self, store, fov_id, **kwargs):
            pass

    plugin = ConcreteViz()
    assert plugin.name == "test_viz"
