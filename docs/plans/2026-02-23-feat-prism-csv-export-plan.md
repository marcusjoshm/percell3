---
title: "feat: Add Prism-friendly CSV export"
type: feat
date: 2026-02-23
---

# feat: Add Prism-friendly CSV export

## Overview

Add a new export mode that produces GraphPad Prism-ready CSV files. Instead of the current wide-format CSV (one row per cell, all metrics as columns), the Prism export creates a **directory of small, focused CSV files** organized by channel and metric. Each file has one column per `{condition}_{biorep}` combination with rows being individual cell values. FOVs from the same condition+bio-rep are pooled as technical replicates.

**Brainstorm:** `docs/brainstorms/2026-02-23-prism-csv-export-brainstorm.md`

## Problem Statement / Motivation

The current `export_csv()` produces a single wide-format CSV with one row per cell and all `{channel}_{metric}` combinations as columns. To use this data in GraphPad Prism, the user must:

1. Open the wide CSV in Excel/Numbers
2. For each metric they want to plot, manually find the right columns
3. Copy cells from one condition at a time, filtering by condition and bio-rep
4. Paste into a Prism column table

This is tedious, error-prone, and must be repeated for every metric. The Prism export eliminates all manual data wrangling: open a file, select an entire column, copy, paste into Prism.

## Proposed Solution

### Output Structure

```
<output_dir>/
  G3BP1/
    mean_intensity.csv
    median_intensity.csv
    total_intensity.csv
    particle_count.csv              # particle summary metric
    mean_particle_area.csv          # particle summary metric
    ...
  DAPI/
    mean_intensity.csv
    median_intensity.csv
    ...
```

### File Format (e.g., `G3BP1/mean_intensity.csv`)

```csv
Control_N1,Control_N2,HS_N1,HS_N2
98.1,88.3,123.4,145.2
102.4,91.2,118.7,139.8
...,...,...,...
95.0,,115.3,
```

- **Columns** = `{condition}_{biorep}`, alphabetically sorted
- **Rows** = individual cell values from all FOVs pooled within that (condition, bio_rep)
- **Ragged columns** = shorter columns padded with empty strings (trailing commas)
- **No row identifiers** (no cell_id column) — pure data for Prism

### Key Design Decisions

1. **FOV pooling**: All FOVs sharing the same (condition, bio_rep) are concatenated. FOVs are technical replicates.
2. **Only valid cells**: Cells with `is_valid=False` (excluded during QC) are omitted.
3. **Scope handling**: Default to `whole_cell` scope only. A `--scope` CLI option allows exporting `mask_inside` or `mask_outside` instead. When a non-default scope is exported, filenames get a suffix: `mean_intensity_mask_inside.csv`.
4. **Particle metrics**: All 8 `PARTICLE_SUMMARY_METRICS` from `percell3.measure.particle_analyzer` are classified as particle metrics and routed to separate files within the same channel directory. They follow the same column layout.
5. **Separate `export-prism` command**: Different from `export` because the argument is a directory path (not a file path) and the output is many files (not one).
6. **No index file**: Keep it simple.
7. **Column ordering**: Alphabetical by condition name, then alphabetical by bio_rep name within each condition.

## Technical Approach

### Phase 1: Core Export Method on ExperimentStore

Add `export_prism_csv()` to `src/percell3/core/experiment_store.py`.

**Algorithm:**
1. Query all measured channels (or filter by `channels` parameter)
2. Query all measured metrics (or filter by `metrics` parameter)
3. Classify metrics into regular vs. particle summary using `PARTICLE_SUMMARY_METRICS`
4. For each (channel, metric) pair:
   a. Query measurements for this channel+metric with scope filter, including cell info
   b. Group cells by `(condition_name, bio_rep_name)` — this pools FOVs
   c. Sort groups alphabetically by condition, then bio_rep
   d. Build column name: `{condition}_{biorep}`
   e. Create ragged DataFrame: each column = values from that group
   f. Write to `{output_dir}/{channel}/{metric}.csv`
5. Create channel subdirectories as needed

```python
# src/percell3/core/experiment_store.py

def export_prism_csv(
    self,
    output_dir: Path,
    channels: list[str] | None = None,
    metrics: list[str] | None = None,
    scope: str = "whole_cell",
) -> dict[str, int]:
    """Export measurements in Prism-friendly format.

    Creates a directory tree with one CSV per (channel, metric).
    Each CSV has columns = {condition}_{biorep} and rows = cell values.

    Args:
        output_dir: Root output directory (will be created).
        channels: Optional channel filter.
        metrics: Optional metric filter.
        scope: Measurement scope ('whole_cell', 'mask_inside', 'mask_outside').

    Returns:
        Dict with 'files_written' and 'channels_exported' counts.
    """
```

**Data flow — do NOT use `get_measurement_pivot()`** because it pivots all channels x metrics into a single wide DataFrame. Instead, query measurements per-channel per-metric using `get_measurements()` directly, which returns the long-form DataFrame. Then group by `(condition_name, bio_rep_name)` and build ragged columns.

Checklist:
- [x] Add `export_prism_csv()` method to `ExperimentStore`
- [x] Import `PARTICLE_SUMMARY_METRICS` from `percell3.measure.particle_analyzer`
- [x] Handle empty experiments (no measurements) gracefully — print warning, create no files
- [x] Handle channels with no measurements — skip silently
- [x] Create output directory and channel subdirectories
- [x] Write each CSV with `csv.writer` (no pandas dependency for writing)
- [x] Scope suffix: if scope != `whole_cell`, append `_{scope}` to metric filename
- [x] Return summary dict for CLI to display

