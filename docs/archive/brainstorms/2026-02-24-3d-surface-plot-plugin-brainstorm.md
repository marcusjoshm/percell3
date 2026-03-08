# Brainstorm: 3D Surface Plot Plugin for napari

**Date:** 2026-02-24
**Status:** Draft
**Next step:** `/workflows:plan`

---

## What We're Building

A **3D surface plot visualization plugin** that renders a microscopy image as an interactive 3D heightmap inside napari. The user selects:

1. **Height channel** — pixel intensity becomes the Z-axis elevation (e.g., DAPI)
2. **Color channel** — pixel intensity of a second channel drives a colormap painted onto the 3D surface (e.g., GFP intensity mapped to a color gradient on the DAPI terrain)

This lets researchers see where signal from one channel (color) localizes relative to the landscape of another channel (height) — a spatial correlation view that flat 2D overlays can't provide.

### User Flow

1. User selects **"3D Surface Plot"** from the Plugins menu
2. User picks an FOV
3. A 2D napari view opens showing the FOV's channels
4. User draws a **rectangle ROI** to select a region of interest
5. User selects the **height channel** and **color channel** (always two channels required)
6. User optionally adjusts **Gaussian smoothing sigma** for the height data
7. A new napari window (or layer) renders the 3D surface using napari's `Surface` layer type
8. User can rotate, zoom, and pan the 3D surface interactively

### Rendering Details

- **Technology:** napari's built-in `Surface` layer (mesh-based 3D rendering)
- **Mesh construction:** Convert the ROI pixel grid into a triangle mesh where vertex Z = height channel intensity
- **Color mapping:** The `values` parameter of the Surface layer is set to the color channel's intensity at each vertex, with a configurable colormap
- **Smoothing:** Optional Gaussian blur (configurable sigma, small default) applied to the height channel before mesh construction to reduce noise

---

## Why This Approach

### napari Surface layer over PyVista/matplotlib

- Stays within the napari ecosystem the project already uses
- Native rotation, zoom, pan controls
- No additional heavy dependencies (PyVista) or limited interactivity (matplotlib)
- Surface layer's `values` parameter maps naturally to the color overlay use case

### New VisualizationPlugin type over reusing AnalysisPlugin

- The existing `AnalysisPlugin` ABC is designed for read-data-write-measurements workflows
- A visualization plugin reads data and launches a viewer — fundamentally different contract
- A lightweight `VisualizationPlugin` ABC keeps the plugin system honest and extensible for future viz plugins (e.g., histogram plots, scatter plots)
- The `PluginRegistry` will discover both types, and the Plugins menu will list them together

### Interactive ROI over numeric coordinates

- Researchers work visually — drawing a rectangle on the image is more intuitive than entering pixel coordinates
- Full-FOV 3D rendering would be too large and noisy for typical microscopy images (1024x1024+)
- The 2D napari view is already available in the codebase as a starting point

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Entry point | Plugins menu (item 8) | Consistent with other plugins, no new top-level menu items |
| Data scope | Single FOV with interactive ROI crop | Full FOV too large; ROI keeps rendering fast and focused |
| Channel selection | Always two channels (height + color) | Core use case is the dual-channel overlay |
| Color overlay | Required, not optional | Simplifies the interface; single-channel heightmap is less useful |
| Smoothing | Optional Gaussian, configurable sigma | Reduces pixel-level noise in the heightmap; user controls the amount |
| Rendering | napari Surface layer | Native ecosystem, good 3D controls, color values built-in |
| Plugin type | New VisualizationPlugin ABC | Clean separation from AnalysisPlugin; extensible for future viz |
| ROI method | Interactive rectangle in 2D napari view | Visual, intuitive for researchers |
| Colormap | Configurable via dock widget dropdown | Interactive switching while viewing |
| Z-scale | Slider in dock widget | Interactive height exaggeration |
| Export | Screenshot button in dock widget | Quick capture without external tools |

---

## Resolved Questions

1. **Colormap choice** — Configurable via a napari dock widget dropdown. User can switch colormaps interactively while viewing the 3D surface.

2. **Z-scale factor** — Yes, configurable via a slider in the napari dock widget. Allows interactive height exaggeration adjustment.

3. **Export** — Yes, add a "Save Screenshot" button to the dock widget for exporting the 3D view.

---

## Dock Widget Summary

The 3D Surface Plot will include a **dock widget** with these controls:

- **Colormap dropdown** — switch the color overlay colormap (viridis, magma, hot, plasma, etc.)
- **Z-scale slider** — adjust height exaggeration interactively
- **Smoothing sigma slider** — adjust Gaussian smoothing on the height channel
- **Save Screenshot button** — export the current 3D view as an image file
