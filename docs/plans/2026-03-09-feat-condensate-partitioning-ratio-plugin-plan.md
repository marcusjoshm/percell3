---
title: "feat: Add condensate_partitioning_ratio plugin"
type: feat
status: completed
date: 2026-03-09
origin: docs/brainstorms/2026-03-09-condensate-partitioning-ratio-brainstorm.md
---

# Plan: Condensate Partitioning Ratio Plugin

## Summary

Build a new PerCell 3 analysis plugin that measures the partitioning of individual condensates by comparing fluorescence intensity **inside** each particle (condensed phase) to intensity in a **dilated ring outside** each particle (dilute phase), then reporting the ratio.

## Acceptance Criteria

- [x] Plugin auto-discovered by PluginRegistry as `condensate_partitioning_ratio`
- [x] Per-particle CSV output with condensate/dilute area, mean intensity, integrated intensity, and partitioning ratio
- [x] Two-step dilation ring: gap zone (default 3px) + measurement ring (default 2px)
- [x] Ring excludes other particles' condensate pixels; ring-ring overlap is allowed
- [x] Particles with ring area < `min_ring_pixels` (default 10) get NaN ratio
- [x] Division by zero (dilute_mean == 0) produces NaN ratio
- [x] CLI handler in menu.py with interactive parameter prompts
- [x] All tests passing (25/25)

