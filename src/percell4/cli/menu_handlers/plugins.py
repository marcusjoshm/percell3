"""Plugin handler -- list and run analysis plugins."""

from __future__ import annotations

from percell4.cli.menu_system import (
    Menu,
    MenuItem,
    MenuState,
    _MenuCancel,
    require_experiment,
)
from percell4.cli.utils import console, print_error, print_success, print_warning


def plugin_menu_handler(state: MenuState) -> None:
    """List plugins with numbered menu, run selected plugin."""
    store = require_experiment(state)

    from percell4.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    plugin_list = registry.list_plugins()

    if not plugin_list:
        print_warning("No plugins available.")
        return

    # Build menu items dynamically
    items: list[MenuItem] = []
    for idx, info in enumerate(plugin_list, 1):
        runner = _make_plugin_runner(registry, info["name"])
        items.append(
            MenuItem(str(idx), info["name"], info.get("description", ""), runner)
        )

    Menu("PLUGINS", items, state).run()
    raise _MenuCancel()


def _make_plugin_runner(registry, plugin_name: str):
    """Create a handler function for a specific plugin.

    If a custom handler exists for this plugin (with parameter prompting),
    use that. Otherwise fall back to the generic runner.
    """
    from percell4.cli.menu_handlers.plugin_handlers import PLUGIN_HANDLERS

    custom_handler = PLUGIN_HANDLERS.get(plugin_name)
    if custom_handler is not None:
        return custom_handler

    def handler(state: MenuState) -> None:
        store = require_experiment(state)

        plugin = registry.get_plugin(plugin_name)
        exp = store.db.get_experiment()
        fovs = store.db.get_fovs(exp["id"])
        fov_ids = [
            f["id"] for f in fovs
            if f["status"] not in ("deleted", "deleting", "error")
        ]

        if not fov_ids:
            print_warning("No FOVs to process")
            return

        try:
            result = plugin.run(store, fov_ids)
            print_success(
                f"Plugin '{plugin_name}' completed: "
                f"{result.fovs_processed} FOVs, "
                f"{result.measurements_added} measurements"
            )
        except Exception as e:
            print_error(str(e))

    return handler
