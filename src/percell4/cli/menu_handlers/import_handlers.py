"""Import handlers -- import images into the experiment."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import MenuState, menu_prompt, require_experiment
from percell4.cli.utils import console, make_progress, print_error, print_success, print_warning


def import_images_handler(state: MenuState) -> None:
    """Prompt for source directory, scan, and import with progress bar."""
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

    try:
        from percell4.io.engine import ImportEngine

        exp = store.db.get_experiment()
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
    except Exception as e:
        print_error(str(e))
