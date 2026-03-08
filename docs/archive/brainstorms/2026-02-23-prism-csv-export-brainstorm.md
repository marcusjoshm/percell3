# Brainstorm: Prism-Friendly CSV Export

**Date:** 2026-02-23
**Status:** Draft

## What We're Building

A new CSV export mode that produces GraphPad Prism-ready files. Instead of the current wide-format CSV (one row per cell, all metrics as columns), the Prism export creates a **directory of small, focused CSV files** organized by channel and metric.

Each file has one column per condition+bio-rep combination (e.g., `HS_N1`, `HS_N2`, `Control_N1`), with rows being individual cells. This allows the user to open a file, select an entire column, copy, and paste directly into a Prism column table.

### Output Structure

```
export_prism/
  G3BP1/
    mean_intensity.csv
    median_intensity.csv
    total_intensity.csv
    particle_count.csv        # particle summary per cell
    mean_particle_size.csv    # particle summary per cell
  DAPI/
    mean_intensity.csv
    median_intensity.csv
    total_intensity.csv
  UFD1L/
    ...
```

### File Format (e.g., `G3BP1/mean_intensity.csv`)

```csv
HS_N1,HS_N2,Control_N1,Control_N2
123.4,145.2,98.1,88.3
118.7,139.8,102.4,91.2
...,...,...,...
```

- Columns = `{condition}_{biorep}` (e.g., `HS_N1`)
- Rows = individual cell values from **all FOVs pooled** within that condition+biorep (ragged columns OK since cell counts differ)
- FOVs are technical replicates and get combined; only bio-reps stay separate
- Empty cells where shorter columns run out

### Particle Data

Particle summary metrics (particles per cell, mean particle size, etc.) get their own CSV files within the channel directory, separate from cell-level intensity metrics. Each follows the same column-per-condition format.

## Why This Approach

1. **Copy-paste workflow**: Open file, select entire column, Ctrl+C, paste into Prism. No scrolling, no hunting for columns in a wide table.
2. **One file per metric per channel**: Each file is small and focused. Easy to find what you need.
3. **Ragged columns are fine**: Prism handles columns of different lengths natively. No need to pad with zeros or NaN.
4. **Subdirectory keeps things organized**: Channel directories group related metrics together.
5. **Separate particle CSVs**: Keeps cell-level and particle-summary data cleanly separated.

## Key Decisions

1. **Column layout**: Column per condition with sub-columns per bio-rep (`condition_biorep`)
2. **FOV pooling**: All FOVs within the same condition+bio-rep are pooled (FOVs are technical replicates). Only bio-reps are kept separate as distinct columns.
3. **File organization**: One CSV per channel per metric, in a subdirectory tree
4. **Column headers**: `{condition}_{biorep}` format (e.g., `HS_N1`)
5. **Particle data**: Separate particle summary CSV per channel (not mixed with intensity metrics)
6. **Ragged columns**: Allowed. Shorter columns padded with empty cells.
7. **Column ordering**: Alphabetical by condition, then bio-rep within each condition (e.g., `Control_N1, Control_N2, HS_N1, HS_N2`).
8. **No index file**: Just the metric CSVs in channel subdirectories. Keep it simple.

## Open Questions

_None remaining - all key decisions resolved._

## Existing Export Code

The current export system lives in:
- `src/percell3/core/experiment_store.py`: `export_csv()` (wide format), `export_particles_csv()`, `get_measurement_pivot()`
- `src/percell3/cli/menu.py`: `_export_csv()` handler (interactive menu)
- CLI: `percell3 export` command

The new Prism export should be a separate command/option (e.g., `--format prism` or a new `export-prism` subcommand) that coexists with the current wide-format export.
