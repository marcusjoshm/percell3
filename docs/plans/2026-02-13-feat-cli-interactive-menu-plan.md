---
title: "Build CLI Module with Dual-Mode Interactive Menu"
type: feat
date: 2026-02-13
---

# Build CLI Module with Dual-Mode Interactive Menu

## Overview

Build Module 7 (CLI) for PerCell 3 with a dual-mode interface: an interactive numbered menu when launched with no arguments, and direct Click commands when arguments are provided. The menu lets users test completed modules (Core, IO, Workflow) interactively, with unbuilt modules shown as disabled. This is the user's primary interface to the system.

## Problem Statement

PerCell 3 has three fully implemented modules (Core, IO, Workflow) with 295 passing tests, but no user-facing interface. The only way to use the system is through Python code. Building the CLI now enables interactive testing of the import pipeline and experiment management as remaining modules (Segment, Measure, Plugins) are developed.

## Technical Approach

### Architecture

```
percell3 (no args)          percell3 import ... (with args)
       │                              │
       ▼                              ▼
  Interactive Menu ──────┐     Click Command Group
  (Rich prompts)         │            │
       │                 │            │
       ▼                 ▼            ▼
  Calls Click command functions directly
       │
       ▼
  percell3.core / percell3.io / percell3.workflow
```

The menu is a thin dispatcher. Each menu item calls the same function that the Click command calls. This means:
- All logic is testable via `CliRunner`
- Menu mode and direct mode share 100% of business logic
- Adding a new command = add a Click command + add a menu entry

### File Structure

```
src/percell3/cli/
├── __init__.py           # Public API exports
├── main.py               # Click group + interactive menu loop
├── utils.py              # Rich console, open_experiment(), progress helpers
├── create.py             # percell3 create
├── import_cmd.py         # percell3 import
├── query.py              # percell3 query
├── export.py             # percell3 export
├── workflow.py           # percell3 workflow run|list
└── stubs.py              # Disabled commands (segment, measure, threshold, plugin)

tests/test_cli/
├── conftest.py           # Fixtures (CliRunner, experiment_with_data, tiff_dir)
├── test_create.py
├── test_import.py
├── test_query.py
├── test_export.py
├── test_workflow.py
├── test_stubs.py
└── test_menu.py          # Interactive menu tests
```

### Implementation Phases

#### Phase 1: Foundation (`main.py`, `utils.py`, `create.py`)

Build the CLI skeleton and simplest command first.

**`utils.py`** — Shared CLI utilities:

```python
# src/percell3/cli/utils.py
from rich.console import Console
from rich.progress import Progress

console = Console()

def open_experiment(path: str) -> ExperimentStore:
    """Open experiment with CLI-friendly error handling."""
    try:
        return ExperimentStore.open(Path(path))
    except ExperimentNotFoundError:
        console.print(f"[red]Error:[/red] No experiment at {path}")
        raise SystemExit(1)

def error_handler(func):
    """Decorator wrapping CLI commands with standard error handling."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SystemExit:
            raise
        except ExperimentError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
        except Exception as e:
            console.print(f"[red]Internal error:[/red] {e}")
            raise SystemExit(2)
    return wrapper
```

**`main.py`** — Click group + menu:

```python
# src/percell3/cli/main.py
import click

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """PerCell 3 — Single-Cell Microscopy Analysis."""
    if ctx.invoked_subcommand is None:
        run_interactive_menu()
```

**`create.py`** — Create experiment:

```python
@cli.command()
@click.argument("path", type=click.Path())
@click.option("--name", "-n", default=None, help="Experiment name.")
@click.option("--description", "-d", default=None, help="Description.")
def create(path, name, description):
    """Create a new .percell experiment."""
    store = ExperimentStore.create(Path(path), name=name, description=description)
    store.close()
    console.print(f"[green]Created experiment at {path}[/green]")
```

- [x] Create `src/percell3/cli/utils.py` with `console`, `open_experiment()`, `error_handler`
- [x] Create `src/percell3/cli/main.py` with Click group and `invoke_without_command=True`
- [x] Create `src/percell3/cli/create.py` with `create` command
- [x] Create `tests/test_cli/conftest.py` with `runner`, `tmp_experiment` fixtures
- [x] Create `tests/test_cli/test_create.py` — success, already-exists, help text
- [x] Verify `percell3 create` works end-to-end
- [x] Update `src/percell3/cli/__init__.py` with exports

#### Phase 2: Import Command (`import_cmd.py`)

The most complex command — scans a TIFF directory, previews what was found, and imports into an experiment.

