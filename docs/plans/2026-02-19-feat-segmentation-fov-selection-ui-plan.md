---
title: "feat: Segmentation FOV Selection UI Redesign"
type: feat
date: 2026-02-19
---

# Segmentation FOV Selection UI Redesign

## Overview

Replace the confusing hierarchical segmentation prompts (condition -> bio rep -> FOV) with a **flat FOV status table** showing all FOVs in the experiment, their metadata, and segmentation status. Users select FOVs by number using space-separated input or "all". Model selection switches from free-text to a numbered list. Re-segmenting a FOV deletes its existing cells and measurements before inserting new ones.

## Problem Statement

User tested segmentation with 8 conditions (1 FOV each). Three problems:

1. **Model is free-text** — user must type "cpsam" instead of picking from a list. No validation until deep in the engine.
2. **Bio rep list shows duplicates with no context** — eight entries all showing "1" with no indication of which condition they belong to. Selecting one gives no feedback about what was chosen.
3. **No "select all" for FOVs** — hierarchical condition -> bio rep -> FOV filtering is confusing and doesn't allow multi-select across conditions. No way to see the full picture before selecting.

## Proposed Solution

### New Flow

```
Channel (numbered list) → Model (numbered list) → Diameter → FOV status table + select → Confirm → Segment
```

### FOV Status Table Mockup

```
FOVs in experiment
┌───┬─────────┬──────────────────────────┬────────┬─────────────┬───────┬───────┐
│ # │ FOV     │ Condition                │ BioRep │ Shape       │ Cells │ Model │
├───┼─────────┼──────────────────────────┼────────┼─────────────┼───────┼───────┤
│ 1 │ FOV_001 │ 30min_Recovery_+_VCPi    │ N1     │ 3246 x 3256 │   -   │   -   │
│ 2 │ FOV_001 │ 30min_Recovery_+_dTAG13  │ N1     │ 3254 x 3253 │   -   │   -   │
│ 3 │ FOV_001 │ HS_Merged                │ N1     │ 2804 x 2791 │  263  │ cpsam │
│ 4 │ FOV_001 │ HS_+_VCPi               │ N1     │ 1871 x 4144 │   -   │   -   │
└───┴─────────┴──────────────────────────┴────────┴─────────────┴───────┴───────┘
Select FOVs (numbers, 'all', or blank=all) (h=home, b=back): all
```

### Confirmation Mockup (with re-segmentation warning)

```
Segmentation settings:
  Channel:  G3BP1
  Model:    cpsam
  Diameter: 70.0 px
  FOVs:     8 selected
  Re-segment: FOV_001/HS_Merged (263 cells will be replaced)
  [1] Yes
  [2] No
Proceed? (h=home, b=back): 1
```

## Files to Modify

| File | Changes |
|------|---------|
| `src/percell3/core/queries.py` | Add `select_fov_segmentation_summary()` batch query, `delete_cells_for_fov()` cascade delete |
| `src/percell3/core/experiment_store.py` | Add `get_fov_segmentation_summary()`, `delete_cells_for_fov()` public methods |
| `src/percell3/segment/_engine.py` | Call `delete_cells_for_fov()` before inserting new cells for each FOV |
| `src/percell3/cli/menu.py` | Rewrite `_segment_cells()` with table-first flow |
| `tests/test_core/test_queries.py` | Tests for new queries |
| `tests/test_core/test_experiment_store.py` | Tests for new store methods |
| `tests/test_cli/test_menu_segment.py` | Tests for new segmentation UI helpers |

## Implementation

### Phase 1: Add cell deletion for re-segmentation

**File: `src/percell3/core/queries.py`**

- [x] Add `delete_cells_for_fov(conn, fov_id)` — cascade delete: measurements → cell_tags → cells for a given FOV
- [x] Add `select_fov_segmentation_summary(conn)` — single SQL query returning `(fov_id, cell_count, last_model_name)` for all FOVs

