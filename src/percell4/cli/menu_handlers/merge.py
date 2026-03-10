"""Merge handler -- merge another .percell experiment."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import MenuState, menu_prompt, require_experiment
from percell4.cli.utils import console, print_error, print_success, print_warning


def merge_handler(state: MenuState) -> None:
    """Prompt for source .percell path, delegate to store.merge_experiment."""
    store = require_experiment(state)

    console.print("\n[bold]Merge Experiment[/bold]\n")
    source_str = menu_prompt("Path to source .percell directory")
    source_path = Path(source_str).expanduser()

    if not source_path.exists():
        print_error(f"Path does not exist: {source_path}")
        return

    try:
        db_path = (
            source_path / "experiment.db"
            if source_path.is_dir()
            else source_path
        )
        result = store.merge_experiment(db_path)

        console.print("\n[bold]Merge complete[/bold]")
        if result.get("warnings"):
            for w in result["warnings"]:
                print_warning(w)

        print_success(f"Merged {source_path} into {store.root}")
    except Exception as e:
        print_error(str(e))
