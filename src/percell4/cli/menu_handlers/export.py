"""Export handlers -- CSV, Prism, and compat export."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import MenuState, menu_prompt, require_experiment
from percell4.cli.utils import console, print_error, print_success, print_warning


def export_csv_handler(state: MenuState) -> None:
    """Prompt for output path, export measurements to CSV."""
    store = require_experiment(state)

    console.print("\n[bold]Export Measurements to CSV[/bold]\n")
    out_str = menu_prompt("Output CSV path", default="measurements.csv")
    out_path = Path(out_str).expanduser()

    if out_path.exists():
        print_warning(f"File exists: {out_path} (will be overwritten)")

    try:
        exp = store.get_experiment()
        fovs = store.get_fovs(exp["id"])
        fov_ids = [
            f["id"] for f in fovs
            if f["status"] not in ("deleted", "deleting", "error")
        ]

        if not fov_ids:
            print_warning("No FOVs with exportable data")
            return

        count = store.export_measurements_csv(fov_ids, out_path)
        print_success(f"Exported {count} measurement rows to {out_path}")
    except Exception as e:
        print_error(str(e))


def export_prism_handler(state: MenuState) -> None:
    """Prompt for output directory, export per-channel CSVs for Prism."""
    store = require_experiment(state)

    console.print("\n[bold]Export Prism CSVs[/bold]\n")
    out_str = menu_prompt("Output directory", default="prism_export")
    out_dir = Path(out_str).expanduser()

    try:
        import csv

        from percell4.core.constants import SCOPE_DISPLAY

        out_dir.mkdir(parents=True, exist_ok=True)
        exp = store.get_experiment()
        fovs = store.get_fovs(exp["id"])
        fov_ids = [
            f["id"] for f in fovs
            if f["status"] not in ("deleted", "deleting", "error")
        ]

        if not fov_ids:
            print_warning("No FOVs with exportable data")
            return

        all_rows: list[dict] = []
        for fov_id in fov_ids:
            measurements = store.db.get_active_measurements(fov_id)
            all_rows.extend(measurements)

        if not all_rows:
            print_warning("No measurements to export")
            return

        channels = store.get_channels(exp["id"])
        ch_lookup = {ch["id"]: ch["name"] for ch in channels}

        groups: dict[tuple, list] = {}
        for m in all_rows:
            ch_name = ch_lookup.get(m["channel_id"], "unknown")
            scope = SCOPE_DISPLAY.get(m["scope"], m["scope"])
            key = (ch_name, m["metric"], scope)
            groups.setdefault(key, []).append(m["value"])

        file_count = 0
        for (ch_name, metric, scope), values in sorted(groups.items()):
            fname = f"{ch_name}_{metric}_{scope}.csv"
            fpath = out_dir / fname
            with open(fpath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([f"{ch_name}_{metric}_{scope}"])
                for v in values:
                    writer.writerow([v])
            file_count += 1

        print_success(f"Exported {file_count} Prism CSV files to {out_dir}")
    except Exception as e:
        print_error(str(e))


def export_compat_handler(state: MenuState) -> None:
    """Prompt for output path, export in percell3-compatible format."""
    store = require_experiment(state)

    console.print("\n[bold]Export percell3-Compatible CSV[/bold]\n")
    out_str = menu_prompt("Output CSV path", default="compat_export.csv")
    out_path = Path(out_str).expanduser()

    if out_path.exists():
        print_warning(f"File exists: {out_path} (will be overwritten)")

    try:
        exp = store.get_experiment()
        fovs = store.get_fovs(exp["id"])
        fov_ids = [
            f["id"] for f in fovs
            if f["status"] not in ("deleted", "deleting", "error")
        ]

        if not fov_ids:
            print_warning("No FOVs with exportable data")
            return

        count = store.export_measurements_csv(fov_ids, out_path)
        print_success(f"Exported {count} rows in compat format to {out_path}")
    except Exception as e:
        print_error(str(e))
