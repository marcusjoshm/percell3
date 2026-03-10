"""Tests for PluginRegistry — auto-discovery and plugin access."""

from __future__ import annotations

import pytest

from percell4.plugins.registry import PluginError, PluginRegistry


def test_discover_finds_plugins() -> None:
    """Registry discovers at least the built-in plugins on init."""
    registry = PluginRegistry()
    plugins = registry.list_plugins()
    names = {p["name"] for p in plugins}
    # At minimum, these should be discovered
    assert "nan_zero" in names
    assert "image_calculator" in names
    assert "surface_plot_3d" in names


def test_get_plugin_by_name() -> None:
    """Can retrieve a known plugin by name."""
    registry = PluginRegistry()
    plugin = registry.get_plugin("nan_zero")
    assert plugin.name == "nan_zero"


def test_list_plugins_returns_info() -> None:
    """list_plugins returns dicts with name, description, type."""
    registry = PluginRegistry()
    plugins = registry.list_plugins()
    assert len(plugins) > 0

    for p in plugins:
        assert "name" in p
        assert "description" in p
        assert "type" in p
        assert p["type"] in ("analysis", "visualization")


def test_get_unknown_raises() -> None:
    """Requesting unknown plugin raises PluginError."""
    registry = PluginRegistry()
    with pytest.raises(PluginError, match="not found"):
        registry.get_plugin("nonexistent_plugin_xyz")


def test_get_visualization_plugin() -> None:
    """Can retrieve a visualization plugin by name."""
    registry = PluginRegistry()
    plugin = registry.get_plugin("surface_plot_3d")
    assert plugin.name == "surface_plot_3d"


def test_all_expected_plugins_present() -> None:
    """All 7 built-in plugins are discovered."""
    registry = PluginRegistry()
    plugins = registry.list_plugins()
    names = {p["name"] for p in plugins}

    expected = {
        "nan_zero",
        "image_calculator",
        "threshold_bg_subtraction",
        "local_bg_subtraction",
        "split_halo_condensate_analysis",
        "condensate_partitioning_ratio",
        "surface_plot_3d",
    }
    assert expected <= names, f"Missing plugins: {expected - names}"
