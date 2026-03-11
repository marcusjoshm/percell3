"""Segment handler -- run Cellpose segmentation via interactive prompts."""

from __future__ import annotations

from percell4.cli.menu_system import (
    MenuState,
    menu_prompt,
    numbered_select_many,
    numbered_select_one,
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


def segment_handler(state: MenuState) -> None:
    """FOV selection, channel selection, run SegmentationEngine."""
    store = require_experiment(state)

    fovs = _get_active_fovs(store)
    if not fovs:
        print_warning("No active FOVs to segment")
        return

    console.print(f"\n[bold]Segment Cells[/bold]")

    # FOV selection
    fov_names = [f["auto_name"] or f"FOV-{i+1}" for i, f in enumerate(fovs)]
    selected_names = numbered_select_many(fov_names, "FOVs to segment (numbers, 'all', or blank=all)")
    selected_fovs = [fovs[fov_names.index(n)] for n in selected_names]

    console.print(f"  Selected: [cyan]{len(selected_fovs)}[/cyan] FOVs\n")

    # Channel selection
    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])
    ch_names = [ch["name"] for ch in channels]
    channel = numbered_select_one(ch_names, "Channel to segment on")

    model = menu_prompt("Cellpose model", default="cyto3")
    diameter_str = menu_prompt("Cell diameter", default="30")

    try:
        diameter = float(diameter_str)
    except ValueError:
        print_error(f"Invalid diameter: {diameter_str}")
        return

    try:
        from percell4.segment._engine import SegmentationEngine
        from percell4.segment.cellpose_adapter import CellposeSegmenter

        fov_ids = [f["id"] for f in selected_fovs]
        params = {"model_name": model, "diameter": diameter}
        segmenter = CellposeSegmenter(model_name=model, diameter=diameter)
        engine = SegmentationEngine()

        with make_progress() as progress:
            task = progress.add_task("Segmenting...", total=len(fov_ids))

            def on_progress(current: int, total: int) -> None:
                progress.update(task, advance=1)

            seg_set_id, needed = engine.run(
                store, fov_ids, channel, "cell", segmenter,
                parameters=params, on_progress=on_progress,
            )

        print_success(
            f"Segmented {len(fov_ids)} FOVs "
            f"({len(needed)} measurement jobs pending)"
        )
    except Exception as e:
        print_error(str(e))
