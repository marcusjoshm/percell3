"""Measure handler -- run measurements on FOVs."""

from __future__ import annotations

from percell4.cli.menu_system import (
    MenuState,
    numbered_select_many,
    require_experiment,
)
from percell4.cli.utils import console, make_progress, print_error, print_success, print_warning


def _get_active_fovs(store):
    """Return all non-deleted FOVs for the current experiment."""
    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    return [
        f for f in fovs
        if f["status"] not in ("deleted", "deleting", "error")
    ]


def measure_handler(state: MenuState) -> None:
    """Build MeasurementNeeded from active assignments, run_measurements."""
    store = require_experiment(state)

    fovs = _get_active_fovs(store)
    if not fovs:
        print_warning("No active FOVs to measure")
        return

    console.print(f"\n[bold]Measure Channels[/bold]")

    # FOV selection
    fov_names = [f["auto_name"] or f"FOV-{i+1}" for i, f in enumerate(fovs)]
    selected_names = numbered_select_many(fov_names, "FOVs to measure (numbers, 'all', or blank=all)")
    selected_fovs = [fovs[fov_names.index(n)] for n in selected_names]

    console.print(f"  Selected: [cyan]{len(selected_fovs)}[/cyan] FOVs\n")

    try:
        from percell4.core.models import MeasurementNeeded
        from percell4.measure.auto_measure import run_measurements

        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        channel_ids = [ch["id"] for ch in channels]
        needed: list[MeasurementNeeded] = []

        for fov in selected_fovs:
            assignments = store.db.get_active_assignments(fov["id"])
            for sa in assignments["segmentation"]:
                needed.append(
                    MeasurementNeeded(
                        fov_id=fov["id"],
                        roi_type_id=sa["roi_type_id"],
                        channel_ids=channel_ids,
                        reason="new_assignment",
                    )
                )

        if not needed:
            print_warning("No measurement work items found")
            return

        with make_progress() as progress:
            task = progress.add_task("Measuring...", total=len(needed))

            def on_progress(current: int, total: int) -> None:
                progress.update(task, advance=1)

            count = run_measurements(store, needed, on_progress=on_progress)

        print_success(f"Created {count} measurements across {len(selected_fovs)} FOVs")
    except Exception as e:
        print_error(str(e))
