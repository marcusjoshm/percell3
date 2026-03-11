"""Import handlers -- import images into the experiment."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import (
    MenuState,
    menu_prompt,
    numbered_select_one,
    require_experiment,
)
from percell4.cli.utils import console, make_progress, print_error, print_success, print_warning


def _select_or_create_condition(store, exp_id: bytes) -> bytes | None:
    """Prompt user to select an existing condition or create a new one.

    Returns:
        Condition ID, or None if user skips.
    """
    conditions = store.db.get_conditions(exp_id)
    choices = ["(skip)"]
    choices += [c["name"] for c in conditions]
    choices.append("(create new)")

    selection = numbered_select_one(choices, "Assign condition")

    if selection == "(skip)":
        return None
    elif selection == "(create new)":
        from percell4.core.db_types import new_uuid

        name = menu_prompt("New condition name")
        cond_id = new_uuid()
        store.db.insert_condition(cond_id, exp_id, name)
        print_success(f"Created condition '{name}'")
        return cond_id
    else:
        for c in conditions:
            if c["name"] == selection:
                return c["id"]
    return None


def _select_or_create_bio_rep(store, exp_id: bytes, condition_id: bytes) -> bytes | None:
    """Prompt user to select an existing bio rep or create a new one.

    Returns:
        Bio rep ID, or None if user skips.
    """
    bio_reps = store.db.get_bio_reps(exp_id)
    # Filter to bio reps matching the condition
    cond_reps = [br for br in bio_reps if br["condition_id"] == condition_id]

    choices = ["(skip)"]
    choices += [br["name"] for br in cond_reps]
    choices.append("(create new)")

    selection = numbered_select_one(choices, "Assign biological replicate")

    if selection == "(skip)":
        return None
    elif selection == "(create new)":
        from percell4.core.db_types import new_uuid

        name = menu_prompt("New bio rep name")
        rep_id = new_uuid()
        store.db.insert_bio_rep(rep_id, exp_id, condition_id, name)
        print_success(f"Created bio rep '{name}'")
        return rep_id
    else:
        for br in cond_reps:
            if br["name"] == selection:
                return br["id"]
    return None


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

    # Condition and bio rep assignment
    exp = store.db.get_experiment()
    condition_id = _select_or_create_condition(store, exp["id"])

    bio_rep_id = None
    if condition_id is not None:
        bio_rep_id = _select_or_create_bio_rep(store, exp["id"], condition_id)

    try:
        from percell4.io.engine import ImportEngine

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
                condition_id=condition_id,
                bio_rep_id=bio_rep_id,
                on_progress=on_progress,
            )

        print_success(f"Imported {len(fov_ids)} FOVs from {source}")
    except Exception as e:
        print_error(str(e))
