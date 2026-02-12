# Module 7: CLI — Specification

## Overview

The CLI provides user-facing commands that wrap all PerCell 3 modules.
Built with Click for composability and Rich for terminal output.

## Top-level Group

```python
import click

@click.group()
@click.version_option()
def cli():
    """PerCell 3 — Single-cell microscopy analysis platform."""
    pass
```

## Commands

### percell3 create

```
percell3 create <path> [--name NAME] [--description DESC]
```

Creates a new .percell experiment directory.

```python
@cli.command()
@click.argument("path", type=click.Path())
@click.option("--name", "-n", default="", help="Experiment name")
@click.option("--description", "-d", default="", help="Experiment description")
def create(path, name, description):
    """Create a new PerCell 3 experiment."""
    store = ExperimentStore.create(Path(path), name=name, description=description)
    console.print(f"Created experiment at [bold]{path}[/bold]")
    store.close()
```

### percell3 import

```
percell3 import <source> -e <experiment> [--format FORMAT] [--condition COND]
    [--channel-map SRC:DST ...]
```

Imports images from a file or directory into the experiment.

| Option | Description |
|--------|-------------|
| `source` | Path to LIF file, TIFF directory, or CZI file |
| `-e, --experiment` | Path to .percell directory |
| `--format` | Force format detection: `lif`, `tiff`, `czi` (default: auto-detect) |
| `--condition` | Override condition name |
| `--channel-map` | Rename channels: `--channel-map "Ch0:DAPI" --channel-map "Ch1:GFP"` |

### percell3 segment

```
percell3 segment -e <experiment> --channel CHANNEL [--model MODEL]
    [--diameter DIAM] [--gpu/--no-gpu] [--regions REGION ...]
```

Runs Cellpose segmentation on a channel.

| Option | Default | Description |
|--------|---------|-------------|
| `--channel, -c` | (required) | Channel to segment |
| `--model, -m` | cyto3 | Cellpose model name |
| `--diameter` | auto | Cell diameter in pixels |
| `--gpu/--no-gpu` | --gpu | Use GPU for segmentation |
| `--flow-threshold` | 0.4 | Cellpose flow threshold |
| `--regions` | all | Specific regions to segment |

### percell3 measure

```
percell3 measure -e <experiment> --channels CH1 CH2 ... [--metrics M1 M2 ...]
    [--regions REGION ...]
```

Measures specified channels for all segmented cells.

| Option | Default | Description |
|--------|---------|-------------|
| `--channels, -c` | (required) | Channels to measure |
| `--metrics` | all | Metrics to compute |
| `--regions` | all | Specific regions to measure |

### percell3 threshold

```
percell3 threshold -e <experiment> --channel CHANNEL [--method METHOD]
    [--value VALUE]
```

Apply thresholding to a channel.

| Option | Default | Description |
|--------|---------|-------------|
| `--channel, -c` | (required) | Channel to threshold |
| `--method` | otsu | Thresholding method: otsu, adaptive, manual, triangle |
| `--value` | None | Manual threshold value (required for method=manual) |

### percell3 query

```
percell3 query -e <experiment> [cells|measurements|channels|regions]
    [--condition COND] [--min-area AREA] [--channels CH ...] [--limit N]
    [--format FORMAT]
```

Query the experiment database.

Subcommands:
- `cells`: List cells with optional filters
- `measurements`: Show measurement values
- `channels`: List registered channels
- `regions`: List regions and conditions

Output formats: `table` (default, Rich table), `csv`, `json`

### percell3 export

```
percell3 export -e <experiment> <output_path> [--channels CH ...]
    [--metrics M ...] [--condition COND] [--min-area AREA]
```

Export measurements to CSV.

### percell3 plugin

```
percell3 plugin list                    # List available plugins
percell3 plugin run <name> -e <exp> [--params KEY=VALUE ...]
percell3 plugin info <name>             # Show plugin details and parameters
```

### percell3 workflow

```
percell3 workflow run <name_or_yaml> -e <experiment> [--params KEY=VALUE ...]
percell3 workflow list                  # List default workflows
percell3 workflow status -e <experiment>  # Show workflow execution state
```

## Shared CLI Utilities

```python
# src/percell3/cli/utils.py

from rich.console import Console
from rich.progress import Progress

console = Console()

def open_experiment(path: str) -> ExperimentStore:
    """Open experiment with error handling for CLI."""
    try:
        return ExperimentStore.open(Path(path))
    except ExperimentNotFoundError:
        console.print(f"[red]Error:[/red] Experiment not found at {path}")
        raise SystemExit(1)

def make_progress() -> Progress:
    """Create a Rich progress bar for CLI operations."""
    return Progress(
        "[progress.description]{task.description}",
        "[progress.percentage]{task.percentage:>3.0f}%",
        "({task.completed}/{task.total})",
        console=console,
    )
```

## Error Handling

All commands should catch exceptions and display user-friendly messages:

```python
@cli.command()
def some_command():
    try:
        # ... do work ...
    except ExperimentError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Internal error:[/red] {e}")
        console.print("Please report this at: <project-issues-url>")
        raise SystemExit(2)
```

## Testing with Click

```python
from click.testing import CliRunner

def test_create_command(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["create", str(tmp_path / "test.percell")])
    assert result.exit_code == 0
    assert (tmp_path / "test.percell").exists()
```
