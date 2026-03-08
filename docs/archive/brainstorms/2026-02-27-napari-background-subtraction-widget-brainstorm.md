---
topic: Napari Background Subtraction Widget
date: 2026-02-27
status: decided
---

# Napari Background Subtraction Widget

## What We're Building

A napari dock widget that lets users subtract a user-specified background value from selected channels, creating a new derived FOV with the background-subtracted images. The original image is preserved.

## Why This Feature

Users need to apply flat background subtraction to images before further analysis (e.g., surface plotting, intensity comparisons). Currently there's no way to do this within PerCell 3 — users would need to export, process externally, and re-import.

## Key Decisions

- **Algorithm:** User specifies a numeric BG value, subtracted from every pixel
- **Storage:** Creates a new derived FOV (e.g., `bg_sub_FOV1`) — original image preserved
- **Channel scope:** User picks which channel(s) to subtract from via dropdown/multi-select
- **Negative pixels:** Clipped to 0 (preserves unsigned integer dtype)
- **Access point:** Napari viewer widget only (no CLI menu item)
- **Widget UX:** Input field for BG value, channel selector, "Apply" button
- **Naming:** Derived FOV named `bg_sub_{original_fov_name}`
- **Overwrite on re-run:** If `bg_sub_{name}` already exists, overwrite it (idempotent, same pattern as split-halo derived FOVs)

## User Flow

1. User opens a FOV in napari viewer
2. "Background Subtraction" dock widget is visible on the right
3. User enters a background value (e.g., `150`)
4. User selects which channels to subtract from (checkboxes or multi-select)
5. User clicks "Apply"
6. System creates `bg_sub_{fov_name}` derived FOV with subtracted images
7. Status label shows "Created bg_sub_FOV_001 with 2 channels"

## Scope

### In Scope
- [ ] Napari dock widget with: value input, channel multi-select, apply button
- [ ] Create derived FOV via `store.add_fov()` + `store.write_image()`
- [ ] Clip negative pixels to 0
- [ ] Overwrite existing derived FOV on re-run
- [ ] Status feedback in the widget

### Out of Scope
- CLI batch processing
- Rolling ball or spatially varying background subtraction
- Preview layer before applying
- Automatic BG estimation from histogram
- Undo/backup mechanism
