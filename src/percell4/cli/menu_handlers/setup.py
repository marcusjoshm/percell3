"""Setup handlers -- create and open experiments."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import MenuState, _MenuCancel, menu_prompt, numbered_select_one
from percell4.cli.utils import console, print_error, print_success


def create_experiment_handler(state: MenuState) -> None:
    """Interactively create a new experiment — path and name only.

    Channels and ROI types are discovered during import, not here.
    """
    console.print("\n[bold]Create New Experiment[/bold]\n")

    path_str = menu_prompt("Path for new experiment", default=str(Path.cwd() / "experiment.percell"))
    path = Path(path_str).expanduser()

    overwrite = False
    if path.exists() and any(path.iterdir()):
        console.print(f"[yellow]Directory is not empty:[/yellow] {path}")
        if numbered_select_one(["No", "Yes"], "Overwrite existing contents?") != "Yes":
            console.print("[yellow]Creation cancelled.[/yellow]")
            return
        overwrite = True

    name = menu_prompt("Experiment name", default=path.stem)

    try:
        from percell4.core.experiment_store import ExperimentStore

        store = ExperimentStore.create(path, name=name, overwrite=overwrite)
        _save_recent(path)

        if state.store:
            state.store.close()
        state.store = store
        state.experiment_path = path

        print_success(f"Created experiment '{name}' at {path}")
        console.print("[dim]Import images to add channels.[/dim]")
    except Exception as e:
        print_error(str(e))


def open_experiment_handler(state: MenuState) -> None:
    """Open an experiment — show recent if available, or prompt for path."""
    console.print("\n[bold]Open Experiment[/bold]\n")

    # Check for recent experiments
    recent = _load_recent()
    if recent:
        options = [str(p) for p in recent if p.exists()]
        if options:
            options.append("Browse for another...")
            choice = numbered_select_one(options, "Recent experiments")
            if choice == "Browse for another...":
                path_str = menu_prompt("Path to .percell directory")
            else:
                path_str = choice
        else:
            path_str = menu_prompt("Path to .percell directory")
    else:
        path_str = menu_prompt("Path to .percell directory")

    path = Path(path_str).expanduser()

    if not path.exists():
        print_error(f"Path does not exist: {path}")
        return

    try:
        state.set_experiment(path)
        _save_recent(path)
        exp = state.store.db.get_experiment()
        print_success(f"Opened experiment '{exp['name']}' at {path}")
    except Exception as e:
        print_error(str(e))


def _load_recent() -> list[Path]:
    """Load recent experiment paths from recent.json."""
    import json

    recent_file = Path.home() / ".config" / "percell4" / "recent.json"
    if not recent_file.exists():
        return []
    try:
        data = json.loads(recent_file.read_text())
        return [Path(p) for p in data.get("recent", [])]
    except (json.JSONDecodeError, KeyError):
        return []


def _save_recent(path: Path) -> None:
    """Save experiment path to recent.json, keeping up to 5 recent entries."""
    import json

    config_dir = Path.home() / ".config" / "percell4"
    config_dir.mkdir(parents=True, exist_ok=True)
    recent_file = config_dir / "recent.json"

    existing = _load_recent()
    resolved = path.resolve()
    # Remove duplicates, prepend new path, keep 5
    paths = [resolved] + [p for p in existing if p.resolve() != resolved]
    data = {"recent": [str(p) for p in paths[:5]]}
    recent_file.write_text(json.dumps(data))
