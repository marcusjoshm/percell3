"""Segment handler -- run Cellpose segmentation via interactive prompts."""

from __future__ import annotations

from percell4.cli.menu_system import MenuState, menu_prompt, require_experiment
from percell4.cli.utils import console, make_progress, print_error, print_success, print_warning


def segment_handler(state: MenuState) -> None:
    """FOV selection, channel selection, run SegmentationEngine."""
    store = require_experiment(state)

    from percell4.core.constants import FovStatus

    exp = store.db.get_experiment()
    fovs = store.db.get_fovs_by_status(exp["id"], FovStatus.imported)
    if not fovs:
        print_warning("No FOVs in 'imported' status to segment")
        return

    console.print(f"\n[bold]Segment Cells[/bold]")
    console.print(f"  FOVs ready: [cyan]{len(fovs)}[/cyan]\n")

    # Channel selection
    channels = store.db.get_channels(exp["id"])
    ch_names = [ch["name"] for ch in channels]
    for i, name in enumerate(ch_names, 1):
        console.print(f"  [{i}] {name}")

    valid = [str(i) for i in range(1, len(ch_names) + 1)]
    if len(ch_names) == 1:
        console.print(f"  [dim](auto-selected: {ch_names[0]})[/dim]")
        channel = ch_names[0]
    else:
        choice = menu_prompt("Channel to segment on", choices=valid)
        channel = ch_names[int(choice) - 1]

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

        fov_ids = [f["id"] for f in fovs]
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
