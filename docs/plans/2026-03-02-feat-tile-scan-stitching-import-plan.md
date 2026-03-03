---
title: "Tile Scan Stitching at Import"
type: feat
date: 2026-03-02
branch: refactor/run-scoped-architecture
brainstorm: docs/brainstorms/2026-03-02-tile-scan-stitching-import-brainstorm.md
---

# Tile Scan Stitching at Import

## Overview

Add tile scan stitching to the existing TIFF import flow. When imported files contain
`_sXX` tokens (e.g., `_s00`, `_s01`), auto-detect them as tiles of a larger image.
Prompt the user for grid layout parameters, then stitch tiles into a single FOV before
storage. Non-overlapping grid concatenation only — no blending or registration.

## Problem Statement

Tile scans from microscopes produce individual TIFF files per tile per channel. Currently
these import as separate FOVs, which is incorrect — they represent one large field of view.
Stitching at import keeps the experiment model clean (one FOV per physical location) and
avoids downstream complexity in segmentation and measurement.

## Proposed Solution

Extend the import pipeline at four layers: scanner (token detection), models (TileConfig),
engine (grid assembly), and CLI (parameter prompts). The series token `_s(\d+)` is added
to `TokenConfig`, stripped from FOV identity during parsing. When tiles are detected, the
CLI prompts for grid size, type, and order. The engine assembles tiles per-channel into a
single 2D array and writes it as one FOV.

## Technical Approach

### Architecture

```
FileScanner._parse_tokens()     ← NEW: extract "series" token, strip from FOV
    ↓
ScanResult                      ← NEW: `tiles` field
    ↓
build_file_groups()             ← MODIFIED: group by base FOV (sans _sXX)
    ↓
CLI: detect tiles, prompt       ← NEW: grid parameter prompts
    ↓
ImportPlan                      ← NEW: `tile_config: TileConfig | None`
    ↓
ImportEngine.execute()          ← MODIFIED: call _stitch_tiles() before write_image()
    ↓
store.write_image(stitched)     ← unchanged
```

### File Changes

| File | Change |
|------|--------|
| `src/percell3/io/models.py` | Add `series` field to `TokenConfig`, add `TileConfig` dataclass, add `tile_config` to `ImportPlan` |
| `src/percell3/io/scanner.py` | Parse `series` token, strip from FOV derivation |
| `src/percell3/io/engine.py` | Add `_stitch_tiles()`, call it in `execute()` when `tile_config` is set |
| `src/percell3/io/serialization.py` | Serialize/deserialize `TileConfig` in YAML round-trip |
| `src/percell3/cli/import_cmd.py` | Add `--tile-grid`, `--tile-type`, `--tile-order` CLI options; detect tiles in `_run_import` |
| `src/percell3/cli/menu.py` | Add tile detection + grid parameter prompts in `_import_images` |
| `tests/test_io/test_scanner.py` | Tests for series token parsing |
| `tests/test_io/test_engine.py` | Tests for tile stitching logic |
| `tests/test_io/test_models.py` | Tests for TileConfig validation |
| `tests/test_cli/test_import_cmd.py` | CLI integration tests for tile options |

### Key Decisions (from SpecFlow analysis)

**Opt-out behavior:** When tiles are detected but the user declines stitching, import
each tile as an individual FOV (the `_sXX` token becomes part of the FOV name, not
stripped). This preserves all data without loss.

**Grid parameters are global:** One set of grid parameters applies to all tile groups
in a single import. Different grid sizes in the same import would require separate
import operations. This keeps the UI simple and matches the typical use case (one
microscope scan session = one grid layout).

**Z-stack + tiles:** Z-project each tile first, then stitch the projected 2D results.
This follows the existing architecture where `apply_z_transform` runs before
`store.write_image()`. The engine already handles Z-projection per-file — stitching
simply receives the projected 2D arrays.

**Tile index sorting:** Numeric (convert captured `\d+` to `int`), not lexicographic.
This ensures `_s10` sorts after `_s9`, not between `_s1` and `_s2`.

