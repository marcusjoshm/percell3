"""Import handlers -- import images into the experiment."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import (
    MenuState,
    menu_prompt,
    require_experiment,
)
from percell4.cli.utils import console, make_progress, print_error, print_success, print_warning


def import_images_handler(state: MenuState) -> None:
    """Prompt for source directory, scan, and import with progress bar.

    Channels are discovered from the first image file when none exist yet.
    Condition and bio-rep assignment is handled separately via Config Management.
    """
    store = require_experiment(state)

    console.print("\n[bold]Import Images[/bold]\n")
    source_str = menu_prompt("Source directory with image files")
    source = Path(source_str).expanduser()

    if not source.exists():
        print_error(f"Directory not found: {source}")
        return

    from percell4.io.scanner import scan_directory

    files = scan_directory(source)
    if not files:
        print_warning(f"No image files found in {source}")
        return

    console.print(f"  Found [cyan]{len(files)}[/cyan] image files")

    exp = store.db.get_experiment()

    try:
        from percell4.io.engine import ImportEngine
        from percell4.io.tiff import read_tiff

        channels = store.db.get_channels(exp["id"])

        if not channels:
            # No channels yet — discover from first image file
            console.print("\n[bold]Channel Setup[/bold] (discovered from first image)")
            first_image = read_tiff(files[0].path)
            if first_image.ndim == 3:
                n_channels = first_image.shape[0]
            else:
                n_channels = 1

            from percell4.core.db_types import new_uuid

            for i in range(n_channels):
                default_name = f"Ch{i}" if n_channels > 1 else "Ch0"
                ch_name = menu_prompt(f"  Name for channel {i}", default=default_name)
                ch_id = new_uuid()
                store.db.insert_channel(ch_id, exp["id"], ch_name, "signal", display_order=i)
                console.print(f"    [dim]Added channel '{ch_name}'[/dim]")

            channels = store.db.get_channels(exp["id"])

        ch_mapping = {i: ch["id"] for i, ch in enumerate(channels)}

        engine = ImportEngine()
        paths = [f.path for f in files]

        with make_progress() as progress:
            task = progress.add_task("Importing...", total=len(paths))

            def on_progress(current: int, total: int, name: str) -> None:
                progress.update(task, advance=1, description=f"Importing {name}")

            fov_ids = engine.import_images(
                store,
                paths,
                ch_mapping,
                on_progress=on_progress,
            )

        print_success(f"Imported {len(fov_ids)} FOVs from {source}")
        console.print("[dim]Use Config > Conditions to organize FOVs by condition/bio-rep.[/dim]")
    except Exception as e:
        print_error(str(e))
