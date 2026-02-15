---
title: "CLI Module (Module 7) — Build Patterns and Code Review Findings"
date: 2026-02-13
category: architecture-decisions
tags: [cli-module, code-review, click, rich, interactive-menu, lazy-imports, startup-performance, type-safety]
modules: [cli]
severity: p2
status: resolved
---

# CLI Module — Build Patterns and Code Review Findings

## Problem Statement

PerCell 3 needed a user-facing CLI (Module 7) to expose the three completed modules (Core, IO, Workflow) for interactive testing. The CLI provides a dual-mode interface: an interactive Rich menu when launched with no arguments, and direct Click subcommands when arguments are provided. After building the module (10 source files, ~1,100 LOC, 48 tests), a 6-agent parallel code review identified 10 findings (6 P2, 4 P3) covering startup performance, logic duplication, type safety, and agent-hostile patterns.

## Architecture & Key Decisions

### Dual-Mode Design

```
percell3 (no args)          percell3 import ... (with args)
       |                              |
       v                              v
  Interactive Menu            Click Command Group
  (Rich prompts)                      |
       |                              |
       v                              v
  Calls Click command functions directly
       |
       v
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
├── main.py               # Click group + invoke_without_command → menu
├── utils.py              # console, open_experiment(), error_handler, make_progress
├── create.py             # percell3 create <path>
├── import_cmd.py         # percell3 import <source> -e <exp>
├── query.py              # percell3 query -e <exp> channels|regions|conditions
├── export.py             # percell3 export <output> -e <exp>
├── workflow.py           # percell3 workflow list|run
├── menu.py               # Interactive menu loop with MenuState
└── stubs.py              # Disabled commands (segment, measure, threshold)
```

## Key Code Patterns

### 1. Click Group with invoke_without_command

```python
# main.py
@click.group(invoke_without_command=True)
@click.version_option(package_name="percell3")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """PerCell 3 — Single-Cell Microscopy Analysis."""
    if ctx.invoked_subcommand is None:
        from percell3.cli.menu import run_interactive_menu
        run_interactive_menu()
```

`invoke_without_command=True` lets the group execute when no subcommand is given, triggering the menu. The menu import is deferred to avoid loading it when subcommands are used directly.

### 2. Error Handler Decorator

