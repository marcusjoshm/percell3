"""PluginRegistry — discovers and manages PerCell 4 analysis and visualization plugins."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Union

from percell4.plugins.base import AnalysisPlugin, VisualizationPlugin

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Raised when a plugin operation fails."""


PluginType = Union[AnalysisPlugin, VisualizationPlugin]


class PluginRegistry:
    """Discovers and manages analysis and visualization plugins.

    Built-in plugins are discovered by scanning the ``percell4.plugins``
    package. Each module is imported and any ``AnalysisPlugin`` or
    ``VisualizationPlugin`` subclass found is registered automatically.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, type[AnalysisPlugin] | type[VisualizationPlugin]] = {}
        self._discover()

    def _discover(self) -> None:
        """Discover built-in plugins from the plugins package.

        Scans ``percell4.plugins`` for Python modules and registers
        any ``AnalysisPlugin`` or ``VisualizationPlugin`` subclass found.
        """
        try:
            import percell4.plugins as plugins_pkg
        except ImportError:
            logger.warning("percell4.plugins package not found")
            return

        for _importer, modname, _ispkg in pkgutil.iter_modules(
            plugins_pkg.__path__, prefix="percell4.plugins."
        ):
            # Skip base and registry modules
            basename = modname.rsplit(".", 1)[-1]
            if basename in ("base", "registry", "__init__"):
                continue

            try:
                mod = importlib.import_module(modname)
            except Exception:
                logger.warning(
                    "Failed to import plugin module %s", modname, exc_info=True
                )
                continue

            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if obj is AnalysisPlugin or obj is VisualizationPlugin:
                    continue
                if issubclass(obj, (AnalysisPlugin, VisualizationPlugin)):
                    plugin_name = getattr(obj, "name", None)
                    if plugin_name:
                        self._plugins[plugin_name] = obj
                        logger.debug("Discovered plugin: %s", plugin_name)

    def get_plugin(self, name: str) -> PluginType:
        """Get a plugin instance by name.

        Args:
            name: Plugin name (class attribute ``name``).

        Returns:
            An instantiated plugin.

        Raises:
            PluginError: If the plugin is not found.
        """
        cls = self._plugins.get(name)
        if cls is None:
            available = sorted(self._plugins.keys())
            raise PluginError(
                f"Plugin {name!r} not found. Available: {available}"
            )
        return cls()

    def list_plugins(self) -> list[dict[str, str]]:
        """Return list of {name, description, type} for each plugin."""
        result: list[dict[str, str]] = []
        for plugin_name, cls in sorted(self._plugins.items()):
            plugin_type = (
                "analysis"
                if issubclass(cls, AnalysisPlugin)
                else "visualization"
            )
            result.append(
                {
                    "name": plugin_name,
                    "description": getattr(cls, "description", ""),
                    "type": plugin_type,
                }
            )
        return result