### Phase 2: CLI Command `export-prism`

Create `src/percell3/cli/export_prism.py` and register in `main.py`.

```python
# src/percell3/cli/export_prism.py

@click.command("export-prism")
@click.argument("output", type=click.Path())
@click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
@click.option("--overwrite", is_flag=True)
@click.option("--channels", default=None, help="Comma-separated channel filter.")
@click.option("--metrics", default=None, help="Comma-separated metric filter.")
@click.option("--scope", default="whole_cell",
              type=click.Choice(["whole_cell", "mask_inside", "mask_outside"]))
@error_handler
def export_prism(output, experiment, overwrite, channels, metrics, scope):
    """Export measurements as Prism-ready CSV files."""
```

Validation:
- Output path must be a directory (not an existing file)
- Parent directory must exist
- If output directory exists and is non-empty, require `--overwrite`
- Create output directory if it doesn't exist

Checklist:
- [x] Create `src/percell3/cli/export_prism.py`
- [x] Add `export-prism` command with argument/options
- [x] Path validation: parent exists, not an existing file, overwrite protection
- [x] Register in `src/percell3/cli/main.py` `_register_commands()`
- [x] Show status spinner during export
- [x] Print summary after export (channels, metrics, files written)

### Phase 3: Interactive Menu Integration

Add Prism export as an option in the Data > Export menu. Modify `_export_csv()` in `menu.py` to offer a format choice first.

```
Data > Export to CSV

Export format:
  [1] Wide format (single CSV, one row per cell)
  [2] Prism format (directory of CSVs, one per metric)
```

If Prism format selected:
1. Prompt for output directory path
2. Call `store.export_prism_csv(output_dir)`
3. Print summary

The Prism export does NOT offer channel/metric/scope filtering in the interactive menu (the directory structure gives per-file control). The CLI command does support `--channels` and `--metrics` for power users.

Checklist:
- [x] Add format selection at top of `_export_csv()` handler
- [x] Branch to `_export_prism(state)` handler for Prism format
- [x] Prompt for output directory (not file)
- [x] Auto-correct: if user enters a `.csv` path, strip the filename and use the directory
- [x] Overwrite confirmation if directory exists and is non-empty
- [x] Show status spinner and summary

### Phase 4: Tests

Add tests to `tests/test_cli/test_export.py` (or a new `test_export_prism.py`).

**Test fixture needed:** An experiment with:
- 2 conditions ("Control", "HS")
- 2 bio_reps ("N1", "N2")
- 2 FOVs per condition+bio_rep (to verify pooling)
- 2 channels ("DAPI", "GFP")
- Multiple metrics (mean_intensity, median_intensity)
- Particle summary metrics on one channel

Checklist:
- [x] Test basic Prism export: correct directory structure, correct file count
- [x] Test column headers: alphabetical `{condition}_{biorep}` order
- [x] Test FOV pooling: cells from 2 FOVs in same (condition, bio_rep) appear in same column
- [x] Test ragged columns: conditions with different cell counts produce correct padding
- [x] Test particle metrics routed to separate files
- [x] Test scope suffix in filenames when scope != whole_cell
- [x] Test empty experiment: no crash, helpful message
- [x] Test channel filter: only specified channels exported
- [x] Test metric filter: only specified metrics exported
- [x] Test overwrite protection: CLI rejects existing non-empty directory without --overwrite
- [x] Test CLI end-to-end: `percell3 export-prism <dir> -e <exp>`
- [ ] Test menu handler: format selection branches correctly

## Acceptance Criteria

- [x] `percell3 export-prism <dir> -e <experiment>` creates directory tree with one CSV per (channel, metric)
- [x] Each CSV has columns = `{condition}_{biorep}` (alphabetically sorted)
- [x] FOVs from same (condition, bio_rep) are pooled into one column
- [x] Only `is_valid=True` cells are included
- [x] Particle summary metrics go to separate CSV files per channel
- [x] Ragged columns padded with empty strings
- [x] Existing `export` command unchanged
- [x] Interactive menu offers format choice (Wide vs. Prism)
- [x] All tests pass

## Dependencies & Risks

- **Depends on measurement system**: The export only produces files for channels/metrics that have measurements. Currently the measurement CLI is a stub (`measure` command in `stubs.py`). The menu handler for measurements exists and works. The export should gracefully handle "no measurements" with a clear error message.
- **No new dependencies**: Uses only `csv` stdlib, `pathlib`, and existing `ExperimentStore` queries.
- **Risk: Large experiments**: For experiments with 100k+ cells, the per-metric query approach (Phase 1 algorithm) loads one metric at a time, keeping memory usage bounded. No risk of loading the entire measurements table at once.

## References

### Internal
- Brainstorm: `docs/brainstorms/2026-02-23-prism-csv-export-brainstorm.md`
- Existing export: `src/percell3/core/experiment_store.py:794` (`export_csv`)
- Measurement pivot: `src/percell3/core/experiment_store.py:476` (`get_measurement_pivot`)
- Particle summary metrics: `src/percell3/measure/particle_analyzer.py:18` (`PARTICLE_SUMMARY_METRICS`)
- CLI export command: `src/percell3/cli/export.py`
- Menu export handler: `src/percell3/cli/menu.py:1767` (`_export_csv`)
- CLI registration: `src/percell3/cli/main.py:34` (`_register_commands`)
- Measurement queries: `src/percell3/core/queries.py:524` (`select_measurements`)
- Cell queries with context: `src/percell3/core/queries.py:406` (`select_cells`)