```python
@cli.command("import")
@click.argument("source", type=click.Path(exists=True))
@click.option("-e", "--experiment", required=True, type=click.Path())
@click.option("--condition", "-c", default="default", help="Condition name.")
@click.option("--channel-map", multiple=True, help="Channel mapping, e.g. '00:DAPI'.")
@click.option("--z-projection", type=click.Choice(["mip", "sum", "mean", "keep"]),
              default="mip", help="Z-stack projection method.")
@click.option("--browse", is_flag=True, help="Open folder picker for source path.")
def import_cmd(source, experiment, condition, channel_map, z_projection, browse):
    """Import TIFF images into an experiment."""
```

In interactive menu mode, import follows this flow:
1. Prompt for source (folder picker or typed path)
2. Scan directory, show preview table (regions, channels, shapes)
3. Prompt for condition name
4. Prompt for channel renaming (optional)
5. Confirm and import with Rich progress bar

- [x] Create `src/percell3/cli/import_cmd.py` with `import_cmd` command
- [x] Implement preview table showing scan results (Rich Table)
- [x] Implement progress callback for Rich Progress bar
- [x] Parse `--channel-map` format (`"00:DAPI"` → `ChannelMapping`)
- [ ] Add optional folder picker via `tkinter.filedialog.askdirectory()`
- [x] Create `tests/test_cli/test_import.py` — success, no TIFFs, bad path, help text
- [x] Test channel mapping parsing

#### Phase 3: Query and Export Commands (`query.py`, `export.py`)

Read-only commands that inspect experiment contents.

**`query.py`** — Query with subcommands:

```python
@cli.group()
@click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
@click.pass_context
def query(ctx, experiment):
    """Query experiment data."""
    ctx.ensure_object(dict)
    ctx.obj["store"] = open_experiment(experiment)

@query.command()
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table")
@click.option("--limit", default=100, help="Max rows (0 for all).")
@click.pass_context
def channels(ctx, fmt, limit):
    """List channels in the experiment."""

@query.command()
@click.pass_context
def regions(ctx, ...):
    """List regions in the experiment."""
```

**`export.py`** — Export to CSV:

```python
@cli.command()
@click.argument("output", type=click.Path())
@click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
def export(output, experiment):
    """Export measurements to CSV."""
```

- [x] Create `src/percell3/cli/query.py` with `channels`, `regions` subcommands
- [x] Implement table output with Rich Table
- [x] Implement CSV and JSON output formats
- [ ] Add `--limit` with default of 100 rows
- [x] Create `src/percell3/cli/export.py` with `export` command
- [x] Create `tests/test_cli/test_query.py` — channels, regions, formats, limit
- [x] Create `tests/test_cli/test_export.py` — success, empty experiment

#### Phase 4: Workflow Commands (`workflow.py`)

```python
@cli.group()
def workflow():
    """Manage and run workflows."""

@workflow.command("list")
def workflow_list():
    """List available preset workflows."""

@workflow.command("run")
@click.argument("name")
@click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
def workflow_run(name, experiment):
    """Run a preset or custom workflow."""
```

- [ ] Create `src/percell3/cli/workflow.py` with `list` and `run` subcommands
- [ ] List preset workflows from `percell3.workflow.defaults`
- [ ] Execute workflows with Rich progress (step-by-step status)
- [ ] Show workflow results table when complete
- [ ] Create `tests/test_cli/test_workflow.py` — list, run import workflow

#### Phase 5: Interactive Menu (`main.py` menu loop)

Build the persistent menu that dispatches to Click command functions.

```python
def run_interactive_menu():
    """Run the interactive menu loop."""
    experiment_path: Path | None = None
    store: ExperimentStore | None = None

    MENU_ITEMS = [
        ("1", "Create experiment", create_interactive, True),
        ("2", "Import images", import_interactive, True),
        ("3", "Segment cells", None, False),          # coming soon
        ("4", "Measure channels", None, False),        # coming soon
        ("5", "Apply threshold", None, False),         # coming soon
        ("6", "Query experiment", query_interactive, True),
        ("7", "Export to CSV", export_interactive, True),
        ("8", "Run workflow", workflow_interactive, True),
        ("9", "Plugin manager", None, False),          # coming soon
        ("0", "Settings / Help", show_help, True),
        ("e", "Select experiment", select_experiment, True),
        ("q", "Quit", None, True),
    ]

    while True:
        show_menu_header(experiment_path)
        for key, label, _, enabled in MENU_ITEMS:
            if enabled:
                console.print(f"  [{key}] {label}")
            else:
                console.print(f"  [{key}] {label}  [dim](coming soon)[/dim]")

        choice = Prompt.ask("Select an option")
        # dispatch...
```

Each `_interactive` function handles the prompts (experiment selection, confirmations) and then calls the Click command's underlying logic.

- [ ] Implement `run_interactive_menu()` in `main.py`
- [ ] Implement `show_menu_header()` showing current experiment info
- [ ] Implement `select_experiment()` — open existing or create new
- [ ] Wire menu items to interactive wrappers for each command
- [ ] Implement folder picker integration (`tkinter.filedialog.askdirectory`)
- [ ] Implement import preview/confirm flow in interactive mode
- [ ] Implement channel rename prompts in interactive mode
- [ ] Create `tests/test_cli/test_menu.py` — menu display, disabled items, quit
- [ ] Test `percell3` launches menu (invoke_without_command)

