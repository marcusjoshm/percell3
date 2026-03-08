---
title: "Tile Scan Stitching Import: Implementation and Code Review"
category: architecture-decisions
tags:
  - tile-stitching
  - tiff-import
  - grid-layout
  - serialization
  - cli-integration
  - code-review
  - memory-safety
  - io-module
module: io, cli
date: 2026-03-02
severity: P1 + P2 (mixed)
status: implemented, code review complete (12 pending todos)
---

# Tile Scan Stitching Import: Implementation and Code Review

## Problem Statement

Tile scans from microscopes produce individual TIFF files per tile per channel
(e.g., `FOV1_s00_ch00.tif`, `FOV1_s01_ch00.tif`). Without stitching, these
import as separate FOVs, which is incorrect — they represent one large field of
view. This causes downstream problems in segmentation and measurement because
each "FOV" is only a fragment of the real image.

**Symptom:** Importing a 2x2 tile scan creates 4 FOVs instead of 1.

## Solution Overview

Extend the TIFF import pipeline to auto-detect `_sXX` tokens in filenames,
prompt the user for grid layout parameters, and stitch tiles into a single FOV
before storage. Non-overlapping grid concatenation only — no blending or
registration.

The implementation spans 6 phases across 10+ files:

1. **Models** — `TileConfig` dataclass, `series` token in `TokenConfig`
2. **Scanner** — series token parsing, strip from FOV derivation
3. **Engine** — `_build_tile_grid()` mapping, `_stitch_tiles()` assembly
4. **Serialization** — YAML round-trip for `TileConfig`, series=None preservation
5. **CLI** — `--tile-grid`, `--tile-type`, `--tile-order` options + interactive prompts
6. **Integration** — end-to-end wiring and tests

## Root Cause Analysis: Bugs Found

### Bug 1: series=None YAML Round-Trip Failure

**Root cause:** When `series=None` (tile detection disabled), the serializer
skipped writing the key. On deserialization, the missing key defaulted to
`r"_s(\d+)"` (the class default), silently re-enabling tile detection.

**Fix:** Always write the series token to YAML:
```python
# serialization.py — Always write series so that series=None round-trips correctly
# (distinguishes "disabled" from "key absent in old YAML")
data["token_config"]["series"] = plan.token_config.series
```

**Lesson:** When a `None` value has semantic meaning (disabled vs. absent),
always serialize it explicitly. Use `null` in YAML, not key omission.

### Bug 2: Missing `import pytest` in Test File

**Root cause:** Added `@pytest.fixture` decorator without adding the import.
Trivial but blocked the entire test class.

## Key Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Series as optional token pattern | Tile scans are optional; `series=None` disables detection. Follows same regex pattern as channel/timepoint/z_slice. |
| Numeric sorting of tile indices | `_s10` must sort after `_s9`, not between `_s1` and `_s2`. Parse as int for sorting. |
| 16 grid_type x order combinations | Covers all microscope acquisition patterns: row/column-major, left/right, top/bottom, snake variants. |
| Grid mapping via flip + traversal | Decompose into `flip_rows`/`flip_cols` booleans + traversal dispatch. Clean separation of concerns. |
| Pre-compute stitched FOV dimensions | Register correct `width`/`height` in `store.add_fov()` before writing data. |
| Always-write series in YAML | Distinguishes `series=None` (disabled) from key-absent (old YAML). Prevents silent data loss. |
| Memory guard at 2 GB | Prevents accidental allocation of enormous canvases from user typos. |
| Frozen dataclasses with `__post_init__` | `TileConfig` is immutable; invalid values caught at construction time. |
| Opt-out: import tiles as individual FOVs | When user declines stitching, `_sXX` becomes part of FOV name. No data loss. |
| Single-tile groups bypass stitching | A single `_s00` file is not a meaningful tile scan. |

## Code Review Findings (12 Todos)

### P1 Critical

**#152: `_MenuCancel` exception swallowed in `_prompt_tile_config()`**

`except (ValueError, _MenuCancel)` catches user cancel alongside validation
errors, trapping the user in an infinite loop. `_MenuCancel` is a control-flow
exception, not a validation exception — it must propagate.

```python
# BAD: Conflates control flow with validation
except (ValueError, _MenuCancel):
    console.print("[red]Enter an integer >= 1[/red]")
    continue  # User who pressed 'b' loops forever

# GOOD: Only catch validation errors; let navigation propagate
except ValueError:
    console.print("[red]Enter an integer >= 1[/red]")
    continue
# _MenuCancel propagates automatically
```

### P2 Important (6 findings)

| # | Finding | Impact |
|---|---------|--------|
| 153 | No upper bound on grid dimensions | OOM via huge grid values (e.g., 999999x999999) |
| 154 | All tiles loaded before stitching | 2x peak memory (tiles + canvas) |
| 155 | No `ndim` check on tile arrays | 3D arrays silently processed incorrectly |
| 156 | YAML tile_config values not type-checked | Deserialized values could be wrong type |
| 157 | Memory guard (2 GB) path untested | Safety code has no test coverage |
| 158 | Files without series token silently become tile 0 | Could mix non-tile files into tile grid |

### P3 Nice-to-Have (5 findings)

