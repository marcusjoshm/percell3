---
title: "CLI Dual-Mode Integration Review Fixes: Scanner Shadowing, Double-Scan, and Parity Gaps"
date: 2026-02-13
category: integration-issues
tags:
  - cli
  - import
  - code-quality
  - variable-shadowing
  - performance
  - test-coverage
  - type-safety
  - agent-parity
severity: medium
component: cli/import, io/scanner
problem_type: maintenance
issues_fixed:
  - scanner_variable_shadowing
  - double_scan_inefficiency
  - missing_auto_conditions_test
  - missing_files_cli_flag
  - bare_list_return_type
affected_files:
  - src/percell3/io/scanner.py
  - src/percell3/cli/import_cmd.py
  - src/percell3/cli/menu.py
  - tests/test_cli/test_import.py
  - tests/test_cli/conftest.py
related_todos:
  - "026"
  - "027"
  - "028"
  - "029"
  - "030"
---

# CLI Dual-Mode Integration Review Fixes

## Problem Symptom

After implementing a multi-condition import workflow with file picker support across PerCell 3's dual-mode CLI (interactive menu + Click commands), a multi-agent code review identified 5 issues at the CLI-IO module boundary:

1. **Variable shadowing**: `files` parameter silently clobbered by a local variable of a different type
2. **Double-scan**: Interactive import read every TIFF file's metadata twice (once for preview, once for import)
3. **Missing test coverage**: `--auto-conditions` CLI flag had zero CliRunner tests
4. **CLI/menu parity gap**: Interactive file picker had no `--files` CLI equivalent
5. **Bare type annotation**: `-> list` instead of `-> list[ChannelMapping]`

## Root Cause Analysis

### Variable Shadowing (scanner.py)

The `scan()` method accepted `files: list[Path] | None = None` as a parameter, then on line 61 declared `files: list[DiscoveredFile] = []` — a completely different type. Python allows this because the parameter is only read before line 61, but any future refactoring that references `files` after that line silently gets the wrong variable.

### Double-Scan (menu.py + import_cmd.py)

The interactive `_import_images()` handler scanned the TIFF directory for the preview table, then called `_run_import()` which scanned again internally. The `_run_import()` function was designed to be self-contained (always scanning its own data), with no mechanism to accept a pre-computed `ScanResult`. For directories with hundreds of TIFFs, this doubled I/O time.

### Missing CLI Test + Parity Gap

The `--auto-conditions` flag was added alongside the engine-level `detect_conditions()` function, which had thorough unit tests. But the CLI glue connecting the flag to the detection logic was untested. Similarly, the `source_files` plumbing existed in `_run_import()` (used by the menu's file picker) but was never exposed via a CLI `--files` option.

### Bare Type Annotation

`_parse_channel_maps()` was written with `-> list` during initial development when `ChannelMapping` wasn't yet in the `TYPE_CHECKING` imports block.

## Working Solution

### Fix 1: Rename Shadowed Variable

**File**: `src/percell3/io/scanner.py`

Renamed the local variable from `files` to `discovered` to eliminate the shadowing:

```python
# Before (shadowed)
files: list[DiscoveredFile] = []
files.append(df)
channels = sorted({f.tokens["channel"] for f in files if ...})

# After (clear)
discovered: list[DiscoveredFile] = []
discovered.append(df)
channels = sorted({f.tokens["channel"] for f in discovered if ...})
```

### Fix 2: Pass scan_result to Avoid Double-Scan

**Files**: `src/percell3/cli/import_cmd.py`, `src/percell3/cli/menu.py`

Added optional `scan_result` parameter to `_run_import()`:

```python
def _run_import(
    store, source, condition, channel_map, z_projection, yes,
    condition_map=None, region_names=None, source_files=None,
    scan_result: ScanResult | None = None,  # NEW
) -> None:
    if scan_result is None:
        scanner = FileScanner()
        scan_result = scanner.scan(Path(source), files=source_files)
    _show_preview(scan_result, source)
    ...
```

Menu passes its already-scanned result:

```python
_run_import(
    store, str(source), condition, channel_maps, z_method, yes=True,
    condition_map=condition_map, region_names=region_names,
    source_files=source_files, scan_result=scan_result,
)
```

### Fix 3: Add CLI Tests for --auto-conditions

**Files**: `tests/test_cli/test_import.py`, `tests/test_cli/conftest.py`

Added `multi_condition_tiff_dir` fixture and two tests:

```python
class TestAutoConditionsFlag:
    def test_auto_conditions_detects_multiple(self, ...):
        result = runner.invoke(cli, [..., "--auto-conditions", "--yes"])
        assert "Auto-detected 2 conditions" in result.output

    def test_auto_conditions_no_match(self, ...):
        result = runner.invoke(cli, [..., "--auto-conditions", "--yes"])
        assert "No conditions detected" in result.output
```

### Fix 4: Add --files CLI Flag

**File**: `src/percell3/cli/import_cmd.py`

```python
@click.option("--files", multiple=True, type=click.Path(exists=True),
              help="Specific TIFF files to import (instead of scanning directory).")
```

Converts to `list[Path]` and feeds into existing `source_files` plumbing.

### Fix 5: Fix Type Annotation

**File**: `src/percell3/cli/import_cmd.py`

```python
# Before
def _parse_channel_maps(maps: tuple[str, ...]) -> list:

# After
def _parse_channel_maps(maps: tuple[str, ...]) -> list[ChannelMapping]:
```

Added `ChannelMapping` to the `TYPE_CHECKING` imports block.

## Verification

All 373 tests passed after fixes (4 new tests added, 0 failures).

## Prevention Strategies

### For Variable Shadowing

- Never reuse parameter names for local variables, even with different types
- Use distinctive names that reflect role: `input_files` vs `discovered`
- Enable `pylint --enable=redefined-outer-name` in pre-commit

### For Duplicate Computation in Shared Pipelines

- Design shared functions with optional pre-computed result parameters
- Pattern: `if result is None: result = compute()` at the top of the function
- Document computation ownership in docstrings ("caller responsible for scanning")

### For CLI Test Coverage

- Rule: **No CLI flag without a CliRunner test**
- Test both success and fallback paths for conditional flags
- Audit: `grep "@click.option" src/percell3/cli/*.py` and cross-reference with test files

### For CLI/Menu Parity

- Map every interactive feature to its CLI equivalent before implementation
- Maintain a parity matrix in code review:
  ```
  import command:
    [x] Source path (positional)
    [x] Condition (--condition)
    [x] Channel renaming (--channel-map)
    [x] Z-projection (--z-projection)
    [x] Auto-detect conditions (--auto-conditions)
    [x] File selection (--files)
  ```

### Code Review Checklist for Dual-Mode CLI

- [ ] Every `@click.option` has a corresponding CliRunner test
- [ ] Interactive features have CLI equivalents
- [ ] Shared functions accept optional pre-computed results
- [ ] No variable shadowing between parameters and locals
- [ ] All container return types are parameterized (`list[T]`, not `list`)
- [ ] Expensive operations (file I/O, scanning) called exactly once per code path

## Cross-References

- Related: [CLI/IO Core Integration Bugs](cli-io-core-integration-bugs.md) — ImportEngine channel registration + Rich markup issues
- Related: [CLI Module Code Review Findings](../architecture-decisions/cli-module-code-review-findings.md) — earlier review findings (todos 016-025)
- Related: [IO Module P1 Fixes](../logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md) — Z-projection and input validation
- Todos: 026 (shadowing), 027 (double-scan), 028 (CLI test), 029 (--files flag), 030 (type annotation)