**Single-tile groups (1 tile detected):** Pass through as a normal FOV import without
prompting for grid parameters. A single `_s00` file is not a meaningful tile scan.

**Source file provenance:** Store the first tile's path in `source_file` (matches
current single-string schema). No schema change needed.

**Prompt placement in CLI flow:** After the file group table is displayed and before
channel mapping. This lets the user see what was detected before being asked about
grid parameters.

## Implementation Phases

### Phase 1: Models — TileConfig and TokenConfig update
`src/percell3/io/models.py`

- [x] Add `series: str | None = None` field to `TokenConfig` with default `r"_s(\d+)"`
- [x] Add `series` to `__post_init__` validation loop
- [x] Add `TileConfig` frozen dataclass:
  ```python
  @dataclass(frozen=True)
  class TileConfig:
      grid_rows: int      # B (number of rows)
      grid_cols: int      # A (number of columns)
      grid_type: str      # "row_by_row", "column_by_column", "snake_by_row", "snake_by_column"
      order: str          # "right_and_down", "left_and_down", "right_and_up", "left_and_up"

      def __post_init__(self) -> None:
          # Validate grid_type, order, and positive dimensions
  ```
- [x] Add `tile_config: TileConfig | None = None` to `ImportPlan`
- [x] Add `tiles: list[str]` to `ScanResult` (default empty list)

### Phase 2: Scanner — series token parsing
`src/percell3/io/scanner.py`

- [x] In `_parse_tokens()`: extract `series` token when `config.series` is not None
- [x] In `_parse_tokens()`: strip series pattern from FOV derivation (add to the `re.sub` loop at line 156)
- [x] In `scan()`: collect unique tile indices into `ScanResult.tiles`, sorted numerically
- [x] Tests: `tests/test_io/test_scanner.py`
  - [x] File `FOV1_s00_ch00.tif` → tokens `{"fov": "FOV1", "channel": "00", "series": "00"}`
  - [x] File `FOV1_s00_ch00.tif`, `FOV1_s01_ch00.tif` → same FOV token `"FOV1"`, tiles `["00", "01"]`
  - [x] Series token disabled (`series=None`) → `_s00` remains in FOV name
  - [x] No series token in filename → `series` key absent from tokens dict

### Phase 3: Engine — tile stitching logic
`src/percell3/io/engine.py`

- [x] Add `_build_tile_grid(tile_config: TileConfig) -> list[tuple[int, int]]` — returns list of `(row, col)` positions indexed by tile number
- [x] Add `_stitch_tiles(tile_images: list[np.ndarray], tile_config: TileConfig) -> np.ndarray` — assembles tiles into a single 2D array
- [x] In `execute()`: when `plan.tile_config` is not None:
  - [x] Group files by (fov_token, channel, z_slice) where fov_token excludes series
  - [x] For each fov_token: collect all tile files, sort by series index (numeric)
  - [x] Validate: tile count == grid_rows * grid_cols
  - [x] Validate: all tiles have identical dimensions
  - [x] Read each tile (applying Z-transform if needed), place into grid
  - [x] Use stitched dimensions for `store.add_fov(width=..., height=...)`
  - [x] Call `store.write_image(fov_id, ch_name, stitched_array)`
- [x] Memory guard: compute expected canvas size before allocating, warn if > 2 GB
- [x] Tests: `tests/test_io/test_engine.py`
  - [x] 2x2 grid of 32x32 tiles → 64x64 stitched image, correct pixel placement
  - [x] 3x2 grid with snake_by_row → verify tile ordering
  - [x] Tile count mismatch → ValueError
  - [x] Tile dimension mismatch → ValueError
  - [x] Multi-channel tile stitch → each channel stitched independently

#### Tile-to-Grid-Position Mapping

The mapping function `_build_tile_grid(config)` returns `positions[tile_index] = (row, col)`.

**row_by_row + right_and_down** (3x3 example):
```
s0→(0,0)  s1→(0,1)  s2→(0,2)
s3→(1,0)  s4→(1,1)  s5→(1,2)
s6→(2,0)  s7→(2,1)  s8→(2,2)
```

