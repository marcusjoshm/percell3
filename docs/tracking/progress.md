# PerCell 3 — Progress Tracker

## Sprint Status

| Sprint | Module | Status | Milestone |
|--------|--------|--------|-----------|
| 1 | Core (ExperimentStore) | Not Started | Can store and retrieve images |
| 2 | IO (Format Readers) | Not Started | Can import real data |
| 3 | Segment (Cellpose) | Not Started | Can segment cells |
| 4 | Measure (Metrics) | Not Started | Can measure anything |
| 5a | Plugins | Not Started | Can extend with plugins |
| 5b | Workflow | Not Started | Can orchestrate steps |
| 6 | CLI | Not Started | Usable from command line |
| 7 | Integration & Polish | Not Started | Ready for real experiments |

## Milestone Checklists

### M1: Can store and retrieve images
- [ ] ExperimentStore.create() works
- [ ] ExperimentStore.open() works
- [ ] Can add channels, conditions, regions
- [ ] Can write numpy array as OME-Zarr
- [ ] Can read back as dask array
- [ ] SQLite schema created with WAL mode

### M2: Can import real data
- [ ] LIF reader imports multi-series files
- [ ] TIFF directory reader imports PerCell 2 layout
- [ ] Channel names and pixel sizes extracted from metadata
- [ ] All data written via ExperimentStore API

### M3: Can segment cells
- [ ] Cellpose adapter runs on any channel
- [ ] Label images stored in labels.zarr
- [ ] Cell records (centroid, bbox, area) in SQLite
- [ ] Segmentation run logged

### M4: Can measure anything
- [ ] Measure any channel using existing labels
- [ ] Built-in metrics: mean, max, integrated intensity
- [ ] Otsu thresholding produces masks
- [ ] Batch measurement across all regions/channels
- [ ] Pivot table export works

### M5: Can extend with plugins
- [ ] AnalysisPlugin ABC defined
- [ ] PluginRegistry discovers built-in plugins
- [ ] IntensityGrouping plugin works
- [ ] Colocalization plugin works
- [ ] Plugin results stored in ExperimentStore

### M6: Usable from command line
- [ ] percell3 create
- [ ] percell3 import
- [ ] percell3 segment
- [ ] percell3 measure
- [ ] percell3 export
- [ ] percell3 query
- [ ] Rich progress bars and tables

### M7: Ready for real experiments
- [ ] End-to-end test with real LIF data
- [ ] End-to-end test with PerCell 2 TIFF data
- [ ] Performance acceptable for typical experiment sizes
- [ ] All acceptance tests passing
- [ ] Error messages are user-friendly
