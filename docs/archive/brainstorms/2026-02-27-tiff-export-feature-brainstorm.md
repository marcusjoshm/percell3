---
topic: TIFF Export Feature
date: 2026-02-27
status: decided
branch: feat/split-halo-condensate-analysis
---

# TIFF Export Feature

## What We're Building

A general-purpose TIFF export feature that lets users export any FOV image (including derived FOVs created by plugins like split-halo-condensate) as .tiff files. Two access points:

1. **CLI Data Menu** — batch export with multi-FOV selection
2. **Napari Viewer** — quick single-image export button for the currently viewed image

## Why This Feature

The split-halo-condensate plugin creates derived FOV images (condensed_phase, dilute_phase) stored in OME-Zarr. Original imported images already exist as TIFFs, but derived images have no TIFF equivalent. Users need TIFF exports for:
- External analysis tools
- Surface plot visualization (3D surface plot plugin)
- Sharing with collaborators
- Archival in standard microscopy format

## Key Decisions

- **Two access points:** Data menu for batch, viewer button for quick single exports
- **FOV selection:** All FOVs (original + derived) in one mixed list — derived FOVs use their descriptive names (e.g., `condensed_phase_FOV1`)
- **Channel handling:** Export all channels for selected FOVs — no channel picker needed
- **Naming convention:** Match FOV name directly — e.g., `condensed_phase_FOV1_GFP.tiff`
- **Output location:** `exports/tiff/` directory inside the experiment
- **Branch:** Work on `feat/split-halo-condensate-analysis` since this feature is motivated by the plugin's derived images

## Scope

### In Scope
- [ ] Data menu item: "Export FOVs as TIFF"
- [ ] FOV selection prompt (multi-select from all FOVs including derived)
- [ ] Export all channels per selected FOV
- [ ] Write 16-bit TIFF files using tifffile (already a dependency)
- [ ] Napari viewer "Export as TIFF" button for current image
- [ ] Progress feedback during batch export

### Out of Scope
- OME-TIFF with full metadata (future enhancement)
- Channel selection filtering
- Condition-based folder organization
- Composite/RGB TIFF generation
