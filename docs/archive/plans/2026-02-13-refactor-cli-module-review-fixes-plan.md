---
title: "CLI Module: Address P2/P3 Code Review Findings"
type: refactor
date: 2026-02-13
---

# CLI Module: Address P2/P3 Code Review Findings

## Overview

The CLI module (percell3.cli) is functionally complete with dual-mode interface (interactive menu + Click subcommands), 48 tests passing, and all 343 project tests green. A 6-agent parallel code review identified 10 findings (6 P2, 4 P3) covering startup performance, logic duplication, type safety, dead code, UX gaps, and agent-hostile patterns. This plan addresses all findings in four phases ordered by dependency and impact.

## Problem Statement

The findings fall into four categories:

1. **Startup performance** (P2-016): Every CLI invocation loads numpy/dask/zarr/pandas via transitive imports in `utils.py`, adding 2-5s latency even for `percell3 --help`. This makes the CLI unusable for quick checks and hostile to scripting.

2. **Code duplication and dead code** (P2-017, 018, 020, P3-022): Menu reimplements business logic (404 LOC), create.py has redundant error handling, workflow.py has unreachable code, and query format dispatch is copy-pasted 3x.

3. **Type safety** (P2-019): Missing imports, erased decorator types, raw tuples instead of dataclasses, and untyped preset dicts violate CLAUDE.md conventions.

4. **UX and agent parity** (P2-021, P3-023, 024, 025): Export lacks progress/overwrite protection, workflow list has no machine-readable output, bare `percell3` hangs non-interactive sessions, and error messages leak internal details.

## Proposed Solution

Fix all 6 P2 findings (required) and all 4 P3 findings (recommended). Group into four phases to minimize test churn and ensure each phase produces a testable, committable unit.

## References

