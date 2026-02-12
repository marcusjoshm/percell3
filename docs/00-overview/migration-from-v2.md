# Migration from PerCell 2 to PerCell 3

## Feature Mapping

| PerCell 2 Feature | PerCell 3 Equivalent | Module |
|---|---|---|
| Cellpose segmentation | Cellpose adapter (same tool, new data layer) | 3 |
| Intensity-based cell grouping | Built-in plugin: intensity_grouping | 5 |
| Otsu thresholding | Thresholding engine (Otsu, adaptive, manual) | 4 |
| Particle analysis (ImageJ) | Measurement engine (Python-native) | 4 |
| ImageJ macro execution | Optional adapter (not required for core) | -- |
| Auto image preprocessing | Import pipeline handles dtype/bit-depth | 2 |
| Directory-based data organization | ExperimentStore + SQLite queries | 1 |
| config.json | SQLite experiment.db | 1 |
| Advanced workflow builder | DAG engine (more powerful) | 6 |
| Cleanup utility | Unnecessary — OME-Zarr compression | -- |
| Interactive menu | Click CLI + optional Textual TUI | 7 |
| CSV results at end of pipeline | SQL measurements queryable anytime | 1 |

## Data Migration Path

PerCell 3 includes a TIFF directory importer (Module 2) that understands
PerCell 2's directory structure:

```
experiment_dir/              # PerCell 2 layout
├── condition_1/
│   ├── timepoint_1/
│   │   ├── region_1/
│   │   │   ├── DAPI.tif
│   │   │   ├── GFP.tif
│   │   │   └── RFP.tif
│   │   └── region_2/
│   └── timepoint_2/
└── condition_2/
```

The TIFF importer reads this structure and writes it into a .percell directory:
- Each TIFF becomes a channel slice in the OME-Zarr store
- Directory names become condition/timepoint/region records in SQLite
- Channel names parsed from filenames

## What You Lose (Intentionally)

- **Individual cell TIFF files**: PerCell 2 extracts each cell as a separate TIFF.
  PerCell 3 keeps cells as label regions in a single label image. Individual cell
  images can be extracted on-demand via array slicing.

- **ImageJ macro integration**: PerCell 2 calls ImageJ for thresholding and
  particle analysis. PerCell 3 replaces these with Python-native equivalents
  (scikit-image). ImageJ can still be used via napari or as an optional adapter.

- **Filesystem as database**: No more encoding metadata in directory names.
  SQL queries replace filesystem traversal.

## What You Gain

- **Non-linear workflow**: Measure any channel at any time without re-running the pipeline
- **Compressed storage**: OME-Zarr with Blosc compression vs thousands of uncompressed TIFFs
- **Multi-format import**: LIF files directly, no manual export from LAS X
- **Plugin system**: Add custom analysis without modifying core code
- **Queryable results**: SQL queries instead of parsing CSV files
- **napari integration**: OME-Zarr files open directly in napari for visualization
