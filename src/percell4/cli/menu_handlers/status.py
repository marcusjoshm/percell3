"""Status handler -- experiment dashboard with Rich Table."""

from __future__ import annotations

from percell4.cli.menu_system import MenuState, require_experiment
from percell4.cli.utils import FOV_STATUS_EXPLANATIONS, console, format_uuid_short


def status_handler(state: MenuState) -> None:
    """Show experiment dashboard with FOV status summary."""
    store = require_experiment(state)

    from rich.table import Table

    exp = store.db.get_experiment()
    console.print(f"\n[bold]{exp['name']}[/bold]")
    console.print(f"  Path: {store.root}")

    channels = store.db.get_channels(exp["id"])
    console.print(f"  Channels: {', '.join(ch['name'] for ch in channels)}")

    fovs = store.db.get_fovs(exp["id"])
    if not fovs:
        console.print("  [dim]No FOVs imported yet.[/dim]")
        return

    # Build status summary
    status_counts: dict[str, int] = {}
    for fov in fovs:
        s = fov["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    table = Table(title="FOV Status Summary")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Explanation", style="dim")

    for s, count in sorted(status_counts.items()):
        explanation = FOV_STATUS_EXPLANATIONS.get(s, "")
        table.add_row(s, str(count), explanation)

    console.print(table)
    console.print(f"\n  Total FOVs: {len(fovs)}")