- Solution doc: `docs/solutions/architecture-decisions/cli-module-code-review-findings.md`
- Todo files: `todos/016-pending-p2-*.md` through `todos/025-pending-p3-*.md`
- Core P1 fix patterns: `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
- IO P1 fix patterns: `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md`
- CLI spec: `docs/07-cli/spec.md`
- CLI conventions: `docs/07-cli/CLAUDE.md`

---

## Implementation Phases

### Phase A: Lazy Imports — Startup Performance (P2-016)

**Goal:** `percell3 --help` completes in <500ms instead of 2-5s.

**Root cause:** `utils.py` imports `ExperimentStore` at module level, which triggers `percell3.core.__init__` → numpy, dask, zarr, pandas. Every subcommand module imports from `utils.py`, so all invocations pay the full cost.

**Key insight:** `percell3.core.exceptions` is lightweight (57 lines, no heavy imports). Exception classes can be imported at module level safely; only `ExperimentStore` needs deferral.

#### 1. Defer ExperimentStore import in utils.py (P2-016)
**File:** `src/percell3/cli/utils.py:7-8`

- [x] Replace `from percell3.core import ExperimentStore, ExperimentError, ExperimentNotFoundError` with:
  ```python
  from percell3.core.exceptions import ExperimentError, ExperimentNotFoundError
  ```
- [x] Move `ExperimentStore` import inside `open_experiment()` function body:
  ```python
  def open_experiment(path: str) -> "ExperimentStore":
      from percell3.core import ExperimentStore
      try:
          return ExperimentStore.open(Path(path))
      ...
  ```
- [x] Add `TYPE_CHECKING` guard for type hints that reference `ExperimentStore`:
  ```python
  from __future__ import annotations
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from percell3.core import ExperimentStore
  ```

#### 2. Defer subcommand imports in main.py (P2-016)
**File:** `src/percell3/cli/main.py:1-14`

- [x] Remove top-level imports of all subcommand modules (create, import_cmd, query, export, workflow, stubs)
- [x] Use deferred `cli.add_command()` pattern — import subcommand modules inside a function or use a lazy group:
  ```python
  import click

  @click.group(invoke_without_command=True)
  @click.version_option(package_name="percell3")
  @click.pass_context
  def cli(ctx: click.Context) -> None:
      """PerCell 3 — Single-Cell Microscopy Analysis."""
      if ctx.invoked_subcommand is None:
          from percell3.cli.menu import run_interactive_menu
          run_interactive_menu()

  def _register_commands() -> None:
      from percell3.cli.create import create
      from percell3.cli.import_cmd import import_cmd
      from percell3.cli.query import query
      from percell3.cli.export import export
      from percell3.cli.workflow import workflow
      from percell3.cli.stubs import segment, measure, threshold
      cli.add_command(create)
      cli.add_command(import_cmd)
      cli.add_command(export)
      cli.add_command(query)
      cli.add_command(workflow)
      cli.add_command(segment)
      cli.add_command(measure)
      cli.add_command(threshold)

  _register_commands()
  ```
  Note: This still imports at module load of `main.py`, but the key win is in **utils.py** deferring `ExperimentStore`. If startup is still slow, switch to a `LazyGroup` pattern where `get_command()` imports on demand.

#### 3. Defer heavy imports in subcommand files
**Files:** `src/percell3/cli/create.py`, `import_cmd.py`, `query.py`, `export.py`

- [x] In each subcommand file, move any `from percell3.core import ExperimentStore` to function bodies or behind `TYPE_CHECKING`
- [x] Use `from percell3.core.exceptions import ...` for exception classes (lightweight)
- [x] Ensure `import_cmd.py` defers `from percell3.io import ...` imports to `_run_import()` body

#### 4. Add startup latency test
**File:** `tests/test_cli/test_startup.py` (new)

- [x] Add test that runs `percell3 --help` via subprocess and asserts completion in <2s (generous bound for CI)
- [x] Add test that imports `percell3.cli.main` and checks `sys.modules` does NOT contain `numpy` or `dask`

**Acceptance criteria:**
- [x] `percell3 --help` completes in <500ms on dev machine
- [x] All 48 existing CLI tests pass
- [x] No behavioral changes to any command

---

### Phase B: Quick Fixes — Error Handling, Dead Code, Type Safety (P2-018, 020, 019)

**Goal:** Clean up redundant code, remove dead code, fix type annotations.

#### 1. Remove redundant error handling in create.py (P2-018)
**File:** `src/percell3/cli/create.py:14-21`

- [x] Remove inner `try/except ExperimentError` block — `@error_handler` already catches this
- [x] Resulting code:
  ```python
  @click.command()
  @click.argument("path", type=click.Path())
  @click.option("--name", "-n", default=None, help="Experiment name.")
  @click.option("--description", "-d", default=None, help="Experiment description.")
  @error_handler
  def create(path: str, name: str | None, description: str | None) -> None:
      """Create a new .percell experiment directory."""
      exp_path = Path(path)
      store = ExperimentStore.create(
          exp_path, name=name or "", description=description or ""
      )
      store.close()
      console.print(f"[green]Created experiment at {exp_path}[/green]")
  ```
- [x] Verify test_create.py still passes (error paths now go through decorator)

#### 2. Remove dead/unreachable code (P2-020)
**File:** `src/percell3/cli/workflow.py:100-114`

- [x] Remove unreachable code block after early returns
- [x] Remove associated `pragma: no cover` comments
- [x] Verify workflow tests still pass

**File:** `src/percell3/cli/menu.py:312-313`

- [x] Remove dead imports (`channels`, `Context`) from abandoned refactor
- [x] Verify menu tests still pass

#### 3. Fix type safety issues (P2-019)

**File:** `src/percell3/cli/utils.py` — Fix error_handler signature

- [x] Replace `Callable[..., Any]` with `ParamSpec`/`TypeVar` for type preservation:
  ```python
  from typing import ParamSpec, TypeVar
  P = ParamSpec("P")
  R = TypeVar("R")

  def error_handler(func: Callable[P, R]) -> Callable[P, R]:
      @functools.wraps(func)
      def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
          ...
      return wrapper
  ```

**File:** `src/percell3/cli/import_cmd.py` — Add missing type imports

- [x] Add `TYPE_CHECKING` guard for `ScanResult` and `ExperimentStore`:
  ```python
  from __future__ import annotations
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from percell3.core import ExperimentStore
      from percell3.io import ScanResult
  ```

**File:** `src/percell3/cli/workflow.py` — Type the presets dict

- [x] Replace `_PRESETS: dict[str, dict[str, Any]]` with a frozen dataclass:
  ```python
  from dataclasses import dataclass

  @dataclass(frozen=True)
  class WorkflowPreset:
      description: str
      steps: list[str]

  _PRESETS: dict[str, WorkflowPreset] = {
      "basic-import": WorkflowPreset(
          description="Import and preview",
          steps=["import", "query"],
      ),
      ...
  }
  ```

**File:** `src/percell3/cli/menu.py` — Replace raw tuple with dataclass

- [x] Replace `MenuItem = tuple[str, str, Callable[...] | None, bool]` with:
  ```python
  @dataclass(frozen=True)
  class MenuItem:
      key: str
      label: str
      handler: Callable[["MenuState"], None] | None
      needs_experiment: bool
  ```
- [x] Update all `MenuItem` construction sites to use keyword arguments

**Acceptance criteria:**
- [x] No inner try/except duplicating `@error_handler` in create.py
- [x] No `pragma: no cover` on reachable code paths
- [x] No dead imports
- [x] `error_handler` preserves wrapped function's type signature
- [x] All type hints use proper imports (no string-only forward refs without TYPE_CHECKING)
- [x] `_PRESETS` uses frozen dataclass, `MenuItem` uses frozen dataclass
- [x] All 48 CLI tests pass

---

### Phase C: DRY and Feature Additions (P3-022, P2-021, P3-023)

**Goal:** Extract shared helpers, add missing UX features.

#### 1. Extract query output format helper (P3-022)
**File:** `src/percell3/cli/query.py`

- [x] Create `_format_output(rows: list[dict], columns: list[str], fmt: str, title: str) -> None` helper in query.py:
  ```python
  def _format_output(
      rows: list[dict[str, Any]],
      columns: list[str],
      fmt: str,
      title: str,
  ) -> None:
      if fmt == "table":
          table = Table(title=title)
          for col in columns:
              table.add_column(col)
          for row in rows:
              table.add_row(*(str(row[c]) for c in columns))
          console.print(table)
      elif fmt == "csv":
          writer = csv.writer(sys.stdout)
          writer.writerow(columns)
          for row in rows:
              writer.writerow([row[c] for c in columns])
      elif fmt == "json":
          console.print_json(json.dumps(rows, indent=2))
  ```
- [x] Refactor `channels`, `regions`, `conditions` subcommands to build `rows` as list[dict] and call `_format_output()`
- [x] Verify all three query subcommands produce identical output to current implementation
- [x] All query tests pass

#### 2. Enhance export command UX (P2-021)
**File:** `src/percell3/cli/export.py`

- [x] Add `--overwrite / --no-overwrite` flag (default: prompt if file exists, or error in non-interactive)
- [x] Add progress spinner using `make_progress()` from utils.py
- [x] Add `expanduser()` to output path for consistency with menu
- [x] Add `--channels` option to filter exported channels
- [x] Add `--metrics` option to filter exported metrics
- [x] Update tests to cover overwrite protection and filtering

#### 3. Add --format to workflow list (P3-023)
**File:** `src/percell3/cli/workflow.py`

- [x] Add `--format` option (`table|json|csv`) to `workflow_list` command, default `table`
- [x] Use the `_format_output()` pattern (or import the helper if extracted to utils)
- [x] Add tests for JSON and CSV output of workflow list

**Acceptance criteria:**
- [x] Query format dispatch logic exists in exactly one place
- [x] Export command has overwrite protection and progress feedback
- [x] `percell3 workflow list --format json` outputs valid JSON
- [x] All tests pass

---

### Phase D: Menu Deduplication and Behavioral Fixes (P2-017, P3-024, P3-025)

**Goal:** Menu delegates to shared functions, non-TTY safety, sanitized errors.

**Note:** This phase depends on Phase C's `_format_output()` helper.

#### 1. Refactor menu to delegate to shared functions (P2-017)
**File:** `src/percell3/cli/menu.py`

- [x] Extract shared rendering functions from `query.py` into a reusable location (either `query.py` public functions or `utils.py`)
- [x] Replace menu's query rendering (lines ~296-353) with calls to shared functions
- [x] Replace menu's import pipeline (lines ~179-258) with a call to `_run_import()` from `import_cmd.py`
- [x] Verify menu's regions table now includes "Pixel Size" column (currently diverged)
- [x] Net reduction of ~100-150 LOC from menu.py
- [x] All menu tests pass

#### 2. Add non-TTY safety to bare invocation (P3-024)
**File:** `src/percell3/cli/main.py`

- [x] Add `sys.stdin.isatty()` check before launching interactive menu:
  ```python
  if ctx.invoked_subcommand is None:
      import sys
      if sys.stdin.isatty():
          from percell3.cli.menu import run_interactive_menu
          run_interactive_menu()
      else:
          click.echo(ctx.get_help())
  ```
- [x] Add test: invoke CLI with no args in non-TTY mode → shows help text, exits 0
- [x] Add test: confirm menu still launches in TTY mode (mock `isatty`)

#### 3. Sanitize error messages (P3-025)
**File:** `src/percell3/cli/utils.py`

- [x] Add `--verbose` flag to the CLI group (stored in `ctx.obj`)
- [x] Modify `error_handler` to show sanitized message by default, full traceback with `--verbose`:
  ```python
  except Exception as e:
      if verbose:
          import traceback
          console.print(f"[red]Internal error:[/red] {e}")
          console.print(traceback.format_exc())
      else:
          console.print("[red]Internal error.[/red] Run with --verbose for details.")
      raise SystemExit(2)
  ```
- [x] Apply same pattern to menu error handling
- [x] Add tests for both verbose and non-verbose error output

**Acceptance criteria:**
- [x] Menu handlers are thin dispatchers (1-5 lines gathering input + delegation)
- [x] No duplicated rendering logic between menu and commands
- [x] `percell3` with no args on non-TTY shows help and exits
- [x] Error messages don't expose file paths or internals by default
- [x] `--verbose` flag shows full tracebacks for debugging
- [x] All tests pass

---

## Testing Strategy

Each phase must maintain green tests before proceeding to the next:

| Phase | New Tests | Existing Tests |
|-------|-----------|----------------|
| A: Lazy imports | `test_startup.py` (2 tests) | All 48 CLI tests |
| B: Quick fixes | Updated error path tests | All 48 CLI tests |
| C: DRY/features | Export UX tests, workflow format tests | All query tests (output parity) |
| D: Menu/behavior | TTY/non-TTY tests, verbose tests | All menu tests |

**Final validation:** All 343 project tests pass after all four phases.

## Risk Analysis

| Risk | Mitigation |
|------|------------|
| Lazy imports break tests that mock at module level | Update mock targets to match new import locations |
| Menu refactor breaks interactive flows | Menu tests exercise all menu items; manual smoke test |
| `_format_output` changes subtly alter output | Snapshot existing output, diff after refactor |
| `--verbose` flag conflicts with subcommand options | Use Click context inheritance, not per-command flags |

## Ordering Rationale

1. **Phase A first** because lazy imports change import paths that other phases reference
2. **Phase B second** because type fixes and dead code cleanup make Phase C/D diffs cleaner
3. **Phase C before D** because Phase D's menu refactor reuses Phase C's shared helpers
4. **Each phase is independently committable** — if any phase is deferred, earlier phases still improve the module