```python
# utils.py
def error_handler(func: Callable[..., Any]) -> Callable[..., Any]:
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

Applied to all commands for consistent exit codes: 0=success, 1=user error, 2=internal error.

### 3. Click Context for Resource Sharing

```python
# query.py
@click.group()
@click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
@click.pass_context
@error_handler
def query(ctx: click.Context, experiment: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["store"] = open_experiment(experiment)

@query.result_callback()
@click.pass_context
def cleanup(ctx, *args, **kwargs):
    store = ctx.obj.get("store")
    if store:
        store.close()
```

Opens experiment once in the group, shares via `ctx.obj`, cleans up via `result_callback`.

### 4. Stub Command Factory

```python
# stubs.py
def _coming_soon(name: str, description: str) -> click.Command:
    @click.command(name, help=f"{description} (coming soon)")
    def stub() -> None:
        console.print(f"\n[yellow]{name.title()} is not yet available.[/yellow]")
        console.print("[dim]This feature is under development.[/dim]\n")
    return stub

segment = _coming_soon("segment", "Run cell segmentation")
```

Factory generates placeholder commands for unbuilt modules. `--help` shows them, but they don't perform work.

### 5. MenuState for Session Context

```python
# menu.py
class MenuState:
    def __init__(self) -> None:
        self.experiment_path: Path | None = None
        self.store: ExperimentStore | None = None
        self.running = True

    def set_experiment(self, path: Path) -> None:
        if self.store:
            self.store.close()
        self.store = ExperimentStore.open(path)
        self.experiment_path = path

    def require_experiment(self) -> ExperimentStore:
        if self.store is None:
            console.print("[yellow]No experiment selected.[/yellow]")
            _select_experiment(self)
            if self.store is None:
                raise _MenuCancel()
        return self.store
```

Holds the currently-open experiment across menu iterations. `require_experiment()` prompts selection if none is open.

## Code Review Findings

### Review Process

Six parallel review agents analyzed the module:

| Agent | Focus | Key Findings |
|-------|-------|--------------|
| kieran-python-reviewer | Type safety, Pythonic patterns | Type erasure, missing imports, raw tuple types |
| code-simplicity-reviewer | YAGNI, over-engineering | Menu duplication (404 LOC), dead code, premature formats |
| security-sentinel | Path traversal, info disclosure | Export overwrite risk, unfiltered exceptions |
| performance-oracle | Startup latency, memory | Eager imports (2-5s penalty), unbounded export memory |
| agent-native-reviewer | Scriptability, automation | Menu duplication, no --format on workflow list |
| learnings-researcher | Institutional knowledge | Referenced core/IO P1 fix patterns |

### P2 Findings (Important — Should Fix)

**016: Eager imports cause 2-5s startup latency**
- Every invocation loads numpy/dask/zarr/pandas via transitive imports in `main.py`
- `utils.py` imports `ExperimentStore` at module level, triggering the full core chain
- Even `percell3 --help` pays the full cost
- Fix: Lazy subcommand loading via custom `click.Group`, defer heavy imports to function bodies

**017: Menu reimplements business logic (404 LOC duplication)**
- `menu.py:296-353` copy-pastes table rendering from `query.py`
- `menu.py:179-258` reimplements import pipeline instead of calling `_run_import()`
- Menu's regions table already diverges (missing "Pixel Size" column)
- Dead imports (`channels`, `Context`) from abandoned refactor attempt
- Fix: Extract shared rendering functions, menu delegates to them

**018: Redundant error handling in create.py**
- Both `@error_handler` decorator AND inner `try/except ExperimentError` catch the same exception
- Inner catch runs first, making decorator's ExperimentError handler dead code
- Fix: Remove inner try/except, rely on decorator

**019: Type safety issues across module**
- `import_cmd.py`: `ScanResult` and `ExperimentStore` used in type hints but never imported
- `utils.py`: `error_handler` uses `Callable[..., Any]` erasing all type info (should use `ParamSpec`)
- `workflow.py`: `_PRESETS` is `dict[str, dict[str, Any]]` losing type info (should use dataclass)
- `menu.py`: `MenuItem` is raw 4-element tuple (CLAUDE.md says use dataclasses)

**020: Dead and unreachable code**
- `workflow.py:100-114`: Unreachable code after early returns (marked `pragma: no cover`)
- `menu.py:312-313`: Dead imports from abandoned refactor

**021: Export command missing UX features**
- No progress bar (import has one, export doesn't)
- No overwrite protection (silently overwrites existing files)
- No `--channels`/`--metrics` filtering (API supports it, CLI doesn't expose it)
- Inconsistent `expanduser()` handling between CLI and menu paths

### P3 Findings (Nice-to-Have)

**022: Query output format boilerplate repeated 3x**
- `if fmt == "table" / elif "csv" / elif "json"` copy-pasted in channels, regions, conditions

**023: Workflow list has no `--format` option**
- Only outputs Rich tables, not machine-readable JSON/CSV

**024: Bare `percell3` silently launches interactive menu**
- Scripts/agents that accidentally invoke bare command will hang on stdin

**025: Unfiltered exception messages**
- `error_handler` prints raw `str(e)` which may disclose file paths or internals

## Prevention Strategies

### 1. Lazy Import Pattern for CLI Modules

**Rule:** Never import scientific libraries (numpy, dask, zarr, pandas, tifffile) at module top-level in CLI files.

```python
# BAD — main.py top-level
from percell3.cli.create import create  # triggers percell3.core → numpy, dask, zarr

# GOOD — lazy loading
class LazyGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        # Import subcommand module only when that command is invoked
        ...
```

**Verification:** `time percell3 --help` should complete in <500ms.

### 2. Menu-as-Thin-Dispatcher Pattern

**Rule:** Menu handlers should be 1-3 lines that gather input and delegate to shared functions. Never reimplement business logic.

```python
# BAD — reimplements query rendering in menu
def _query_experiment(state):
    channels = state.store.get_channels()
    table = Table(...)  # Duplicated rendering
    for ch in channels:
        table.add_row(...)

# GOOD — delegates to shared function
def _query_experiment(state):
    store = state.require_experiment()
    choice = Prompt.ask("Query", choices=["channels", "regions", "conditions"])
    render_query_results(store, choice, fmt="table")  # Shared function
```

### 3. Decorator Awareness Checklist

Before adding error handling to any CLI command:
- [ ] Check if `@error_handler` is already applied
- [ ] If yes, do NOT add inner try/except for the same exception types
- [ ] If the decorator doesn't catch what you need, extend the decorator

### 4. CLI Module Review Checklist

- [ ] `percell3 --help` completes in <500ms (no heavy imports)
- [ ] No duplicated logic between menu handlers and Click commands
- [ ] All output commands support `--format table|csv|json`
- [ ] All user prompts gated behind interactive mode or `--yes` flag
- [ ] No dead imports or unreachable code (`pragma: no cover` = code smell)
- [ ] Exit codes consistent: 0=success, 1=user error, 2=internal error
- [ ] Type hints on all public functions, mypy-clean

## Related Documentation

- Core module P1 fixes: `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
- IO module P1 fixes: `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md`
- CLI spec: `docs/07-cli/spec.md`
- CLI conventions: `docs/07-cli/CLAUDE.md`
- Build plan: `docs/plans/2026-02-13-feat-cli-interactive-menu-plan.md`
- Review todos: `todos/016-pending-p2-lazy-imports-startup-latency.md` through `todos/025-pending-p3-sanitize-error-messages.md`
- ADR-005 (Click): `docs/tracking/decisions-log.md`

## Work Log

### 2026-02-13 — CLI Module Build and Review
- Built CLI module in 6 phases (Foundation → Import → Query/Export → Workflow → Menu → Stubs)
- 343 total tests passing (295 pre-existing + 48 new CLI tests)
- Ran 6-agent parallel code review
- Created 10 todo files (016-025) for findings
- Documented patterns and prevention strategies in this file
