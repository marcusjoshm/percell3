"""Tests for SurfacePlot3DPlugin — info, validate, and registry discovery."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from percell3.plugins.base import PluginInfo, VisualizationPlugin
from percell3.plugins.builtin.surface_plot_3d import SurfacePlot3DPlugin
from percell3.plugins.registry import PluginError, PluginRegistry


class TestVisualizationPluginABC:
    """Tests for the VisualizationPlugin abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            VisualizationPlugin()  # type: ignore[abstract]

    def test_subclass_must_implement_info(self) -> None:
        class Incomplete(VisualizationPlugin):
            def validate(self, store):
                return []

            def launch(self, store, fov_id, parameters=None):
                pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_validate(self) -> None:
        class Incomplete(VisualizationPlugin):
            def info(self):
                return PluginInfo(name="t", version="1", description="t")

            def launch(self, store, fov_id, parameters=None):
                pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_launch(self) -> None:
        class Incomplete(VisualizationPlugin):
            def info(self):
                return PluginInfo(name="t", version="1", description="t")

            def validate(self, store):
                return []

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_complete_subclass_works(self) -> None:
        class Complete(VisualizationPlugin):
            def info(self):
                return PluginInfo(name="viz_test", version="1.0.0", description="Test viz")

            def validate(self, store):
                return []

            def launch(self, store, fov_id, parameters=None):
                pass

        plugin = Complete()
        assert plugin.info().name == "viz_test"
        assert plugin.validate(MagicMock()) == []
        assert plugin.get_parameter_schema() == {}


class TestSurfacePlot3DPlugin:
    """Tests for the concrete SurfacePlot3DPlugin."""

    def test_info(self) -> None:
        plugin = SurfacePlot3DPlugin()
        info = plugin.info()
        assert info.name == "surface_plot_3d"
        assert info.version == "1.0.0"
        assert "surface" in info.description.lower()

    def test_validate_needs_two_channels(self) -> None:
        """validate() returns error with < 2 channels."""
        store = MagicMock()
        store.get_channels.return_value = [MagicMock()]  # Only 1 channel
        store.get_fovs.return_value = [MagicMock()]

        plugin = SurfacePlot3DPlugin()
        errors = plugin.validate(store)

        assert len(errors) == 1
        assert "2 channels" in errors[0]

    def test_validate_needs_fovs(self) -> None:
        """validate() returns error with 0 FOVs."""
        store = MagicMock()
        store.get_channels.return_value = [MagicMock(), MagicMock()]
        store.get_fovs.return_value = []

        plugin = SurfacePlot3DPlugin()
        errors = plugin.validate(store)

        assert len(errors) == 1
        assert "FOV" in errors[0]

    def test_validate_needs_both(self) -> None:
        """validate() returns two errors when both fail."""
        store = MagicMock()
        store.get_channels.return_value = [MagicMock()]  # Only 1
        store.get_fovs.return_value = []

        plugin = SurfacePlot3DPlugin()
        errors = plugin.validate(store)

        assert len(errors) == 2

    def test_validate_passes(self) -> None:
        """validate() returns [] with 2+ channels and FOVs."""
        store = MagicMock()
        store.get_channels.return_value = [MagicMock(), MagicMock()]
        store.get_fovs.return_value = [MagicMock()]

        plugin = SurfacePlot3DPlugin()
        errors = plugin.validate(store)

        assert errors == []


class TestRegistryDiscoversVizPlugin:
    """Tests for PluginRegistry discovering visualization plugins."""

    def test_discover_finds_surface_plot_3d(self) -> None:
        """PluginRegistry.discover() finds surface_plot_3d in viz plugins."""
        registry = PluginRegistry()
        registry.discover()

        viz_plugins = registry.list_viz_plugins()
        names = {p.name for p in viz_plugins}
        assert "surface_plot_3d" in names

    def test_viz_plugin_not_in_analysis_list(self) -> None:
        """Viz plugins should not appear in the analysis plugins list."""
        registry = PluginRegistry()
        registry.discover()

        analysis_names = {p.name for p in registry.list_plugins()}
        assert "surface_plot_3d" not in analysis_names

    def test_get_viz_plugin(self) -> None:
        """get_viz_plugin returns a VisualizationPlugin instance."""
        registry = PluginRegistry()
        registry.discover()

        plugin = registry.get_viz_plugin("surface_plot_3d")
        assert isinstance(plugin, VisualizationPlugin)
        assert plugin.info().name == "surface_plot_3d"

    def test_get_viz_plugin_not_found(self) -> None:
        """get_viz_plugin raises PluginError for unknown names."""
        registry = PluginRegistry()
        with pytest.raises(PluginError, match="not found"):
            registry.get_viz_plugin("nonexistent")

    def test_discovery_skips_viz_abc(self) -> None:
        """VisualizationPlugin base class should not be registered."""
        registry = PluginRegistry()
        registry.discover()

        for info in registry.list_viz_plugins():
            assert info.name != "VisualizationPlugin"
