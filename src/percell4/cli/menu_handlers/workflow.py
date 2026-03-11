"""Workflow menu handlers — particle analysis and decapping sensor pipelines."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from percell4.cli.menu_system import (
    Menu,
    MenuItem,
    MenuState,
    _MenuCancel,
    menu_prompt,
    numbered_select_many,
    numbered_select_one,
    require_experiment,
)
from percell4.cli.utils import (
    console,
    print_error,
    print_success,
    print_warning,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _select_fovs(state: MenuState) -> tuple[Any, list[bytes]]:
    """Let the user select FOVs from the open experiment.

    Returns:
        Tuple of (store, list of selected FOV IDs).
    """
    store = require_experiment(state)
    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    active_fovs = [
        f for f in fovs if f["status"] not in ("deleted", "deleting")
    ]

    if not active_fovs:
        print_warning("No active FOVs available.")
        return store, []

    names = [f.get("display_name") or f["name"] for f in active_fovs]
    selected_names = numbered_select_many(names, "Select FOVs")

    selected_ids = []
    for name in selected_names:
        idx = names.index(name)
        selected_ids.append(active_fovs[idx]["id"])

    return store, selected_ids


def _select_channels(store: Any) -> list[str]:
    """Let the user select channels from the experiment.

    Returns:
        List of selected channel names.
    """
    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])
    if not channels:
        print_warning("No channels found.")
        return []

    ch_names = [ch["name"] for ch in channels]
    return numbered_select_many(ch_names, "Select channels")


def _workflow_progress_callbacks() -> tuple:
    """Create Rich-based progress callbacks for workflow execution.

    Returns:
        Tuple of (on_step_start, on_step_complete) callbacks.
    """
    from rich.status import Status

    statuses: dict[str, Status] = {}

    def on_step_start(step_name: str, description: str) -> None:
        console.print(f"\n  [bold cyan]>> {description}[/bold cyan]")

    def on_step_complete(step_name: str, status: str) -> None:
        if status == "completed":
            console.print(f"     [green]Done[/green]")
        elif status == "skipped":
            console.print(f"     [dim]Skipped[/dim]")
        elif status == "failed":
            console.print(f"     [bold red]Failed[/bold red]")

    return on_step_start, on_step_complete


def _load_workflow_config(
    store: Any, workflow_name: str
) -> dict[str, Any] | None:
    """Try to load a saved workflow config from the database.

    Returns:
        Parsed config dict or None if no config found.
    """
    configs = store.db.list_workflow_configs(workflow_name)
    if not configs:
        return None

    config_names = [c["config_name"] for c in configs]
    config_names.append("(use defaults)")

    selected = numbered_select_one(
        config_names, "Load saved config? Select one"
    )

    if selected == "(use defaults)":
        return None

    idx = config_names.index(selected)
    config_row = configs[idx]
    return json.loads(config_row["config_json"])


# ---------------------------------------------------------------------------
# Particle analysis handler
# ---------------------------------------------------------------------------


def particle_analysis_handler(state: MenuState) -> None:
    """Run the particle analysis workflow with user-selected parameters."""
    from percell4.workflow.particle_analysis import (
        create_particle_analysis_workflow,
    )

    store, fov_ids = _select_fovs(state)
    if not fov_ids:
        return

    console.print(f"\n[bold]Particle Analysis Workflow[/bold]")
    console.print(f"  Selected {len(fov_ids)} FOV(s)\n")

    # Try loading saved config
    saved_config = _load_workflow_config(store, "particle_analysis")

    # Channel selection for segmentation
    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])
    if not channels:
        print_error("No channels found in experiment.")
        return

    ch_names = [ch["name"] for ch in channels]

    if saved_config:
        channel_name = saved_config.get("channel_name", ch_names[0])
        model_name = saved_config.get("model_name", "cyto3")
        diameter = saved_config.get("diameter", 30.0)
        threshold_method = saved_config.get("threshold_method", "otsu")
        console.print(f"  [dim]Using saved config: channel={channel_name}, "
                       f"model={model_name}, diameter={diameter}[/dim]")
    else:
        channel_name = numbered_select_one(
            ch_names, "Select segmentation channel"
        )
        model_name = menu_prompt("Cellpose model", default="cyto3")
        diameter_str = menu_prompt("Cell diameter (pixels)", default="30")
        try:
            diameter = float(diameter_str)
        except ValueError:
            diameter = 30.0

        threshold_method = numbered_select_one(
            ["otsu", "triangle", "li"], "Threshold method"
        )

    # Export path
    export_str = menu_prompt(
        "Export CSV path (blank to skip)", default=""
    )
    export_path = Path(export_str) if export_str.strip() else None

    # Create and run workflow
    console.print("\n[bold]Running workflow...[/bold]")

    workflow = create_particle_analysis_workflow(
        channel_name=channel_name,
        model_name=model_name,
        diameter=diameter,
        threshold_method=threshold_method,
        export_path=export_path,
    )

    on_start, on_complete = _workflow_progress_callbacks()

    # Inject selected FOVs into context
    context: dict[str, Any] = {"selected_fov_ids": fov_ids}

    try:
        results = workflow.run(
            store,
            context=context,
            on_step_start=on_start,
            on_step_complete=on_complete,
        )

        console.print("\n[bold green]Workflow complete![/bold green]")

        # Summary
        for step_name, result in results.items():
            status = result.get("status", "?")
            elapsed = result.get("elapsed", 0)
            console.print(
                f"  {step_name}: {status} ({elapsed:.1f}s)"
            )

    except Exception as e:
        print_error(f"Workflow failed: {e}")
        logger.exception("Particle analysis workflow failed")


# ---------------------------------------------------------------------------
# Decapping sensor handler
# ---------------------------------------------------------------------------


def decapping_sensor_handler(state: MenuState) -> None:
    """Run the decapping sensor workflow with user-selected parameters."""
    from percell4.workflow.decapping_sensor import create_decapping_workflow

    store, fov_ids = _select_fovs(state)
    if not fov_ids:
        return

    console.print(f"\n[bold]Decapping Sensor Workflow[/bold]")
    console.print(f"  Selected {len(fov_ids)} FOV(s)\n")

    # Try loading saved config
    saved_config = _load_workflow_config(store, "decapping_sensor")

    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])
    if not channels:
        print_error("No channels found in experiment.")
        return

    ch_names = [ch["name"] for ch in channels]

    if saved_config:
        signal_channels = saved_config.get("signal_channels", ch_names[:1])
        halo_channel = saved_config.get("halo_channel", ch_names[0])
        bg_channel = saved_config.get("bg_channel")
        rounds = saved_config.get("rounds", 3)
        console.print(
            f"  [dim]Using saved config: signals={signal_channels}, "
            f"halo={halo_channel}, rounds={rounds}[/dim]"
        )
    else:
        # Select signal channels
        signal_channels = numbered_select_many(
            ch_names, "Select signal channels"
        )

        # Select halo channel
        halo_channel = numbered_select_one(
            ch_names, "Select halo channel (for segmentation)"
        )

        # Background channel (optional)
        bg_options = ["(none)"] + ch_names
        bg_selected = numbered_select_one(
            bg_options, "Background channel (optional)"
        )
        bg_channel = bg_selected if bg_selected != "(none)" else None

        # Number of thresholding rounds
        rounds_str = menu_prompt(
            "Thresholding rounds", default="3"
        )
        try:
            rounds = int(rounds_str)
        except ValueError:
            rounds = 3

    # Export path
    export_str = menu_prompt(
        "Export CSV path (blank to skip)", default=""
    )
    export_path = Path(export_str) if export_str.strip() else None

    # Create and run workflow
    console.print("\n[bold]Running workflow...[/bold]")

    workflow = create_decapping_workflow(
        signal_channels=signal_channels,
        halo_channel=halo_channel,
        bg_channel=bg_channel,
        rounds=rounds,
        export_path=export_path,
    )

    on_start, on_complete = _workflow_progress_callbacks()
    context: dict[str, Any] = {"selected_fov_ids": fov_ids}

    try:
        results = workflow.run(
            store,
            context=context,
            on_step_start=on_start,
            on_step_complete=on_complete,
        )

        console.print("\n[bold green]Workflow complete![/bold green]")

        for step_name, result in results.items():
            status = result.get("status", "?")
            elapsed = result.get("elapsed", 0)
            console.print(
                f"  {step_name}: {status} ({elapsed:.1f}s)"
            )

    except Exception as e:
        print_error(f"Workflow failed: {e}")
        logger.exception("Decapping sensor workflow failed")
