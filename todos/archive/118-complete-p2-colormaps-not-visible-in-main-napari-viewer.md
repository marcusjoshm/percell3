---
status: complete
priority: p2
issue_id: "118"
tags: [code-review, viewer, feature]
dependencies: []
---

# New colormaps not visible in main napari viewer layer controls

## Problem Statement

New colormaps (nipy_spectral, Spectral, rainbow, coolwarm, gnuplot, jet, cividis) were added to the surface plot widget's `_COLORMAPS` dropdown, but they don't appear in napari's main image viewer layer controls. The user expects to see them when viewing regular image layers, not just in the 3D surface plot dock widget.

## Findings

- **Found by:** user report + code investigation
- The `_COLORMAPS` list in `surface_plot_widget.py` only controls the **3D surface plot dock widget's** dropdown — it does NOT affect napari's built-in layer control panel
- napari's built-in layer controls show `AVAILABLE_COLORMAPS` (30 items) which is a fixed registry
- Matplotlib colormaps like `nipy_spectral` work on-demand in napari but aren't listed in the default dropdown
- The main viewer (`_viewer.py`) assigns colormaps per-channel using `_channel_colormap()` with a name/color lookup — it doesn't expose a user-selectable colormap dropdown
- To make custom colormaps visible in napari's layer controls, they need to be registered via `napari.utils.colormaps.AVAILABLE_COLORMAPS`

## Proposed Solutions

### Solution A: Register matplotlib colormaps with napari at viewer launch (Recommended)

In `_viewer.py`, register the desired matplotlib colormaps with napari's colormap registry before creating the viewer:

```python
from napari.utils.colormaps import AVAILABLE_COLORMAPS
from matplotlib import colormaps as mpl_colormaps

for name in ["nipy_spectral", "Spectral", "rainbow", "coolwarm", "gnuplot", "jet", "cividis"]:
    if name not in AVAILABLE_COLORMAPS:
        AVAILABLE_COLORMAPS[name] = napari.utils.colormaps.ensure_colormap(name)
```

This makes them appear in napari's built-in layer control dropdown for all layers.

- **Pros:** Simple, works globally, users can select from napari's native UI
- **Cons:** Modifies napari global state
- **Effort:** Small
- **Risk:** Low

### Solution B: Keep surface plot only

Accept that the new colormaps are surface-plot-only. Document that they are available in the 3D surface plot widget dropdown, not in napari's main layer controls.

- **Pros:** No code change needed
- **Cons:** Doesn't address user expectation
- **Effort:** None
- **Risk:** None

## Technical Details

**Affected files:**
- `src/percell3/segment/viewer/_viewer.py` — register colormaps before viewer creation

## Acceptance Criteria

- [ ] nipy_spectral, Spectral, rainbow, coolwarm, gnuplot, jet, cividis appear in napari's layer control colormap dropdown
- [ ] Existing channel-based colormap assignment still works (DAPI=blue, GFP=green, etc.)
- [ ] Colormaps work correctly when selected from the dropdown
