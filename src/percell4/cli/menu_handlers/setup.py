"""Setup handlers -- create and open experiments."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import MenuState, _MenuCancel, menu_prompt, require_experiment
from percell4.cli.utils import console, print_error, print_success


def create_experiment_handler(state: MenuState) -> None:
    """Prompt for TOML config path, create a new .percell experiment."""
    console.print("\n[bold]Create New Experiment[/bold]\n")

    toml_path_str = menu_prompt("Path to experiment TOML config")
    toml_path = Path(toml_path_str).expanduser()

    if not toml_path.exists():
        print_error(f"Config file not found: {toml_path}")
        return

    out_str = menu_prompt(
        "Output .percell path",
        default=str(Path.cwd() / f"{toml_path.stem}.percell"),
    )
    out_path = Path(out_str).expanduser()

    try:
        from percell4.core.experiment_store import ExperimentStore

        store = ExperimentStore.create(out_path, toml_path)
        _save_recent(out_path)

        # Set as current
        if state.store:
            state.store.close()
        state.store = store
        state.experiment_path = out_path

        exp = store.db.get_experiment()
        print_success(f"Created experiment '{exp['name']}' at {out_path}")
    except Exception as e:
        print_error(str(e))


def open_experiment_handler(state: MenuState) -> None:
    """Prompt for .percell path, open it as the current experiment."""
    console.print("\n[bold]Open Experiment[/bold]\n")

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


def _save_recent(path: Path) -> None:
    """Save experiment path to recent.json."""
    import json

    config_dir = Path.home() / ".config" / "percell4"
    config_dir.mkdir(parents=True, exist_ok=True)
    recent_file = config_dir / "recent.json"
    data = {"recent": [str(path.resolve())]}
    recent_file.write_text(json.dumps(data))