## Key Decisions (from brainstorm)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Standalone plugin, single file | YAGNI — no shared base class, no core module (see brainstorm) |
| Background subtraction | None — raw intensities | High-SNR imaging; limitation documented (see brainstorm: Known Limitations #1) |
| Storage | CSV only, no DB measurements | Per-particle keyed; measurements table is cell_id keyed (see brainstorm) |
| Ring overlap | Allow ring-ring overlap | Only exclude other condensate pixels (see brainstorm) |
| Channel handling | One channel per invocation | Simpler schema (see brainstorm) |
| Edge particles | Clip ring to cell/image bounds | Measure available area (see brainstorm) |

## Implementation Steps

### Step 1: Create plugin file

**File:** `src/percell3/plugins/builtin/condensate_partitioning_ratio.py`

- [ ] Module-level `PARTITION_CSV_COLUMNS` list (19 columns per brainstorm CSV spec, including `threshold_name`)
- [ ] Class `CondensatePartitioningRatioPlugin(AnalysisPlugin)`
- [ ] `info()` → `PluginInfo(name="condensate_partitioning_ratio", version="1.0.0", description="...", author="PerCell Team")`
- [ ] `required_inputs()` → `[PluginInputRequirement(SEGMENTATION), PluginInputRequirement(THRESHOLD)]`
- [ ] `validate(store)` → check channels exist, cells exist, thresholds exist (same pattern as split_halo lines 96-111)
- [ ] `get_parameter_schema()` → JSON Schema with:
  - Required: `measurement_channel` (str), `particle_channel` (str)
  - Optional: `gap_pixels` (int, default 3, minimum 0), `ring_pixels` (int, default 2, minimum 1), `min_ring_pixels` (int, default 10, minimum 0), `export_csv` (bool, default True)
- [ ] `run()` method following split_halo structure (phases A-G from repo-research):
  - **Phase A:** Extract parameters with defaults
  - **Phase B:** Filter thresholds by `particle_channel`
  - **Phase C:** Determine FOV list (from cell_ids or all FOVs)
  - **Phase D:** Initialize accumulators (`rows_by_condition`, counters, warnings, `nan_count`)
  - **Phase E:** Main FOV loop:
    - E1: Resolve thresholds via config matrix + source_fov_id fallback (copy split_halo pattern)
    - E2: Read cell labels
    - E3: Merge particle labels from multiple thresholds (renumber with offset)
    - E4: Read measurement image
    - E5: Get cells for FOV
    - E6: Per-cell loop:
      - Extract bbox, crop arrays
      - Build `cell_mask` from label crop
      - Build `all_particles_in_cell` mask
      - Per-particle loop:
        - Single-particle mask from particle labels
        - **Condensate measurement:** mean and integrated intensity inside particle mask (float64 intermediate)
        - **Ring construction:**
          1. `inner = binary_dilation(particle_mask, disk(gap_pixels))`
          2. `outer = binary_dilation(particle_mask, disk(gap_pixels + ring_pixels))`
          3. `ring = outer & ~inner`
          4. `ring = ring & cell_mask` (clip to cell boundary)
          5. `ring = ring & ~all_other_particles` (exclude other condensate pixels)
        - **Ring quality check:** if `ring.sum() < min_ring_pixels` → NaN for dilute measurements and ratio, increment `nan_count`
        - **Dilute measurement:** mean and integrated intensity in ring (float64 intermediate)
        - **Ratio:** `condensate_mean / dilute_mean` if dilute_mean > 0 else NaN
        - **Area um2:** `area_pixels * pixel_size_um**2` if pixel_size_um is not None else NaN
        - Build row dict, append to `rows_by_condition[condition]`
    - E7: Update progress callback
  - **Phase F:** CSV export via `_export_csvs()` private method
  - **Phase G:** Build NaN warning if `nan_count > 0`, return `PluginResult`
- [ ] `_export_csvs()` private method:
  - Directory: `Path(store.path) / "exports"` (mkdir exist_ok)
  - Filename: `partitioning_ratio_{meas_channel}_{safe_condition}_{timestamp}.csv`
  - Uses `csv.DictWriter` with `PARTITION_CSV_COLUMNS`
  - Returns `dict[str, Path]` for `custom_outputs`

**Reference files:**
- `src/percell3/plugins/builtin/split_halo_condensate_analysis.py` (primary pattern)
- `src/percell3/plugins/base.py` (ABC interface)

### Step 2: Add CLI handler

**File:** `src/percell3/cli/menu.py`

- [ ] Add `elif` branch in `_make_plugin_runner()` (~line 444):
  ```python
  elif plugin_name == "condensate_partitioning_ratio":
      _run_condensate_partitioning_ratio(state, registry)
  ```
- [ ] Define `_run_condensate_partitioning_ratio(state, registry)` function:
  - Step 1: Get store, validate plugin
  - Step 2: Prompt measurement channel (`numbered_select_one(ch_names)`)
  - Step 3: Prompt particle channel (filter thresholds by source_channel, `numbered_select_one`)
  - Step 4: Prompt gap_pixels (default "3")
  - Step 5: Prompt ring_pixels (default "2")
  - Step 6: Prompt min_ring_pixels (default "10")
  - Step 7: FOV selection (`_show_fov_status_table` + `_select_fovs_from_table`, exclude derived FOVs)
  - Step 8: Confirmation summary
  - Step 9: Run with `make_progress()` context
  - Step 10: Display summary (cells processed, particles measured, CSV paths, NaN warnings)

**Reference:** `_run_condensate_analysis()` function (lines 961-1141) — follow same structure but simpler (no exclusion channel, no normalization channel, no save_images)

### Step 3: Write tests

**File:** `tests/test_plugins/test_condensate_partitioning_ratio.py`

- [ ] `_create_partitioning_experiment(tmp_path)` helper:
  - 80x80 image with 2 cells (20x20 each at known positions)
  - GFP channel: background ~30, particle 1 at known position = 200, particle 2 = 250
  - Cell labels, threshold mask, particle labels at known positions
  - Stash test IDs on store object
- [ ] `TestPluginInfo`:
  - `test_info_name` — verify name is `"condensate_partitioning_ratio"`
  - `test_parameter_schema` — verify required params, defaults
- [ ] `TestValidation`:
  - `test_empty_experiment` — no channels → error
  - `test_no_cells` — channels but no cells → error
  - `test_no_thresholds` — channels + cells but no thresholds → error
  - `test_valid_experiment` — all present → empty errors list
- [ ] `TestPartitioningMeasurement`:
  - `test_basic_ratio` — verify condensate_mean > dilute_mean, ratio > 1.0 for bright particles
  - `test_condensate_area` — verify area matches known particle size
  - `test_dilute_ring_area` — verify ring area is reasonable for dilation params
  - `test_ratio_value_range` — with known synthetic data, verify ratio is within expected range
- [ ] `TestRingConstruction`:
  - `test_other_particles_excluded_from_ring` — two adjacent particles, verify other's condensate excluded
  - `test_ring_clipped_to_cell_mask` — particle near cell edge, verify ring doesn't extend outside cell
  - `test_min_ring_pixels_nan` — ring with < min_ring_pixels gets NaN ratio
  - `test_zero_dilute_intensity_nan` — ring pixels all zero → NaN ratio
- [ ] `TestCSVExport`:
  - `test_csv_columns` — all 19 columns present
  - `test_csv_file_exists` — file written to exports/
  - `test_csv_content` — rows have expected values
  - `test_no_export_when_disabled` — `export_csv=False` produces no CSV
- [ ] `TestEdgeCases`:
  - `test_no_particles_in_cell` — cell produces no rows
  - `test_progress_callback` — callback called once per FOV
  - `test_cell_ids_filter` — only specified cells measured
  - `test_pixel_size_none_area_um2_nan` — NaN for area_um2 when no calibration
  - `test_nan_count_warning` — warning emitted when particles get NaN ratios
- [ ] `TestMultiThreshold`:
  - `test_merged_particle_labels` — two thresholds produce renumbered labels
  - `test_threshold_name_in_csv` — combined threshold name appears in CSV

**Reference:** `tests/test_plugins/test_split_halo_condensate_analysis.py` (test patterns, synthetic data helper)

## Notes

- **Steps 2 and 3 can run in parallel** after Step 1 completes (they touch separate files with no dependencies on each other)
- Step 1 is the largest step but is well-bounded by the split_halo reference implementation
- No core module — the ring construction is ~10 lines of numpy inline in `run()`, not worth a separate file per YAGNI
- Plugin file should use runtime imports for scipy/skimage (inside `run()`) following split_halo pattern

## Sources

- **Origin brainstorm:** `docs/brainstorms/2026-03-09-condensate-partitioning-ratio-brainstorm.md` — key decisions: standalone plugin, raw intensities only, CSV-only storage, ring overlap allowed, gap_pixels=3 default, min_ring_pixels=10
- **Research:** `.workflows/plan-research/condensate-partitioning-ratio/agents/repo-research.md` — full split_halo code structure, plugin ABC, test patterns, CLI handler pattern
- **Research:** `.workflows/plan-research/condensate-partitioning-ratio/agents/learnings.md` — NaN-safe measurement, float64 intermediates, mask integrity
- **Research:** `.workflows/plan-research/condensate-partitioning-ratio/agents/specflow.md` — CLI handler gap (critical), division by zero, NaN warning
- **Reference implementation:** `src/percell3/plugins/builtin/split_halo_condensate_analysis.py`
- **Plugin ABC:** `src/percell3/plugins/base.py`
- **Red team review:** `.workflows/brainstorm-research/condensate-partitioning-ratio/red-team--opus.md`
