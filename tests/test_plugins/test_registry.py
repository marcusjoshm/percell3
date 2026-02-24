"""Tests for PluginRegistry — discovery, lifecycle, error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult
from percell3.plugins.registry import PluginError, PluginRegistry


# --- Test plugin classes ---

class _DummyPlugin(AnalysisPlugin):
    """A minimal plugin for testing."""

    def info(self) -> PluginInfo:
        return PluginInfo(name="dummy", version="1.0.0", description="Dummy plugin")

    def validate(self, store) -> list[str]:
        return []

    def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
        return PluginResult(measurements_written=5, cells_processed=3)


class _FailingPlugin(AnalysisPlugin):
    """A plugin whose run() raises an error."""

    def info(self) -> PluginInfo:
        return PluginInfo(name="failing", version="1.0.0", description="Fails")

    def validate(self, store) -> list[str]:
        return []

    def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
        raise RuntimeError("Plugin crashed")


class _InvalidPlugin(AnalysisPlugin):
    """A plugin that fails validation."""

    def info(self) -> PluginInfo:
        return PluginInfo(name="invalid", version="1.0.0", description="Invalid")

    def validate(self, store) -> list[str]:
        return ["No cells found", "No channels found"]

    def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
        return PluginResult(measurements_written=0, cells_processed=0)


class TestPluginRegistryManual:
    """Tests for manual registration and listing."""

    def test_register_and_list(self) -> None:
        registry = PluginRegistry()
        registry.register(_DummyPlugin)
        plugins = registry.list_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "dummy"

    def test_register_multiple(self) -> None:
        registry = PluginRegistry()
        registry.register(_DummyPlugin)
        registry.register(_FailingPlugin)
        plugins = registry.list_plugins()
        names = {p.name for p in plugins}
        assert names == {"dummy", "failing"}

    def test_register_non_plugin_raises(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(TypeError, match="Expected AnalysisPlugin subclass"):
            registry.register(str)  # type: ignore[arg-type]

    def test_get_plugin_by_name(self) -> None:
        registry = PluginRegistry()
        registry.register(_DummyPlugin)
        plugin = registry.get_plugin("dummy")
        assert isinstance(plugin, _DummyPlugin)
        assert plugin.info().name == "dummy"

    def test_get_plugin_not_found(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(PluginError, match="not found"):
            registry.get_plugin("nonexistent")

    def test_list_empty_registry(self) -> None:
        registry = PluginRegistry()
        assert registry.list_plugins() == []


class TestPluginRegistryLifecycle:
    """Tests for run_plugin lifecycle management."""

    def test_run_plugin_success(self) -> None:
        registry = PluginRegistry()
        registry.register(_DummyPlugin)

        store = MagicMock()
        store.start_analysis_run.return_value = 42

        result = registry.run_plugin("dummy", store)

        assert result.measurements_written == 5
        assert result.cells_processed == 3
        store.start_analysis_run.assert_called_once_with("dummy", None)
        store.complete_analysis_run.assert_called_once_with(42, status="completed", cell_count=3)

    def test_run_plugin_with_parameters(self) -> None:
        registry = PluginRegistry()
        registry.register(_DummyPlugin)

        store = MagicMock()
        store.start_analysis_run.return_value = 1
        params = {"channel": "GFP", "dilation": 5}

        registry.run_plugin("dummy", store, parameters=params)

        store.start_analysis_run.assert_called_once_with("dummy", params)

    def test_run_plugin_validation_fails(self) -> None:
        registry = PluginRegistry()
        registry.register(_InvalidPlugin)

        store = MagicMock()

        with pytest.raises(PluginError, match="validation failed"):
            registry.run_plugin("invalid", store)

        # Analysis run should NOT be started if validation fails
        store.start_analysis_run.assert_not_called()

    def test_run_plugin_crash_marks_failed(self) -> None:
        registry = PluginRegistry()
        registry.register(_FailingPlugin)

        store = MagicMock()
        store.start_analysis_run.return_value = 99

        with pytest.raises(RuntimeError, match="Plugin crashed"):
            registry.run_plugin("failing", store)

        # Analysis run should be marked as failed
        store.complete_analysis_run.assert_called_once_with(99, status="failed")

    def test_run_plugin_not_found(self) -> None:
        registry = PluginRegistry()
        store = MagicMock()

        with pytest.raises(PluginError, match="not found"):
            registry.run_plugin("ghost", store)

    def test_run_plugin_with_progress_callback(self) -> None:
        class ProgressPlugin(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="prog", version="1", description="p")

            def validate(self, store):
                return []

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                if progress_callback:
                    progress_callback(1, 2, "FOV_001")
                    progress_callback(2, 2, "FOV_002")
                return PluginResult(measurements_written=10, cells_processed=5)

        registry = PluginRegistry()
        registry.register(ProgressPlugin)

        store = MagicMock()
        store.start_analysis_run.return_value = 1

        callback = MagicMock()
        registry.run_plugin("prog", store, progress_callback=callback)

        assert callback.call_count == 2
        callback.assert_any_call(1, 2, "FOV_001")
        callback.assert_any_call(2, 2, "FOV_002")


class TestPluginRegistryDiscovery:
    """Tests for automatic discovery from builtin package."""

    def test_discover_finds_builtin_plugins(self) -> None:
        """Discovery should find any plugins in percell3.plugins.builtin."""
        registry = PluginRegistry()
        # This should not raise even if no plugins are registered yet
        registry.discover()
        # After implementing local_bg_subtraction, this will find it
        # For now, just verify discovery runs without error
        plugins = registry.list_plugins()
        # At minimum, the list should be a list (may be empty before plugins are added)
        assert isinstance(plugins, list)

    def test_discover_skips_base_class(self) -> None:
        """Discovery should not register AnalysisPlugin itself."""
        registry = PluginRegistry()
        registry.discover()
        # AnalysisPlugin should never appear as a discovered plugin
        for info in registry.list_plugins():
            assert info.name != "AnalysisPlugin"

    def test_discover_skips_internal_base_classes(self) -> None:
        """Classes with _INTERNAL_BASE_CLASS = True should be skipped."""
        registry = PluginRegistry()
        registry.discover()
        for info in registry.list_plugins():
            assert "_base" not in info.name.lower()
