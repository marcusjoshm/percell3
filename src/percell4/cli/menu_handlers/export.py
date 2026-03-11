"""Export handlers -- CSV, Prism, and TIFF export."""

from __future__ import annotations

from pathlib import Path

from percell4.cli.menu_system import (
    MenuState,
    menu_prompt,
    numbered_select_many,
    require_experiment,
)
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
        exp = store.db.get_experiment()
        fovs = store.db.get_fovs(exp["id"])
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
        exp = store.db.get_experiment()
        fovs = store.db.get_fovs(exp["id"])
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

        channels = store.db.get_channels(exp["id"])
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


def export_tiff_handler(state: MenuState) -> None:
    """Export FOV channel images as TIFF files."""
    store = require_experiment(state)

    console.print("\n[bold]Export FOV as TIFF[/bold]\n")

    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    active_fovs = [
        f for f in fovs
        if f["status"] not in ("deleted", "deleting", "error")
    ]

    if not active_fovs:
        print_warning("No FOVs with exportable data")
        return

    # Let user select FOVs
    fov_names = [f.get("display_name") or f["name"] for f in active_fovs]
    selected_names = numbered_select_many(fov_names, "Select FOVs to export")
    selected_fovs = [
        active_fovs[fov_names.index(n)] for n in selected_names
    ]

    out_str = menu_prompt("Output directory", default="tiff_export")
    out_dir = Path(out_str).expanduser()

    try:
        import tifffile

        from percell4.core.db_types import uuid_to_hex
        from percell4.core.experiment_store import find_channel_index

        out_dir.mkdir(parents=True, exist_ok=True)
        channels = store.db.get_channels(exp["id"])
        total_written = 0

        for fov in selected_fovs:
            fov_stem = (fov.get("display_name") or fov["name"]).replace(" ", "_")
            fov_hex = uuid_to_hex(fov["id"])
            for ch in channels:
                try:
                    ch_idx = find_channel_index(channels, channel_id=ch["id"])
                    img = store.layers.read_image_channel_numpy(fov_hex, ch_idx)
                except Exception:
                    continue
                fname = f"{fov_stem}_{ch['name']}.tiff"
                fpath = out_dir / fname
                tifffile.imwrite(str(fpath), img)
                total_written += 1

        if total_written == 0:
            print_warning("No images found to export")
        else:
            print_success(f"Exported {total_written} TIFF file(s) to {out_dir}")
    except ImportError:
        print_error("tifffile is not installed. Install with: pip install tifffile")
    except Exception as e:
        print_error(str(e))
