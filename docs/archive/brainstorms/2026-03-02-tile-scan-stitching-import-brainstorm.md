---
title: "Tile Scan Stitching at Import"
date: 2026-03-02
status: decided
type: feat
---

# Tile Scan Stitching at Import

## What We're Building

A tile stitching feature integrated into the existing TIFF import flow. When imported files contain `_sXX` tokens (e.g., `_s00`, `_s01`, `_s02`), the scanner auto-detects them as tiles of a larger image. The user is prompted for grid layout parameters, and tiles are stitched into a single FOV before storage.

**Core behavior**: Detect tiles → prompt for grid config → stitch per-channel → store as single FOV.

## Why This Approach

Tile scans from microscopes produce individual TIFF files per tile per channel. Currently these would import as separate FOVs, which is incorrect — they represent one large field of view. Stitching at import keeps the experiment model clean (one FOV per physical location) and avoids downstream complexity in segmentation/measurement.

## Key Decisions

### 1. Token Detection
- New scanner token: `series` with pattern `_s(\d+)` — added to `TokenConfig`
- When `_sXX` tokens are found in scanned files, the import flow auto-detects tile mode
- The `_sXX` token is stripped from the FOV identity (tiles with the same base name belong to the same FOV)

### 2. Grid Parameters (User-Provided)
- **Grid size**: `A x B` where A = columns (X tiles) and B = rows (Y tiles)
- **Grid type**: How the microscope scanned — `row_by_row`, `column_by_column`, `snake_by_row`, `snake_by_column`
- **Order**: Starting corner and direction — `right_and_down`, `left_and_down`, `right_and_up`, `left_and_up`
- All three parameters are required when tiles are detected

### 3. Tile Assembly
- Non-overlapping tiles — simple grid concatenation (no blending or registration)
- Each tile is placed on the grid according to the (grid_type, order) mapping
- All tiles for a given FOV must have the same dimensions
- Stitching happens per-channel: for each channel, read all tiles, assemble into one large array, write as single FOV image
- Stitched image dimensions: `(A * tile_width, B * tile_height)`

### 4. Grid Type and Order Mapping

The combination of grid_type and order determines which tile index (`s00`, `s01`, ...) maps to which grid position `(row, col)`:

- **row_by_row + right_and_down**: `s00`→(0,0), `s01`→(0,1), `s02`→(0,2), `s03`→(1,0), ...
- **snake_by_row + right_and_down**: `s00`→(0,0), `s01`→(0,1), `s02`→(0,2), `s03`→(1,2), `s04`→(1,1), ... (alternating direction per row)
- **column_by_column + right_and_down**: `s00`→(0,0), `s01`→(1,0), `s02`→(2,0), `s03`→(0,1), ...
- And so on for all 8 combinations

### 5. Storage Model
- Stitched image stored as a single FOV — individual tiles are NOT kept
- FOV name derived from the base filename (after stripping `_sXX` token)
- Source file metadata records all tile files (comma-separated or first file)

### 6. Integration Points
- **Scanner** (`io/scanner.py`): Add `series` token to `TokenConfig`. Group files by (base_name, channel, z_slice) where base_name excludes the series token.
- **CLI prompt** (`cli/menu.py` or `cli/import_cmd.py`): When tiles detected, prompt for grid size, type, order before building ImportPlan.
- **Engine** (`io/engine.py`): New `_stitch_tiles()` step between file reading and `store.write_image()`. Assembles tile grid per channel.
- **Models** (`io/models.py`): Add `TileConfig` dataclass to `ImportPlan`.

### 7. Validation
- Number of detected tiles must equal `A * B`
- All tiles must have identical dimensions
- All tiles for a given FOV+channel must be present (no gaps)

## Resolved Questions

1. **File format?** Individual TIFFs only (not LIF multi-series).
2. **Tile overlap?** None — non-overlapping grid concatenation.
3. **Detection mode?** Auto-detect when `_sXX` tokens found, then prompt for parameters.
4. **Keep individual tiles?** No — single stitched FOV only.
5. **Which branch?** Add to existing `refactor/run-scoped-architecture` branch.
