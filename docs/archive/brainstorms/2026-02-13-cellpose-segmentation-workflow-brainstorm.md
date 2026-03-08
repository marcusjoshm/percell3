---
title: "Cellpose Segmentation Workflow Design"
date: 2026-02-13
topic: segmentation-cellpose-workflow
status: complete
---

# Cellpose Segmentation Workflow Design

## What We're Building

A segmentation module for PerCell 3 that wraps Cellpose behind an abstract interface, with two distinct workflows:

1. **Automated (headless)**: `percell3 segment -e exp --channel DAPI` runs Cellpose programmatically via the Python API. No GUI, no files — images go in, labels + cell properties come out in zarr/SQLite.

2. **GUI (napari-based)**: Launch napari pre-loaded with experiment data, user runs the cellpose-napari plugin, manually edits labels, and PerCell 3 imports the result back. The native Cellpose GUI is also supported as a fallback (imports `_seg.npy` files).

The module is split into two parts following hexagonal architecture:
- **Module 3a (Segmentation Engine)**: Core domain logic — `BaseSegmenter` ABC, `CellposeAdapter`, `LabelProcessor`, `SegmentationEngine`. No UI dependencies. Build now.
- **Module 3b (napari Viewer)**: UI/adapter layer — launches napari, integrates cellpose-napari plugin, imports labels back. Optional `percell3[napari]` dependency. Build next.

## Why This Approach

### Moving away from ImageJ ROIs (PerCell 2 approach)

PerCell 2 saved Cellpose output as ImageJ-formatted ROI lists for use with downstream ImageJ macros. PerCell 3's architecture is fundamentally different:

- **OME-Zarr for pixel data** — label images are stored as int32 zarr arrays, not ROI polygons
- **SQLite for cell properties** — centroid, bbox, area, perimeter, circularity live in a queryable database
- **Python-native pipeline** — no Java/ImageJ bridge needed

ImageJ ROIs are polygonal outlines that require rasterization to become label images. This adds complexity, potential accuracy loss, and an unnecessary format conversion. The native format for PerCell 3 is integer label images, which is exactly what Cellpose produces.

### Cellpose output format: `_seg.npy` for GUI, direct API for automated

**Automated path**: Cellpose `model.eval()` returns numpy masks directly. No file I/O. Fastest path.

**GUI path (napari)**: Labels come directly from napari's label layer as numpy arrays. No file intermediate needed.

**GUI path (native Cellpose fallback)**: Import `_seg.npy` files that Cellpose GUI auto-creates. Contains masks + parameter metadata.

TIFF/PNG export is available on-demand from stored zarr labels but not auto-generated.

### napari over ImageJ/FIJI

napari is the right viewer for PerCell 3 because:
- **Python-native** — speaks numpy/dask/zarr natively (same stack as PerCell 3)
- **Label layers** — first-class integer label image support with overlay, colormap, toggle
- **Manual editing** — paint, erase, fill, undo/redo on labels
- **OME-Zarr support** — loads PerCell 3 experiment data directly via `napari-ome-zarr`
- **cellpose-napari plugin** — run Cellpose inside napari with live parameter tuning
- **Multi-channel overlay** — view DAPI + GFP + segmentation masks simultaneously

### Split architecture: engine (3a) before viewer (3b)

The headless segmentation engine and the napari viewer are separate concerns:
- Engine = domain logic: read image -> segment -> write labels -> extract cells
- Viewer = UI layer: launch napari -> user interacts -> import results

Building the engine first because:
1. Hexagonal architecture: domain logic never depends on UI
2. 100% testable without Qt/napari (runs in CI)
3. napari module reuses engine components (LabelProcessor, ExperimentStore methods)
4. Workflow module (Module 6) calls SegmentationEngine for batch automation
5. Automated `percell3 segment` works day one; napari follows

## Key Decisions

1. **Primary segmentation output**: Integer label images in zarr + cell properties in SQLite. No auto-export. TIFF/CSV export on demand.

2. **Primary GUI**: napari with cellpose-napari plugin (preferred). Native Cellpose GUI supported as fallback via `_seg.npy` import.

3. **Automated path**: Direct Cellpose Python API (`model.eval()`). No intermediate files.

4. **No more ImageJ ROIs**: PerCell 3 stores labels natively as int32 zarr arrays. ROI rasterization is an unnecessary detour. napari replaces ImageJ/FIJI for manual label editing.

5. **Module split**: Core engine (3a, no UI deps, build now) + napari viewer (3b, optional dep, build next).

6. **napari is optional**: `pip install percell3[napari]`. Core segmentation works without it.

## Resolved Questions

1. **Q: Should we build napari module before segmentation engine?**
   A: No. The engine is domain logic (hexagonal core). napari is a UI adapter layer. Engine first, viewer second. The engine is the foundation both paths need.

2. **Q: What about PerCell 2's ImageJ ROI workflow?**
   A: Replaced by napari label layers + zarr storage. ROI rasterization adds complexity with no benefit in PerCell 3's architecture.

3. **Q: Auto-export TIFFs/CSVs after segmentation?**
   A: No. Store in zarr + SQLite only. Export on demand via `percell3 export`.

4. **Q: Which Cellpose output format for GUI workflow?**
   A: napari label layer (numpy array) for napari path. `_seg.npy` for native Cellpose GUI fallback. Both convert to int32 labels for zarr storage.

## Cellpose Output Format Comparison (Reference)

| Format | Source | Pros | Cons | PerCell 3 fit |
|--------|--------|------|------|---------------|
| Direct API (numpy masks) | `model.eval()` | Fastest, no I/O | Automated only | Best for headless |
| napari label layer | cellpose-napari plugin | Direct numpy, editable | Requires napari | Best for GUI |
| `_seg.npy` | Cellpose GUI auto-save | Has masks + params | Requires file import | Good fallback |
| Label TIFF/PNG | Manual export | Universal format | Manual step, loses params | Supported for import |
| ImageJ ROI zip | Cellpose export | ImageJ-compatible | Needs rasterization, lossy | Not recommended |
| Outlines text | Cellpose export | Lightweight | Needs rasterization | Not supported |

## Scope for Module 3a (Segmentation Engine — Build Now)

- `BaseSegmenter` ABC with `segment()` method
- `SegmentationParams` frozen dataclass
- `CellposeAdapter` wrapping Cellpose with model caching + lazy import
- `LabelProcessor` extracting cell properties via regionprops
- `SegmentationEngine` orchestrating the pipeline
- `RoiImporter` for importing pre-existing labels (`_seg.npy`, TIFF)
- CLI command: `percell3 segment -e exp --channel DAPI --model cyto3`
- No napari, no Qt, no GUI dependencies

## Scope for Module 3b (napari Viewer — Build Next)

- Launch napari with experiment loaded from zarr
- cellpose-napari plugin configuration
- Label import callback: napari label layer -> ExperimentStore
- Manual label editing workflow
- Native Cellpose GUI fallback (launch + import `_seg.npy`)
- Optional dependency: `percell3[napari]`
