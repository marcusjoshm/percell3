# Open Questions

## Data Model
- How to handle timelapse data where cells move between frames? (tracking)
- Should we support 3D segmentation (Z-stacks) in v3.0 or defer to v3.1?
- How to handle multi-position/tiled/mosaic images from LIF files?

## FLIM-Phasor
- What's the input format for FLIM data? Separate files or embedded in LIF?
- Does FLIM-Phasor output per-cell metrics or per-pixel images (or both)?
- What parameters does the user need to configure for phasor analysis?

## Workflow
- Should workflows be YAML-defined or Python-defined or both?
- How to handle interactive steps (Cellpose GUI, ImageJ) in the DAG engine?

## Distribution
- PyPI package or conda package or both?
- How to handle GPL dependencies (readlif) for MIT-licensed core?
- Minimum Python version: 3.10 or 3.11?