```python
def delete_cells_for_fov(conn: sqlite3.Connection, fov_id: int) -> int:
    """Delete all cells (and their measurements/tags) for a FOV.

    Returns the number of cells deleted.
    """
    count = conn.execute(
        "SELECT COUNT(*) FROM cells WHERE fov_id = ?", (fov_id,)
    ).fetchone()[0]
    conn.execute(
        "DELETE FROM measurements WHERE cell_id IN "
        "(SELECT id FROM cells WHERE fov_id = ?)", (fov_id,)
    )
    conn.execute(
        "DELETE FROM cell_tags WHERE cell_id IN "
        "(SELECT id FROM cells WHERE fov_id = ?)", (fov_id,)
    )
    conn.execute("DELETE FROM cells WHERE fov_id = ?", (fov_id,))
    conn.commit()
    return count


def select_fov_segmentation_summary(
    conn: sqlite3.Connection,
) -> dict[int, tuple[int, str | None]]:
    """Return {fov_id: (cell_count, last_model_name)} for all FOVs.

    Uses the most recent segmentation_run that produced cells for each FOV.
    Returns cell_count=0 and model=None for unsegmented FOVs.
    """
    rows = conn.execute("""
        SELECT f.id AS fov_id,
               COUNT(c.id) AS cell_count,
               sr.model_name
        FROM fovs f
        LEFT JOIN cells c ON c.fov_id = f.id AND c.is_valid = 1
        LEFT JOIN segmentation_runs sr ON c.segmentation_id = sr.id
        GROUP BY f.id
        ORDER BY f.id
    """).fetchall()
    result = {}
    for r in rows:
        result[r["fov_id"]] = (r["cell_count"], r["model_name"])
    return result
```

**File: `src/percell3/core/experiment_store.py`**

- [x] Add `delete_cells_for_fov(fov_name, condition)` — resolves FOV by name, calls query, returns deleted count
- [x] Add `get_fov_segmentation_summary()` — returns the batch summary dict

**File: `src/percell3/segment/_engine.py`**

- [ ] Before `add_cells` in the FOV loop, call `store.delete_cells_for_fov(fov_name, condition)` if cells exist
- [ ] This ensures re-segmentation cleanly replaces old data

### Phase 2: Rewrite `_segment_cells()` with table-first flow

**File: `src/percell3/cli/menu.py`**

- [x] Replace entire `_segment_cells()` function (lines ~618-741)
- [x] `_prompt_bio_rep()` kept — used by measure and edit menus
- [x] Add `_show_fov_status_table()` helper — Rich table with #, FOV, Condition, BioRep, Shape, Cells, Model
- [x] Add `_build_model_list()` helper — ordered list with cpsam first, then sorted alphabetically

**New `_segment_cells()` pseudocode:**

```python
def _segment_cells(state: MenuState) -> None:
    store = state.require_experiment()

    # 1. Channel selection (unchanged)
    channels = store.get_channels()
    if not channels:
        console.print("[red]No channels found.[/red] Import images first.")
        return
    channel = numbered_select_one([ch.name for ch in channels], "Channel to segment")

    # 2. Check FOVs exist (early exit)
    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("[red]No FOVs found.[/red] Import images first.")
        return

    # 3. Model selection (numbered list)
    models = _build_model_list()
    console.print("\n[bold]Segmentation model:[/bold]")
    model = numbered_select_one(models, "Model")

    # 4. Diameter (unchanged)
    diam_str = menu_prompt("Cell diameter in pixels (blank = auto-detect)", default="")
    diameter = _parse_diameter(diam_str)  # returns float | None, prints error on invalid

    # 5. FOV status table + selection
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(all_fovs, seg_summary)

    if len(all_fovs) == 1:
        console.print(f"  [dim](auto-selected: {all_fovs[0].name})[/dim]")
        selected_fovs = all_fovs
    else:
        # Prompt for selection (space-separated numbers, "all", blank=all)
        selected_fovs = _select_fovs_from_table(all_fovs)

    # 6. Confirmation with re-segmentation warning
    reseg_fovs = [f for f in selected_fovs if seg_summary.get(f.id, (0, None))[0] > 0]
    _show_segment_confirmation(channel, model, diameter, selected_fovs, reseg_fovs, seg_summary)

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Segmentation cancelled.[/yellow]")
        return

    # 7. Run segmentation (pass FOV names, no condition/bio_rep filter needed)
    fov_names = [f.name for f in selected_fovs]
    # Engine needs condition context for FOV resolution — pass None to get all,
    # then filter by fov names
    ...
```

**`_show_fov_status_table()` function:**

```python
def _show_fov_status_table(
    fovs: list[FovInfo],
    seg_summary: dict[int, tuple[int, str | None]],
) -> None:
    table = Table(show_header=True, title="FOVs in experiment")
    table.add_column("#", style="bold", width=4)
    table.add_column("FOV")
    table.add_column("Condition")
    table.add_column("Bio Rep")
    table.add_column("Shape")
    table.add_column("Cells", justify="right")
    table.add_column("Model")

    for i, f in enumerate(fovs, 1):
        cell_count, model_name = seg_summary.get(f.id, (0, None))
        shape = f"{f.width} x {f.height}" if f.width and f.height else "-"
        table.add_row(
            str(i), f.name, f.condition, f.bio_rep, shape,
            str(cell_count) if cell_count > 0 else "-",
            model_name or "-",
        )
    console.print(table)
```

