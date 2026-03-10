"""Viewer handler -- launch napari viewer from the interactive menu."""

from __future__ import annotations

from percell4.cli.menu_system import MenuState, _MenuCancel, menu_prompt, require_experiment
from percell4.cli.utils import console, print_error, print_success, print_warning


def viewer_handler(state: MenuState) -> None:
    """Open the napari viewer for the current experiment."""
    store = require_experiment(state)

    try:
        from percell4.viewer import NAPARI_AVAILABLE, launch_viewer
    except ImportError:
        print_error("napari is not installed. Install with: pip install 'napari[all]'")
        return

    if not NAPARI_AVAILABLE:
        print_error("napari is not installed. Install with: pip install 'napari[all]'")
        return

    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])

    if not fovs:
        print_warning("No FOVs imported yet.")
        return

    # Let user pick a FOV or open the first one
    active_fovs = [f for f in fovs if f["status"] not in ("deleted", "deleting")]
    if not active_fovs:
        print_warning("No active FOVs found.")
        return

    console.print(f"\n[bold]Open Viewer[/bold]")
    console.print(f"  {len(active_fovs)} FOV(s) available")
    console.print(f"  [dim]The FOV browser widget lets you switch FOVs inside napari.[/dim]\n")

    try:
        launch_viewer(store, fov_id=active_fovs[0]["id"])
        print_success("Viewer closed.")
    except ImportError as e:
        print_error(str(e))
    except Exception as e:
        print_error(f"Viewer error: {e}")
