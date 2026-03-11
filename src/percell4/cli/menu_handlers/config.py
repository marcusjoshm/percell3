"""Config handlers -- condition/bio-rep CRUD, assignment matrix, FOV metadata."""

from __future__ import annotations

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
    format_uuid_short,
    print_error,
    print_success,
    print_warning,
)


# ---------------------------------------------------------------------------
# Config submenu entry point
# ---------------------------------------------------------------------------


def config_menu_handler(state: MenuState) -> None:
    """Config management submenu."""
    Menu(
        "CONFIG",
        [
            MenuItem("1", "Assignment matrix", "FOV config overview", _assignment_matrix_handler),
            MenuItem("2", "Conditions", "List / create / rename / delete conditions", _condition_menu_handler),
            MenuItem("3", "Bio replicates", "List / create / rename / delete bio reps", _bio_rep_menu_handler),
            MenuItem("4", "FOV metadata", "View FOV details and lineage", _fov_metadata_handler),
            MenuItem("5", "Delete FOV", "Remove a FOV with confirmation", _fov_delete_handler),
            MenuItem("6", "Workflow config", "Manage workflow configurations", _workflow_config_handler),
        ],
        state,
    ).run()
    raise _MenuCancel()


# ---------------------------------------------------------------------------
# Assignment matrix (read-only)
# ---------------------------------------------------------------------------


