"""Measure handler -- run measurements on segmented FOVs."""

from __future__ import annotations

from percell4.cli.menu_system import MenuState, require_experiment
from percell4.cli.utils import console, make_progress, print_error, print_success, print_warning


def measure_handler(state: MenuState) -> None:
    """Build MeasurementNeeded from active assignments, run_measurements."""
    store = require_experiment(state)

    from percell4.core.constants import FovStatus

    exp = store.get_experiment()
    fovs = store.get_fovs_by_status(exp["id"], FovStatus.segmented)
    if not fovs:
        print_warning("No FOVs in 'segmented' status to measure")
        return

    console.print(f"\n[bold]Measure Channels[/bold]")
    console.print(f"  FOVs ready: [cyan]{len(fovs)}[/cyan]\n")

    try:
        from percell4.core.models import MeasurementNeeded
        from percell4.measure.auto_measure import run_measurements

        channels = store.get_channels(exp["id"])
        channel_ids = [ch["id"] for ch in channels]
        needed: list[MeasurementNeeded] = []

        for fov in fovs:
            assignments = store.get_active_assignments(fov["id"])
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

        print_success(f"Created {count} measurements across {len(fovs)} FOVs")
    except Exception as e:
        print_error(str(e))