#### Phase 6: Stub Commands (`stubs.py`)

```python
def _coming_soon(name: str):
    """Create a Click command that prints 'coming soon'."""
    @cli.command(name)
    def stub():
        console.print(f"\n[yellow]{name.title()} is not yet available.[/yellow]")
        console.print("[dim]This feature is under development.[/dim]\n")
        raise SystemExit(0)
    return stub

segment = _coming_soon("segment")
measure = _coming_soon("measure")
threshold = _coming_soon("threshold")
```

- [ ] Create `src/percell3/cli/stubs.py` with disabled commands
- [ ] Register stubs in `main.py`
- [ ] Create `tests/test_cli/test_stubs.py` — each stub prints message, exits 0
- [ ] Test `percell3 --help` shows all commands including stubs

## Acceptance Criteria

### Functional — Direct Commands
- [ ] `percell3 create <path>` creates a `.percell` experiment
- [ ] `percell3 import <source> -e <exp>` imports TIFF directory with progress bar
- [ ] `percell3 import --browse -e <exp>` opens OS folder picker
- [ ] `percell3 query channels -e <exp>` displays channels table
- [ ] `percell3 query regions -e <exp>` displays regions table
- [ ] `percell3 export <output> -e <exp>` writes CSV
- [ ] `percell3 workflow list` shows preset workflows
- [ ] `percell3 workflow run <name> -e <exp>` executes workflow
- [ ] `percell3 segment` shows "coming soon" message
- [ ] `percell3 --help` shows all commands with descriptions

### Functional — Interactive Menu
- [ ] `percell3` (no args) launches interactive menu
- [ ] Menu shows current experiment context
- [ ] Menu remembers experiment across commands within a session
- [ ] Disabled items show "coming soon" and are not selectable
- [ ] `q` exits the menu cleanly

### Error Handling
- [ ] Invalid experiment path → exit code 1 with clear message
- [ ] Missing required options → Click's built-in error + exit code 2
- [ ] All user-facing errors formatted with Rich (no raw tracebacks)

### Quality
- [ ] All commands tested with `CliRunner`
- [ ] Tests cover success, error, and help text for each command
- [ ] Type hints on all public functions
- [ ] Exit codes: 0=success, 1=user error, 2=internal error

## Dependencies & Risks

**Dependencies:**
- `click>=8.1` — already in `pyproject.toml`
- `rich>=13.0` — already in `pyproject.toml`
- `tkinter` — bundled with Python stdlib (for folder picker)

**Risks:**

1. **tkinter availability.** Some minimal Python installations lack tkinter. The folder picker should gracefully fall back to path typing if tkinter is not available.

2. **Interactive menu testing.** Menu input/output is harder to test than Click commands. Keep the menu as thin as possible — it should only collect input and call command functions. Test the input collection separately from the business logic.

3. **Import command complexity.** The interactive import flow (scan → preview → channel rename → confirm → import) has the most state. Keep it in a single `import_interactive()` function that calls IO module functions directly. Don't try to route it through Click's argument parsing.

## Items Deferred (Not in This Plan)

These are identified by the SpecFlow analysis but deferred as YAGNI for the initial build:

- **Experiment locking** — SQLite handles basic concurrency. Add file locking if real multi-process usage is observed.
- **Disk space pre-check** — Import already fails gracefully on I/O errors. Add pre-checks later if users hit this.
- **Import interruption recovery** — ImportEngine already skips existing regions (idempotent). Sufficient for now.
- **Experiment health check / repair** — No need until corruption is observed.
- **External tool launching** (napari, Cellpose, ImageJ) — These modules aren't built yet. Add launch commands when Segment module is implemented.
- **Menu state persistence** across sessions — Simple enough to add later with a config file.
- **Verbosity controls** (`-v`, `-q`) — Can add when debugging needs arise.
- **Color/theme customization** — Rich respects `NO_COLOR` env var by default.
- **Export formats** beyond CSV — CSV covers the primary use case. Add Parquet/Excel later if needed.

## References

- Brainstorm: `docs/brainstorms/2026-02-13-cli-interactive-menu-brainstorm.md`
- CLI spec: `docs/07-cli/spec.md`
- CLI conventions: `docs/07-cli/CLAUDE.md`
- CLI acceptance tests: `docs/07-cli/acceptance-tests.md`
- ADR-005 (Click): `docs/tracking/decisions-log.md`
- Migration guide: `docs/00-overview/migration-from-v2.md`
- Core public API: `src/percell3/core/__init__.py`
- IO public API: `src/percell3/io/__init__.py`
- Workflow public API: `src/percell3/workflow/__init__.py`
