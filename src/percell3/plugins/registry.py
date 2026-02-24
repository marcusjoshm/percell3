"""PluginRegistry — discovers and manages PerCell 3 analysis plugins."""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import pkgutil
from typing import TYPE_CHECKING, Any

from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Raised when a plugin operation fails."""


class PluginRegistry:
    """Discovers and manages analysis plugins.

    Built-in plugins are discovered by scanning the ``percell3.plugins.builtin``
    package. Each module is imported and any ``AnalysisPlugin`` subclass found
    is registered automatically.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, type[AnalysisPlugin]] = {}

    def discover(self) -> None:
        """Discover built-in plugins from the builtin package.

        Scans ``percell3.plugins.builtin`` for Python modules and registers
        any ``AnalysisPlugin`` subclass found in each module.
        """
        try:
            import percell3.plugins.builtin as builtin_pkg
        except ImportError:
            logger.warning("percell3.plugins.builtin package not found")
            return

        for importer, modname, ispkg in pkgutil.iter_modules(
            builtin_pkg.__path__, prefix="percell3.plugins.builtin."
        ):
            try:
                mod = importlib.import_module(modname)
            except Exception:
                logger.warning("Failed to import plugin module %s", modname, exc_info=True)
                continue

            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, AnalysisPlugin)
                    and obj is not AnalysisPlugin
                    and not getattr(obj, "_INTERNAL_BASE_CLASS", False)
                ):
                    instance = obj()
                    plugin_name = instance.info().name
                    self._plugins[plugin_name] = obj
                    logger.debug("Discovered plugin: %s", plugin_name)

    def register(self, plugin_cls: type[AnalysisPlugin]) -> None:
        """Manually register a plugin class.

        Args:
            plugin_cls: An AnalysisPlugin subclass to register.

        Raises:
            TypeError: If plugin_cls is not an AnalysisPlugin subclass.
        """
        if not (inspect.isclass(plugin_cls) and issubclass(plugin_cls, AnalysisPlugin)):
            raise TypeError(
                f"Expected AnalysisPlugin subclass, got {type(plugin_cls).__name__}"
            )
        instance = plugin_cls()
        self._plugins[instance.info().name] = plugin_cls

    def list_plugins(self) -> list[PluginInfo]:
        """Return metadata for all discovered plugins."""
        return [cls().info() for cls in self._plugins.values()]

    def get_plugin(self, name: str) -> AnalysisPlugin:
        """Get a plugin instance by name.

        Args:
            name: Plugin name (from PluginInfo.name).

        Returns:
            An instantiated AnalysisPlugin.

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

    def run_plugin(
        self,
        name: str,
        store: ExperimentStore,
        cell_ids: list[int] | None = None,
        parameters: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> PluginResult:
        """Run a plugin with full lifecycle management.

        1. Get plugin instance
        2. Validate against store
        3. Start analysis run in SQLite
        4. Execute plugin.run()
        5. Complete analysis run
        6. Return result

        Args:
            name: Plugin name.
            store: ExperimentStore to operate on.
            cell_ids: Optional subset of cell IDs.
            parameters: Plugin-specific parameters.
            progress_callback: Optional callback(current, total, message).

        Returns:
            PluginResult summarizing execution.

        Raises:
            PluginError: If validation fails or plugin is not found.
        """
        plugin = self.get_plugin(name)

        # Validate
        errors = plugin.validate(store)
        if errors:
            raise PluginError(
                f"Plugin {name!r} validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        # Start analysis run
        run_id = store.start_analysis_run(
            name, parameters,
        )

        try:
            result = plugin.run(
                store,
                cell_ids=cell_ids,
                parameters=parameters,
                progress_callback=progress_callback,
            )
        except Exception:
            store.complete_analysis_run(run_id, status="failed")
            raise

        # Complete analysis run
        store.complete_analysis_run(
            run_id,
            status="completed",
            cell_count=result.cells_processed,
        )

        return result
