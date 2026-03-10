"""Threshold handler -- interactive thresholding via napari or CLI."""

from __future__ import annotations

from percell4.cli.menu_system import MenuState, require_experiment
from percell4.cli.utils import console, print_error, print_success, print_warning


def threshold_handler(state: MenuState) -> None:
    """Launch the napari threshold viewer, or fall back to manual CLI."""
    store = require_experiment(state)

    try:
        from percell4.viewer import NAPARI_AVAILABLE, launch_viewer
    except ImportError:
        NAPARI_AVAILABLE = False

    if NAPARI_AVAILABLE:
        exp = store.db.get_experiment()
        fovs = store.db.get_fovs(exp["id"])
        active_fovs = [f for f in fovs if f["status"] not in ("deleted", "deleting")]

        if not active_fovs:
            print_warning("No active FOVs found.")
            return

        console.print("\n[bold]Interactive Threshold[/bold]")
        console.print(
            f"  {len(active_fovs)} FOV(s) available"
        )
        console.print(
            "  [dim]Use the Threshold dock widget to adjust "
            "thresholds with live preview.[/dim]\n"
        )

        try:
            launch_viewer(store, fov_id=active_fovs[0]["id"])
            print_success("Threshold viewer closed.")
        except ImportError as e:
            print_error(str(e))
        except Exception as e:
            print_error(f"Viewer error: {e}")
    else:
        print_warning(
            "napari is not installed. Install with: pip install 'napari[all]'"
        )
        print_warning(
            "Use the CLI 'threshold' command with --value for manual thresholds."
        )