def _assignment_matrix_handler(state: MenuState) -> None:
    """Show FOV x segmentation/threshold assignment matrix."""
    from rich.table import Table

    store = require_experiment(state)
    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    active_fovs = [f for f in fovs if f["status"] not in ("deleted", "deleting")]

    if not active_fovs:
        print_warning("No active FOVs.")
        return

    console.print("\n[bold]Assignment Matrix[/bold]\n")

    table = Table(title="FOV Assignments")
    table.add_column("FOV", style="cyan")
    table.add_column("Status", style="dim")
    table.add_column("Segmentations", style="green")
    table.add_column("Masks", style="yellow")

    for fov in active_fovs:
        fov_label = fov.get("display_name") or fov["name"]
        assignments = store.db.get_active_assignments(fov["id"])

        seg_names = []
        for seg_row in assignments["segmentation"]:
            seg_set = store.db.get_segmentation_set(seg_row["segmentation_set_id"])
            if seg_set:
                roi_type = store.db.get_roi_type_definition(seg_set["produces_roi_type_id"])
                name = roi_type["name"] if roi_type else seg_set["seg_type"]
                seg_names.append(name)

        mask_names = []
        for mask_row in assignments["mask"]:
            # threshold_mask_id references threshold_masks table
            mask_names.append(format_uuid_short(mask_row["threshold_mask_id"]))

        table.add_row(
            fov_label,
            fov["status"],
            ", ".join(seg_names) if seg_names else "-",
            ", ".join(mask_names) if mask_names else "-",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Condition CRUD
# ---------------------------------------------------------------------------


def _condition_menu_handler(state: MenuState) -> None:
    """Submenu for condition management."""
    Menu(
        "CONDITIONS",
        [
            MenuItem("1", "List conditions", "Show all conditions", _list_conditions),
            MenuItem("2", "Create condition", "Add a new condition", _create_condition),
            MenuItem("3", "Rename condition", "Change condition name", _rename_condition),
            MenuItem("4", "Delete condition", "Remove a condition", _delete_condition),
        ],
        state,
    ).run()
    raise _MenuCancel()


def _list_conditions(state: MenuState) -> None:
    """List all conditions with their bio reps."""
    from rich.table import Table

    store = require_experiment(state)
    exp = store.db.get_experiment()
    conditions = store.db.get_conditions(exp["id"])

    if not conditions:
        print_warning("No conditions defined.")
        return

    table = Table(title="Conditions")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Bio Reps", style="green")

    for cond in conditions:
        bio_reps = store.db.get_bio_reps_for_condition(cond["id"])
        rep_names = ", ".join(r["name"] for r in bio_reps) if bio_reps else "-"
        table.add_row(cond["name"], format_uuid_short(cond["id"]), rep_names)

    console.print(table)


def _create_condition(state: MenuState) -> None:
    """Create a new condition."""
    from percell4.core.db_types import new_uuid

    store = require_experiment(state)
    exp = store.db.get_experiment()

    name = menu_prompt("Condition name")
    if not name.strip():
        print_error("Name cannot be empty.")
        return

    try:
        cond_id = new_uuid()
        store.db.insert_condition(cond_id, exp["id"], name.strip())
        print_success(f"Created condition '{name.strip()}'")
    except Exception as e:
        print_error(str(e))


def _rename_condition(state: MenuState) -> None:
    """Rename an existing condition."""
    store = require_experiment(state)
    exp = store.db.get_experiment()
    conditions = store.db.get_conditions(exp["id"])

    if not conditions:
        print_warning("No conditions to rename.")
        return

    names = [c["name"] for c in conditions]
    selected = numbered_select_one(names, "Select condition to rename")
    cond = conditions[names.index(selected)]

    new_name = menu_prompt(f"New name for '{selected}'")
    if not new_name.strip():
        print_error("Name cannot be empty.")
        return

    try:
        store.db.rename_condition(cond["id"], new_name.strip())
        print_success(f"Renamed '{selected}' -> '{new_name.strip()}'")
    except Exception as e:
        print_error(str(e))


def _delete_condition(state: MenuState) -> None:
    """Delete a condition (with confirmation)."""
    store = require_experiment(state)
    exp = store.db.get_experiment()
    conditions = store.db.get_conditions(exp["id"])

    if not conditions:
        print_warning("No conditions to delete.")
        return

    names = [c["name"] for c in conditions]
    selected = numbered_select_one(names, "Select condition to delete")
    cond = conditions[names.index(selected)]

    # Check for referencing bio_reps
    bio_reps = store.db.get_bio_reps_for_condition(cond["id"])
    if bio_reps:
        print_warning(
            f"Condition '{selected}' has {len(bio_reps)} bio rep(s). "
            "Delete them first."
        )
        return

    confirm = menu_prompt(f"Delete condition '{selected}'? (yes/no)", default="no")
    if confirm.lower() != "yes":
        console.print("[dim]Cancelled.[/dim]")
        return

    try:
        store.db.delete_condition(cond["id"])
        print_success(f"Deleted condition '{selected}'")
    except Exception as e:
        print_error(str(e))


# ---------------------------------------------------------------------------
# Bio Rep CRUD
# ---------------------------------------------------------------------------


def _bio_rep_menu_handler(state: MenuState) -> None:
    """Submenu for biological replicate management."""
    Menu(
        "BIO REPLICATES",
        [
            MenuItem("1", "List bio reps", "Show all biological replicates", _list_bio_reps),
            MenuItem("2", "Create bio rep", "Add a new bio rep", _create_bio_rep),
            MenuItem("3", "Rename bio rep", "Change bio rep name", _rename_bio_rep),
            MenuItem("4", "Delete bio rep", "Remove a bio rep", _delete_bio_rep),
        ],
        state,
    ).run()
    raise _MenuCancel()


def _list_bio_reps(state: MenuState) -> None:
    """List all bio reps grouped by condition."""
    from rich.table import Table

    store = require_experiment(state)
    exp = store.db.get_experiment()
    conditions = store.db.get_conditions(exp["id"])
    bio_reps = store.db.get_bio_reps(exp["id"])

    if not bio_reps:
        print_warning("No biological replicates defined.")
        return

    cond_lookup = {c["id"]: c["name"] for c in conditions}

    table = Table(title="Biological Replicates")
    table.add_column("Name", style="cyan")
    table.add_column("Condition", style="green")
    table.add_column("ID", style="dim")

    for rep in bio_reps:
        cond_name = cond_lookup.get(rep["condition_id"], "?")
        table.add_row(rep["name"], cond_name, format_uuid_short(rep["id"]))

    console.print(table)


def _create_bio_rep(state: MenuState) -> None:
    """Create a new biological replicate under a condition."""
    from percell4.core.db_types import new_uuid

    store = require_experiment(state)
    exp = store.db.get_experiment()
    conditions = store.db.get_conditions(exp["id"])

    if not conditions:
        print_warning("Create a condition first.")
        return

    cond_names = [c["name"] for c in conditions]
    selected_cond = numbered_select_one(cond_names, "Select condition")
    cond = conditions[cond_names.index(selected_cond)]

    name = menu_prompt("Bio rep name")
    if not name.strip():
        print_error("Name cannot be empty.")
        return

    try:
        rep_id = new_uuid()
        store.db.insert_bio_rep(rep_id, exp["id"], cond["id"], name.strip())
        print_success(f"Created bio rep '{name.strip()}' under '{selected_cond}'")
    except Exception as e:
        print_error(str(e))


def _rename_bio_rep(state: MenuState) -> None:
    """Rename an existing biological replicate."""
    store = require_experiment(state)
    exp = store.db.get_experiment()
    bio_reps = store.db.get_bio_reps(exp["id"])

    if not bio_reps:
        print_warning("No bio reps to rename.")
        return

    names = [r["name"] for r in bio_reps]
    selected = numbered_select_one(names, "Select bio rep to rename")
    rep = bio_reps[names.index(selected)]

    new_name = menu_prompt(f"New name for '{selected}'")
    if not new_name.strip():
        print_error("Name cannot be empty.")
        return

    try:
        store.db.rename_bio_rep(rep["id"], new_name.strip())
        print_success(f"Renamed '{selected}' -> '{new_name.strip()}'")
    except Exception as e:
        print_error(str(e))


def _delete_bio_rep(state: MenuState) -> None:
    """Delete a biological replicate (with confirmation)."""
    store = require_experiment(state)
    exp = store.db.get_experiment()
    bio_reps = store.db.get_bio_reps(exp["id"])

    if not bio_reps:
        print_warning("No bio reps to delete.")
        return

    names = [r["name"] for r in bio_reps]
    selected = numbered_select_one(names, "Select bio rep to delete")
    rep = bio_reps[names.index(selected)]

    confirm = menu_prompt(f"Delete bio rep '{selected}'? (yes/no)", default="no")
    if confirm.lower() != "yes":
        console.print("[dim]Cancelled.[/dim]")
        return

    try:
        store.db.delete_bio_rep(rep["id"])
        print_success(f"Deleted bio rep '{selected}'")
    except Exception as e:
        print_error(str(e))


# ---------------------------------------------------------------------------
# FOV metadata view
# ---------------------------------------------------------------------------


def _fov_metadata_handler(state: MenuState) -> None:
    """Show detailed FOV metadata including lineage."""
    from rich.table import Table

    store = require_experiment(state)
    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    active_fovs = [f for f in fovs if f["status"] not in ("deleted", "deleting")]

    if not active_fovs:
        print_warning("No active FOVs.")
        return

    names = [f.get("display_name") or f["name"] for f in active_fovs]
    selected = numbered_select_one(names, "Select FOV")
    fov = active_fovs[names.index(selected)]

    console.print(f"\n[bold]FOV: {selected}[/bold]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("ID", format_uuid_short(fov["id"]))
    table.add_row("Name", fov["name"])
    if fov.get("display_name"):
        table.add_row("Display Name", fov["display_name"])
    table.add_row("Status", fov["status"])

    # Condition / Bio rep
    if fov.get("condition_id"):
        cond = store.db.get_condition(fov["condition_id"])
        table.add_row("Condition", cond["name"] if cond else "?")
    if fov.get("bio_rep_id"):
        rep = store.db.get_bio_rep(fov["bio_rep_id"])
        table.add_row("Bio Rep", rep["name"] if rep else "?")

    if fov.get("pixel_size_um") is not None:
        table.add_row("Pixel Size", f"{fov['pixel_size_um']:.4f} um")

    # Lineage info
    depth = fov.get("lineage_depth", 0)
    table.add_row("Lineage Depth", str(depth))
    if fov.get("lineage_path"):
        table.add_row("Lineage Path", fov["lineage_path"])
    if fov.get("parent_fov_id"):
        parent = store.db.get_fov(fov["parent_fov_id"])
        parent_name = (parent.get("display_name") or parent["name"]) if parent else "?"
        table.add_row("Parent FOV", parent_name)
    if fov.get("derivation_op"):
        table.add_row("Derivation Op", fov["derivation_op"])

    # ROI count
    roi_count = store.db.count_rois_for_fov(fov["id"])
    table.add_row("ROI Count", str(roi_count))

    # Measurement count
    meas_count = store.db.count_measurements_for_fov(fov["id"])
    table.add_row("Measurements", str(meas_count))

    if fov.get("zarr_path"):
        table.add_row("Zarr Path", fov["zarr_path"])

    console.print(table)


# ---------------------------------------------------------------------------
# FOV delete with double-confirmation
# ---------------------------------------------------------------------------


def _fov_delete_handler(state: MenuState) -> None:
    """Delete a FOV with double confirmation."""
    store = require_experiment(state)
    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    active_fovs = [f for f in fovs if f["status"] not in ("deleted", "deleting")]

    if not active_fovs:
        print_warning("No active FOVs.")
        return

    names = [f.get("display_name") or f["name"] for f in active_fovs]
    selected = numbered_select_one(names, "Select FOV to delete")
    fov = active_fovs[names.index(selected)]

    # First confirmation
    confirm1 = menu_prompt(f"Delete FOV '{selected}'? (yes/no)", default="no")
    if confirm1.lower() != "yes":
        console.print("[dim]Cancelled.[/dim]")
        return

    # Gather impact info
    roi_count = store.db.count_rois_for_fov(fov["id"])
    meas_count = store.db.count_measurements_for_fov(fov["id"])

    # Second confirmation with impact
    confirm2 = menu_prompt(
        f"This will delete {roi_count} ROI(s) and {meas_count} measurement(s). "
        f"Confirm? (yes/no)",
        default="no",
    )
    if confirm2.lower() != "yes":
        console.print("[dim]Cancelled.[/dim]")
        return

    try:
        store.delete_fov(fov["id"])
        print_success(f"Deleted FOV '{selected}'")
    except Exception as e:
        print_error(str(e))


# ---------------------------------------------------------------------------
# Workflow Config CRUD
# ---------------------------------------------------------------------------


def _workflow_config_handler(state: MenuState) -> None:
    """Submenu for workflow configuration management."""
    Menu(
        "WORKFLOW CONFIG",
        [
            MenuItem("1", "List configs", "Show saved workflow configs", _list_workflow_configs),
            MenuItem("2", "Create config", "Save a new workflow config", _create_workflow_config),
            MenuItem("3", "Edit config", "Modify an existing config", _edit_workflow_config),
            MenuItem("4", "Delete config", "Remove a saved config", _delete_workflow_config),
        ],
        state,
    ).run()
    raise _MenuCancel()


def _list_workflow_configs(state: MenuState) -> None:
    """List all saved workflow configurations."""
    import json

    from rich.table import Table

    store = require_experiment(state)
    configs = store.db.list_workflow_configs()

    if not configs:
        print_warning("No workflow configurations saved.")
        return

    table = Table(title="Workflow Configurations")
    table.add_column("Workflow", style="cyan")
    table.add_column("Config Name", style="green")
    table.add_column("Parameters", style="dim")
    table.add_column("Updated", style="dim")

    for cfg in configs:
        try:
            params = json.loads(cfg["config_json"])
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        except (json.JSONDecodeError, TypeError):
            param_str = cfg["config_json"]

        # Truncate long param strings
        if len(param_str) > 60:
            param_str = param_str[:57] + "..."

        table.add_row(
            cfg["workflow_name"],
            cfg["config_name"],
            param_str,
            cfg.get("updated_at", ""),
        )

    console.print(table)


def _create_workflow_config(state: MenuState) -> None:
    """Create a new workflow configuration."""
    import json

    from percell4.core.db_types import new_uuid

    store = require_experiment(state)

    workflow_name = numbered_select_one(
        ["particle_analysis", "decapping_sensor"],
        "Select workflow",
    )

    config_name = menu_prompt("Config name (e.g. 'default', 'large_cells')")
    if not config_name.strip():
        print_error("Name cannot be empty.")
        return

    # Prompt for parameters based on workflow type
    params: dict = {}

    if workflow_name == "particle_analysis":
        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_names = [ch["name"] for ch in channels]

        if ch_names:
            params["channel_name"] = numbered_select_one(
                ch_names, "Segmentation channel"
            )
        else:
            params["channel_name"] = menu_prompt("Channel name")

        params["model_name"] = menu_prompt("Cellpose model", default="cyto3")
        diameter_str = menu_prompt("Cell diameter", default="30")
        try:
            params["diameter"] = float(diameter_str)
        except ValueError:
            params["diameter"] = 30.0
        params["threshold_method"] = numbered_select_one(
            ["otsu", "triangle", "li"], "Threshold method"
        )

    elif workflow_name == "decapping_sensor":
        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_names = [ch["name"] for ch in channels]

        if ch_names:
            params["signal_channels"] = numbered_select_many(
                ch_names, "Signal channels"
            )
            params["halo_channel"] = numbered_select_one(
                ch_names, "Halo channel"
            )
            bg_options = ["(none)"] + ch_names
            bg_sel = numbered_select_one(bg_options, "Background channel")
            params["bg_channel"] = bg_sel if bg_sel != "(none)" else None
        else:
            params["signal_channels"] = []
            params["halo_channel"] = menu_prompt("Halo channel")
            params["bg_channel"] = None

        rounds_str = menu_prompt("Thresholding rounds", default="3")
        try:
            params["rounds"] = int(rounds_str)
        except ValueError:
            params["rounds"] = 3

    config_json = json.dumps(params)

    try:
        cfg_id = new_uuid()
        store.db.insert_workflow_config(
            cfg_id, workflow_name, config_name.strip(), config_json
        )
        print_success(f"Created config '{config_name.strip()}' for {workflow_name}")
    except Exception as e:
        print_error(str(e))


def _edit_workflow_config(state: MenuState) -> None:
    """Edit an existing workflow configuration's JSON."""
    import json

    store = require_experiment(state)
    configs = store.db.list_workflow_configs()

    if not configs:
        print_warning("No configs to edit.")
        return

    labels = [f"{c['workflow_name']}/{c['config_name']}" for c in configs]
    selected = numbered_select_one(labels, "Select config to edit")
    cfg = configs[labels.index(selected)]

    try:
        current = json.loads(cfg["config_json"])
    except (json.JSONDecodeError, TypeError):
        current = {}

    console.print(f"\n[bold]Current parameters:[/bold]")
    for k, v in current.items():
        console.print(f"  {k} = {v}")

    console.print(
        "\n[dim]Edit individual values (press Enter to keep current):[/dim]"
    )

    updated = dict(current)
    for k, v in current.items():
        new_val = menu_prompt(f"  {k}", default=str(v))
        if new_val != str(v):
            # Try to preserve types
            if isinstance(v, bool):
                updated[k] = new_val.lower() in ("true", "1", "yes")
            elif isinstance(v, int):
                try:
                    updated[k] = int(new_val)
                except ValueError:
                    updated[k] = new_val
            elif isinstance(v, float):
                try:
                    updated[k] = float(new_val)
                except ValueError:
                    updated[k] = new_val
            elif isinstance(v, list):
                # Keep as-is if user didn't change
                updated[k] = v
            else:
                updated[k] = new_val

    new_json = json.dumps(updated)
    try:
        store.db.update_workflow_config(cfg["id"], new_json)
        print_success(f"Updated config '{selected}'")
    except Exception as e:
        print_error(str(e))


def _delete_workflow_config(state: MenuState) -> None:
    """Delete a workflow configuration."""
    store = require_experiment(state)
    configs = store.db.list_workflow_configs()

    if not configs:
        print_warning("No configs to delete.")
        return

    labels = [f"{c['workflow_name']}/{c['config_name']}" for c in configs]
    selected = numbered_select_one(labels, "Select config to delete")
    cfg = configs[labels.index(selected)]

    confirm = menu_prompt(f"Delete config '{selected}'? (yes/no)", default="no")
    if confirm.lower() != "yes":
        console.print("[dim]Cancelled.[/dim]")
        return

    try:
        store.db.delete_workflow_config(cfg["id"])
        print_success(f"Deleted config '{selected}'")
    except Exception as e:
        print_error(str(e))