**row_by_row + left_and_down:**
```
s0→(0,2)  s1→(0,1)  s2→(0,0)
s3→(1,2)  s4→(1,1)  s5→(1,0)
s6→(2,2)  s7→(2,1)  s8→(2,0)
```

**row_by_row + right_and_up:**
```
s0→(2,0)  s1→(2,1)  s2→(2,2)
s3→(1,0)  s4→(1,1)  s5→(1,2)
s6→(0,0)  s7→(0,1)  s8→(0,2)
```

**row_by_row + left_and_up:**
```
s0→(2,2)  s1→(2,1)  s2→(2,0)
s3→(1,2)  s4→(1,1)  s5→(1,0)
s6→(0,2)  s7→(0,1)  s8→(0,0)
```

**snake_by_row + right_and_down** (alternating direction per row):
```
s0→(0,0)  s1→(0,1)  s2→(0,2)
s3→(1,2)  s4→(1,1)  s5→(1,0)   ← reversed
s6→(2,0)  s7→(2,1)  s8→(2,2)
```

**snake_by_row + left_and_down:**
```
s0→(0,2)  s1→(0,1)  s2→(0,0)
s3→(1,0)  s4→(1,1)  s5→(1,2)   ← reversed
s6→(2,2)  s7→(2,1)  s8→(2,0)
```

**snake_by_row + right_and_up:**
```
s0→(2,0)  s1→(2,1)  s2→(2,2)
s3→(1,2)  s4→(1,1)  s5→(1,0)   ← reversed
s6→(0,0)  s7→(0,1)  s8→(0,2)
```

**snake_by_row + left_and_up:**
```
s0→(2,2)  s1→(2,1)  s2→(2,0)
s3→(1,0)  s4→(1,1)  s5→(1,2)   ← reversed
s6→(0,2)  s7→(0,1)  s8→(0,0)
```

**column_by_column + right_and_down:**
```
s0→(0,0)  s3→(0,1)  s6→(0,2)
s1→(1,0)  s4→(1,1)  s7→(1,2)
s2→(2,0)  s5→(2,1)  s8→(2,2)
```

**column_by_column + left_and_down:**
```
s6→(0,0)  s3→(0,1)  s0→(0,2)
s7→(1,0)  s4→(1,1)  s1→(1,2)
s8→(2,0)  s5→(2,1)  s2→(2,2)
```

**column_by_column + right_and_up:**
```
s2→(0,0)  s5→(0,1)  s8→(0,2)
s1→(1,0)  s4→(1,1)  s7→(1,2)
s0→(2,0)  s3→(2,1)  s6→(2,2)
```

**column_by_column + left_and_up:**
```
s8→(0,0)  s5→(0,1)  s2→(0,2)
s7→(1,0)  s4→(1,1)  s1→(1,2)
s6→(2,0)  s3→(2,1)  s0→(2,2)
```

**snake_by_column + right_and_down:**
```
s0→(0,0)  s5→(0,1)  s6→(0,2)
s1→(1,0)  s4→(1,1)  s7→(1,2)
s2→(2,0)  s3→(2,1)  s8→(2,2)
```

**snake_by_column + left_and_down:**
```
s6→(0,0)  s3→(0,1)  s0→(0,2)
s7→(1,0)  s4→(1,1)  s1→(1,2)
s8→(2,0)  s5→(2,1)  s2→(2,2)
```

**snake_by_column + right_and_up:**
```
s2→(0,0)  s3→(0,1)  s8→(0,2)
s1→(1,0)  s4→(1,1)  s7→(1,2)
s0→(2,0)  s5→(2,1)  s6→(2,2)
```

**snake_by_column + left_and_up:**
```
s8→(0,0)  s5→(0,1)  s2→(0,2)
s7→(1,0)  s4→(1,1)  s1→(1,2)
s6→(2,0)  s3→(2,1)  s0→(2,2)
```

