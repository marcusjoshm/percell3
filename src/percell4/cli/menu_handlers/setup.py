"""Setup handlers -- create and open experiments."""

from __future__ import annotations

import tempfile
from pathlib import Path

from percell4.cli.menu_system import MenuState, _MenuCancel, menu_prompt, numbered_select_one
from percell4.cli.utils import console, print_error, print_success


def create_experiment_handler(state: MenuState) -> None:
    """Interactively create a new experiment with auto-generated config."""
    console.print("\n[bold]Create New Experiment[/bold]\n")

    # 1. Get experiment path
    path_str = menu_prompt("Path for new experiment", default=str(Path.cwd() / "experiment.percell"))
    path = Path(path_str).expanduser()

    # Check if directory already exists
    if path.exists() and any(path.iterdir()):
        console.print(f"[yellow]Directory is not empty:[/yellow] {path}")
        if numbered_select_one(["No", "Yes"], "Overwrite existing contents?") != "Yes":
            console.print("[yellow]Creation cancelled.[/yellow]")
            return

    # 2. Get experiment name and description
    name = menu_prompt("Experiment name", default="My Experiment")
    description = menu_prompt("Description", default="")

    # 3. Get channel info
    console.print("\n[bold]Channels[/bold] (enter channel names, empty line to finish)")
    channels: list[dict[str, str | int]] = []
    order = 0
    while True:
        ch_name = menu_prompt(f"Channel {order + 1} name (empty to finish)", default="")
        if not ch_name:
            break
        role = menu_prompt(f"  Role for '{ch_name}'", default="signal")
        channels.append({"name": ch_name, "role": role, "display_order": order})
        order += 1

    if not channels:
        # Default channels if none provided
        channels = [
            {"name": "DAPI", "role": "nuclear", "display_order": 0},
            {"name": "GFP", "role": "signal", "display_order": 1},
        ]
        console.print("[dim]No channels entered, using defaults: DAPI, GFP[/dim]")

    # 4. Generate TOML config and create experiment
    toml_lines = [
        "[experiment]",
        f'name = "{name}"',
        f'description = "{description}"',
        "",
    ]
    for ch in channels:
        toml_lines.extend([
            "[[channels]]",
            f'name = "{ch["name"]}"',
            f'role = "{ch["role"]}"',
            f'display_order = {ch["display_order"]}',
            "",
        ])
    toml_lines.extend([
        "[[roi_types]]",
        'name = "cell"',
    ])

    try:
        from percell4.core.experiment_store import ExperimentStore

        # Write temp TOML and create experiment
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("\n".join(toml_lines) + "\n")
            tmp_toml = Path(f.name)

        try:
            store = ExperimentStore.create(path, tmp_toml)
        finally:
            tmp_toml.unlink(missing_ok=True)

        _save_recent(path)

        # Set as current
        if state.store:
            state.store.close()
        state.store = store
        state.experiment_path = path

        print_success(f"Created experiment '{name}' at {path}")
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