**`_build_model_list()` function:**

```python
def _build_model_list() -> list[str]:
    from percell3.segment.cellpose_adapter import KNOWN_CELLPOSE_MODELS
    models = sorted(KNOWN_CELLPOSE_MODELS - {"cpsam"})
    return ["cpsam"] + models
```

**`_select_fovs_from_table()` function:**

Uses a `menu_prompt` loop (similar to `numbered_select_many` but with blank=all support):

```python
def _select_fovs_from_table(fovs: list[FovInfo]) -> list[FovInfo]:
    while True:
        raw = menu_prompt("Select FOVs (numbers, 'all', or blank=all)", default="all")
        if raw.lower() == "all":
            return list(fovs)
        parts = raw.split()
        try:
            indices = sorted({int(p) for p in parts})
        except ValueError:
            console.print("[red]Enter numbers separated by spaces, or 'all'.[/red]")
            continue
        if any(i < 1 or i > len(fovs) for i in indices):
            console.print(f"[red]Numbers must be 1-{len(fovs)}.[/red]")
            continue
        return [fovs[i - 1] for i in indices]
```

### Phase 3: Engine integration for re-segmentation

**File: `src/percell3/segment/_engine.py`**

- [x] In the FOV processing loop, before calling `store.add_cells()`, delete existing cells for re-segmentation
- [x] The menu now passes explicit FOV names via the `fovs` parameter — no condition/bio_rep filter needed

```python
# Before add_cells (in the per-FOV loop):
existing_cells = store.get_cell_count(
    condition=fov_info.condition, fov=fov_info.name
)
if existing_cells > 0:
    store.delete_cells_for_fov(fov_info.name, fov_info.condition)
```

### Phase 4: Tests

- [x] `tests/test_core/test_queries.py`: Test `delete_cells_for_fov` cascade (measurements + tags + cells deleted)
- [x] `tests/test_core/test_queries.py`: Test `select_fov_segmentation_summary` returns correct counts
- [x] `tests/test_core/test_experiment_store.py`: Test `delete_cells_for_fov` through store API
- [x] `tests/test_core/test_experiment_store.py`: Test `get_fov_segmentation_summary` with mix of segmented/unsegmented FOVs
- [x] `tests/test_cli/test_menu_segment.py`: Test `_build_model_list` returns cpsam first
- [x] `tests/test_cli/test_menu_segment.py`: Test `_show_fov_status_table` renders without crash
- [x] `tests/test_cli/test_menu_segment.py`: Test `_select_fovs_from_table` with "all", numbers, blank
- [x] Run full test suite (647 passed)

## Edge Cases

- **Empty experiment (0 FOVs)**: Exit early after channel selection with "No FOVs found. Import images first."
- **Single FOV**: Show table (user sees segmentation status) but auto-select with `(auto-selected: ...)` message
- **All FOVs already segmented**: Table shows cell counts; confirmation warns about re-segmentation for all
- **Mixed segmented/unsegmented**: Confirmation lists only the FOVs being re-segmented (up to 5 names, then "...and N more")
- **Re-segmentation with different channel**: Old cells from the previous channel's segmentation remain (only cells on the same FOV are replaced, regardless of channel). The table shows the most recent segmentation run's model.

## Acceptance Criteria

- [ ] Model is selected from a numbered list, not typed as free text
- [ ] FOV status table shows all FOVs with condition, bio rep, shape, cell count, and model
- [ ] User can select FOVs by space-separated numbers, "all", or blank (= all)
- [ ] Re-segmenting a FOV deletes its existing cells and measurements before inserting new ones
- [ ] Confirmation shows re-segmentation warning with FOV names and cell counts
- [ ] No more hierarchical condition -> bio rep -> FOV filtering
- [ ] Single FOV auto-selects (with message)
- [ ] Empty experiment exits early with helpful message
- [ ] All existing tests pass

## References

- Brainstorm: `docs/brainstorms/2026-02-19-segmentation-fov-selection-ui-brainstorm.md`
- Current segmentation menu: `src/percell3/cli/menu.py:618-741`
- Import table-first pattern: `src/percell3/cli/import_cmd.py:225-265` `show_file_group_table()`
- Known models: `src/percell3/segment/cellpose_adapter.py:12-21` `KNOWN_CELLPOSE_MODELS`
- FOV data: `src/percell3/core/experiment_store.py` `get_fovs()`, `get_cell_count()`
- Existing multi-select: `src/percell3/cli/menu.py:142-179` `numbered_select_many()`
