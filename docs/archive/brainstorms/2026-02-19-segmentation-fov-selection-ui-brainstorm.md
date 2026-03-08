---
title: Segmentation FOV Selection UI Redesign
date: 2026-02-19
type: feat
status: decided
---

# Segmentation FOV Selection UI Redesign

## What We're Building

Replace the confusing hierarchical segmentation prompts (condition -> bio rep -> FOV) with a **flat FOV status table** that shows all FOVs in the experiment with their metadata and segmentation status. The user selects FOVs by number using `numbered_select_many` (space-separated numbers or "all"). Model selection switches from free-text to a numbered list.

### Current Flow (broken UX)

```
Channel → free-text model → diameter → condition filter → bio rep filter → FOV filter → confirm
```

Problems:
1. Model is free-text, no list shown
2. Bio rep list shows duplicates with no condition context (e.g. eight "1" entries)
3. No "select all" for FOV filter
4. No visibility into which FOVs are already segmented
5. Hierarchical filtering is confusing and doesn't match the mental model

### New Flow

```
Channel → model (numbered list) → diameter → FOV table + select → confirm
```

## Why This Approach

- **Flat table matches import pattern.** The import UI was just redesigned with a table-first approach (`show_file_group_table`). Reusing the same pattern for segmentation gives a consistent experience.
- **All info visible at once.** User sees condition, bio rep, shape, AND segmentation status in one table. No guessing what "Biological replicate [1]" means.
- **Re-segmentation is explicit.** Cells column shows existing count, so user knows they're replacing results. Re-segmenting a FOV replaces its existing segmentation.
- **Simple implementation.** Reuses `numbered_select_many` which already supports space-separated numbers and "all".

## Key Decisions

1. **Flat table, not grouped or filtered.** User confirmed scrolling through a long list is fine. No condition grouping needed.
2. **Model from numbered list.** Use `KNOWN_CELLPOSE_MODELS` from `cellpose_adapter.py` with `numbered_select_one`. Put `cpsam` first as the recommended default.
3. **Table columns:** `#`, `FOV`, `Condition`, `Bio Rep`, `Shape`, `Cells` (count or `-`), `Model` (last used or `-`).
4. **Re-segmentation replaces existing.** When a FOV with existing cells is re-segmented, the old cells/measurements are replaced. The confirmation summary should warn about this.
5. **"all" is the default selection.** Blank input or "all" selects every FOV in the table.

## FOV Table Mockup

```
FOVs in experiment
┌───┬─────────┬──────────────────────────┬────────┬─────────────┬───────┬───────┐
│ # │ FOV     │ Condition                │ BioRep │ Shape       │ Cells │ Model │
├───┼─────────┼──────────────────────────┼────────┼─────────────┼───────┼───────┤
│ 1 │ FOV_001 │ 30min_Recovery_+_VCPi    │ N1     │ 3246 x 3256 │   -   │   -   │
│ 2 │ FOV_001 │ 30min_Recovery_+_dTAG13  │ N1     │ 3254 x 3253 │   -   │   -   │
│ 3 │ FOV_001 │ 30min_Recovery           │ N1     │ 3219 x 3235 │   -   │   -   │
│ 4 │ FOV_001 │ HS_Merged                │ N1     │ 2804 x 2791 │  263  │ cpsam │
│ 5 │ FOV_001 │ HS_+_VCPi               │ N1     │ 1871 x 4144 │   -   │   -   │
│ ...                                                                           │
└───┴─────────┴──────────────────────────┴────────┴─────────────┴───────┴───────┘
Select FOVs (numbers, 'all', or blank=all) (h=home, b=back): 4 5
```

## Confirmation Mockup

```
Segmentation settings:
  Channel:  G3BP1
  Model:    cpsam
  Diameter: 70.0 px
  FOVs:     2 selected (1 will be re-segmented)
  [1] Yes
  [2] No
Proceed? (h=home, b=back): 1
```

## Resolved Questions

- **Scrolling vs filtering?** Scrolling is fine even for 50+ FOVs. No filter needed.
- **Selection pattern?** Usually all, but need cherry-pick and re-segment individual FOVs too.
- **Table info?** Both metadata (shape, condition, bio rep) AND segmentation status (cells, model).

## Open Questions

None remaining.

## References

- Current segmentation menu: `src/percell3/cli/menu.py` `_segment_cells` (~lines 618-741)
- Import table-first pattern: `src/percell3/cli/menu.py` `_import_images` + `src/percell3/cli/import_cmd.py` `show_file_group_table`
- Known models: `src/percell3/segment/cellpose_adapter.py` `KNOWN_CELLPOSE_MODELS`
- FOV data: `src/percell3/core/experiment_store.py` `get_fovs()`, `get_cell_count()`
- Multi-select pattern: `src/percell3/cli/menu.py` `numbered_select_many`