**Algorithm:** The mapping function uses two steps:
1. Generate sequential positions based on grid_type (row-major, column-major, snake variants)
2. Transform positions based on order (flip rows, flip columns, or both)

### Phase 4: Serialization — YAML round-trip for TileConfig
`src/percell3/io/serialization.py`

- [x] Add `tile_config` key to `plan_to_yaml()`: serialize as `{grid_rows, grid_cols, grid_type, order}` or `null`
- [x] Add `tile_config` parsing to `plan_from_yaml()`: construct `TileConfig` from dict or `None`
- [x] Tests: round-trip test — save plan with TileConfig, reload, verify fields match

### Phase 5: CLI — tile detection and prompts
`src/percell3/cli/import_cmd.py` and `src/percell3/cli/menu.py`

#### import_cmd.py

- [x] Add CLI options to `import_cmd`:
  - `--tile-grid TEXT` — grid size as "AxB" (e.g., "3x3")
  - `--tile-type` — choice of grid types
  - `--tile-order` — choice of orders
- [x] In `_run_import()`: when tile CLI options are provided, construct `TileConfig` and set on `ImportPlan`
- [x] CliRunner tests for `--tile-grid 2x2 --tile-type row_by_row --tile-order right_and_down`

#### menu.py — `_import_images()`

- [x] After `show_file_group_table(groups)` (line 926), detect tiles:
  ```python
  has_tiles = bool(scan_result.tiles)
  ```
- [x] If `has_tiles` and more than 1 tile detected:
  - Show tile detection summary: "Detected N tile indices across M file groups"
  - Prompt: "Stitch tiles into single FOV?" [Yes / No]
  - If Yes: prompt grid_cols (A), grid_rows (B), grid_type, order
  - Validate: total tiles per group == A * B (re-prompt on failure)
  - If No: proceed with normal import (tiles become individual FOVs)
- [x] Pass `tile_config` through to `_run_import()`

### Phase 6: Integration — wire everything together

- [ ] Pass `tile_config` from `_run_import()` into `ImportPlan` constructor
- [ ] Pass `scan_result` through to avoid double-scanning (already implemented)
- [ ] Verify end-to-end flow:
  - Create temp dir with tile TIFF files (2x2 grid, 2 channels)
  - Run interactive import flow with tile detection
  - Verify single stitched FOV written to store with correct dimensions
  - Verify pixel data is in correct grid positions

## Acceptance Criteria

- [ ] Files with `_sXX` tokens are auto-detected as tiles during scanning
- [ ] Tiles sharing the same base FOV name (after stripping `_sXX`) are grouped together
- [ ] User is prompted for grid parameters only when tiles are detected
- [ ] Declining stitching imports each tile as an individual FOV
- [ ] All 16 grid_type x order combinations produce correct tile placement
- [ ] Multi-channel tiles are stitched independently per channel
- [ ] Z-stack tiles are Z-projected per tile before stitching
- [ ] Validation rejects tile count != A*B with a clear error message
- [ ] Validation rejects tiles with mismatched dimensions
- [ ] Single-tile groups bypass stitching and import normally
- [ ] Stitched FOV has correct width = A * tile_width, height = B * tile_height
- [ ] TileConfig survives YAML round-trip (save and reload import plan)
- [ ] CLI `--tile-grid`, `--tile-type`, `--tile-order` options work in non-interactive mode
- [ ] All new code has test coverage

## References

- Brainstorm: `docs/brainstorms/2026-03-02-tile-scan-stitching-import-brainstorm.md`
- Scanner source: `src/percell3/io/scanner.py`
- Engine source: `src/percell3/io/engine.py`
- Models source: `src/percell3/io/models.py`
- CLI import: `src/percell3/cli/import_cmd.py`
- CLI menu: `src/percell3/cli/menu.py:889-1062`
- Existing learning: `docs/solutions/integration-issues/cli-io-dual-mode-review-fixes.md` — avoid double-scanning, pass `scan_result`
- Existing learning: `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md` — validate regex patterns, stream tile loading