| # | Finding |
|---|---------|
| 159 | Use `Literal` types for `grid_type` and `order` instead of `str` |
| 160 | Deduplicate z-map grouping logic between `execute()` and `_read_and_stitch_tiles()` |
| 161 | Re-export `stitch_tiles` and `build_tile_grid` from `io/__init__.py` |
| 162 | CLI missing tile count validation warning (only in menu) |
| 163 | CLI doesn't reject nonpositive grid dimensions early |

## Prevention Strategies

### 1. Separate Exception Hierarchies by Semantic Type

Never mix control-flow exceptions (`_MenuCancel`, `_MenuHome`) with validation
exceptions (`ValueError`) in the same `except` clause. Control-flow exceptions
should always propagate to their handler.

```python
# Pattern: prompt with validation, allow navigation cancellation
def prompt_with_validation(prompt_text, validator_fn):
    while True:
        try:
            raw = menu_prompt(prompt_text)  # May raise _MenuCancel
            return validator_fn(raw)         # May raise ValueError
        except ValueError as e:
            console.print(f"[red]Invalid: {e}[/red]")
            continue
        # _MenuCancel propagates automatically
```

### 2. Validate Input at Every Layer

```
User Input (CLI/Menu)
    -> Type coercion & format validation
    -> Range validation (min/max bounds)
    -> Domain validation (semantic sense)
    -> Business logic
```

Add upper bounds on grid dimensions (e.g., max 256). Validate in both CLI
`_parse_tile_options()` and menu `_prompt_tile_config()`.

### 3. Memory Safety in Image Processing

- Estimate memory before allocating: `height * width * dtype.itemsize`
- Guard threshold at 2 GB (or configurable)
- Consider streaming: allocate canvas first, then load and place tiles one at a
  time instead of collecting all into a list
- Always test the guard path

### 4. Always Validate Array Dimensions

```python
for i, tile in enumerate(tile_images):
    if tile.ndim != 2:
        raise ValueError(f"Tile {i} has ndim={tile.ndim}, expected 2D")
```

### 5. Type-Safe Deserialization

When deserializing from YAML/JSON, explicitly coerce and validate types:
```python
grid_rows = int(data["grid_rows"])   # Coerce
grid_type = str(data["grid_type"])   # Coerce
```

Consider `Literal` types for compile-time checking of enumerated values.

## Testing Strategy

### Coverage Matrix

| Layer | What's Tested |
|-------|---------------|
| Scanner | Series token extraction, numeric sorting, FOV stripping, series=None passthrough |
| Engine | All 16 grid/order combinations, 2x2 and 3x2 grids, snake patterns, multi-channel, tile count/dimension mismatch errors |
| Serialization | TileConfig round-trip, series=None round-trip, old YAML backward compat |
| CLI | `--tile-grid` parsing, validation errors, help text, stitched FOV dimensions |
| Integration | 2x2 grid + 2 channels end-to-end, pixel placement verification |

### Key Test Patterns

- **Parametrized grid tests:** All 16 `grid_type x order` combinations verified for unique positions
- **Ground truth pixel tests:** Known tile values placed in expected grid positions
- **Error path tests:** Tile count mismatch, dimension mismatch, invalid format
- **Round-trip tests:** Serialize ImportPlan with TileConfig, reload, verify all fields

## Affected Files

| File | Changes |
|------|---------|
| `src/percell3/io/models.py` | `TileConfig` dataclass, `series` in `TokenConfig`, `tile_config` in `ImportPlan`, `tiles` in `ScanResult` |
| `src/percell3/io/scanner.py` | Series token extraction, strip from FOV derivation, numeric tile sorting |
| `src/percell3/io/engine.py` | `_build_tile_grid()`, `_stitch_tiles()`, `_read_and_stitch_tiles()`, memory guard, tile grouping in `execute()` |
| `src/percell3/io/serialization.py` | TileConfig YAML round-trip, always-write series token |
| `src/percell3/cli/import_cmd.py` | `--tile-grid`, `--tile-type`, `--tile-order` options, `_parse_tile_options()`, tile info in preview |
| `src/percell3/cli/menu.py` | `_prompt_tile_config()`, tile detection after file group table, pass-through to `_run_import()` |
| `tests/test_io/test_scanner.py` | Series token parsing tests |
| `tests/test_io/test_engine.py` | Grid mapping, stitching, integration tests |
| `tests/test_io/test_serialization.py` | TileConfig and series token round-trip tests |
| `tests/test_cli/test_import.py` | CLI tile option tests, stitched dimension verification |

## Cross-References

### Directly Related
- Brainstorm: `docs/brainstorms/2026-03-02-tile-scan-stitching-import-brainstorm.md`
- Plan: `docs/plans/2026-03-02-feat-tile-scan-stitching-import-plan.md`

### Pattern Sources
- `docs/solutions/integration-issues/cli-io-dual-mode-review-fixes.md` — scan_result pass-through pattern (avoid double-scanning)
- `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md` — TokenConfig regex validation, memory guard rationale
- `docs/solutions/integration-issues/cli-io-core-integration-bugs.md` — default channel registration guard, Rich markup escaping

### Architectural Context
- `docs/solutions/design-gaps/import-flow-table-first-ui-and-heuristics.md` — prompt placement rules in `_import_images()`
- `docs/solutions/architecture-decisions/cli-module-code-review-findings.md` — dual-mode parity rule
- `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md` — current ExperimentStore API

### Supersedes
- `docs/brainstorms/2026-02-12-io-module-design-brainstorm.md` Decision 8 ("no tile stitching") — this feature reverses that decision
