---
title: "Filter CSV Exports by FOV"
date: 2026-03-04
type: feat
status: brainstorm
---

# Filter CSV Exports by FOV

## What We're Building

Add a FOV selection step to the "Export to CSV" handler in the DATA menu. Currently all three export paths (wide-format, particle, prism) export all FOVs unconditionally. Users need to select a subset of FOVs for export.

### Workflow Change

Add a FOV selection step early in the export flow (after format selection, before path prompt):

```
Step 1: Format selection (wide vs prism) — existing
Step 2: FOV selection — NEW (using _select_fovs_from_table pattern)
Step 3: Path prompt — existing
Step 4+: Channel/metric/scope filters — existing
```

## Why This Approach

- **`_select_fovs_from_table`** is the established pattern used in 9+ other menu handlers
- Underlying export methods need `fov_ids` parameter added to filter at the query level
- Blank/all selection = current behavior (no breaking change)

## Key Decisions

1. **Selection pattern**: Use `_select_fovs_from_table` (same as segment, measure, threshold handlers)
2. **Default**: Blank = all FOVs (preserves current behavior)
3. **Scope**: Applies to all three export paths (wide, particle, prism)
4. **Filter level**: Pass `fov_ids` to export methods, filter at SQL query level

## Open Questions

None — requirements are clear.
