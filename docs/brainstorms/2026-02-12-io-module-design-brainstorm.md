---
title: "IO Module Design for PerCell 3"
date: 2026-02-12
topic: io-module
status: decided
---

# IO Module Design Brainstorm

## What We're Building

A two-phase import system for microscopy data that scans source files, lets the user interactively map the discovered structure to experiment concepts (conditions, regions, channels, timepoints), and then executes the import into ExperimentStore. The import plan can be serialized to YAML for reproducibility.

## Why This Approach

The old PerCell had three pain points:
1. **Input fragility** — TIFF-only, brittle filename regex, required a preprocessing script to normalize filenames before import.
2. **Mapping complexity** — Conditions derived from directory names with no override, channels identified by `_ch00` tokens with no name mapping, Z-stacks required a separate plugin for MIP.
3. **No preview** — You couldn't see what would be imported before committing. Errors discovered only after a long import.

The new approach fixes all three:
- **Configurable token scanner** replaces brittle regex with user-tunable patterns.
- **Two-phase scan/import** with an explicit ImportPlan lets users review and correct mappings before any data is written.
- **YAML serialization** of the ImportPlan makes imports reproducible and version-controllable.

## Chosen Approach: Token Scanner + Import Plan (Hybrid with YAML Manifest)

### Architecture

```
Source Files                    ExperimentStore
     │                               ▲
     ▼                               │
┌─────────────┐   ┌────────────┐   ┌──────────────┐
│ FileScanner  │──▶│ ScanResult │──▶│ ImportEngine  │
│ (tokenize)   │   │ (preview)  │   │ (execute)     │
└─────────────┘   └─────┬──────┘   └──────▲───────┘
                        │                  │
                   CLI/GUI builds    ┌─────┴──────┐
                        │            │ ImportPlan  │
                        ▼            │ (mapping +  │
                   ┌─────────────┐   │  transforms)│
                   │ User Review │──▶└─────┬──────┘
                   └─────────────┘         │
                                     serialize/load
                                           │
                                     ┌─────▼──────┐
                                     │ YAML file   │
                                     │ (optional)  │
                                     └────────────┘
```

### Core Data Flow

1. **Scan**: `FileScanner.scan(path, token_config) -> ScanResult`
   - Walks directory tree, tokenizes filenames
   - Groups files by discovered dimensions (channel, region, timepoint, z-slice)
   - Reports what it found: N files, M channels, K regions, etc.
   - No data is read — only file paths and parsed tokens

2. **Plan**: User reviews ScanResult, creates ImportPlan
   - Map token values to human names (ch00 → "DAPI", ch01 → "GFP")
   - Assign condition names
   - Choose transforms (Z-stack → MIP, or keep raw)
   - Set pixel size if not in metadata
   - CLI/GUI provides the mapping UI; IO module just consumes the plan

3. **Execute**: `ImportEngine.execute(plan, store, progress_callback?) -> ImportResult`
   - Reads files according to plan
   - Applies transforms (MIP, dtype conversion)
   - Writes into ExperimentStore via write_image()
   - Supports incremental imports (skips existing regions/channels)
   - Returns ImportResult with counts, warnings, elapsed time

4. **Serialize** (optional): `ImportPlan.to_yaml(path)` / `ImportPlan.from_yaml(path)`
   - Reproducible record of what was imported and how
   - Can be committed alongside the .percell directory

### Key Data Models

```python
@dataclass
class TokenConfig:
    """Configurable token patterns for filename parsing."""
    channel: str = r"_ch(\d+)"       # or r"_([A-Za-z]+)\.tif$"
    timepoint: str = r"_t(\d+)"
    z_slice: str = r"_z(\d+)"
    region: str = r"_r(\d+)"         # optional — may derive from remaining text
    # Users can override these per microscope setup

@dataclass
class DiscoveredFile:
    """A single file with its parsed tokens."""
    path: Path
    tokens: dict[str, str]           # {"channel": "00", "timepoint": "00", "z": "03"}
    metadata: dict                   # pixel size, dtype, shape from TIFF tags

@dataclass
class ScanResult:
    """What the scanner found — presented to user for review."""
    source_path: Path
    files: list[DiscoveredFile]
    channels: list[str]              # unique channel token values found
    regions: list[str]               # unique region identifiers
    timepoints: list[str]            # unique timepoint values
    z_slices: list[str]              # unique z values (empty if 2D)
    pixel_size_um: float | None      # from TIFF metadata if consistent
    warnings: list[str]              # e.g. "inconsistent pixel sizes across files"

@dataclass
class ChannelMapping:
    """Map a discovered channel token to a named channel."""
    token_value: str                 # "00"
    name: str                        # "DAPI"
    role: str | None = None          # "nucleus", "signal"
    color: str | None = None         # "#0000FF"

@dataclass
class ZTransform:
    """How to handle Z-stacks."""
    method: str                      # "mip", "sum", "mean", "keep", "slice"
    slice_index: int | None = None   # if method == "slice"

@dataclass
class ImportPlan:
    """Complete specification for an import operation."""
    source_path: Path
    condition: str                   # condition name for this import
    channel_mappings: list[ChannelMapping]
    region_names: dict[str, str]     # token -> display name (optional rename)
    z_transform: ZTransform
    pixel_size_um: float | None      # override if not in metadata
    token_config: TokenConfig        # how filenames were parsed
    # Serialization
    def to_yaml(self, path: Path) -> None: ...
    @classmethod
    def from_yaml(cls, path: Path) -> ImportPlan: ...
```

### File Structure

```
src/percell3/io/
├── __init__.py              # Public API: scan, import_into, ScanResult, ImportPlan
├── scanner.py               # FileScanner — directory walking + token parsing
├── models.py                # TokenConfig, ScanResult, ImportPlan, etc.
├── engine.py                # ImportEngine — reads files, applies transforms, writes to store
├── tiff.py                  # TIFF-specific reading and metadata extraction
├── transforms.py            # Z-projection transforms (MIP, sum, mean)
└── serialization.py         # ImportPlan YAML serialization
```

## Key Decisions

1. **TIFF-only for v1.** No LIF/CZI until proprietary format support is needed. Architecture supports adding readers later — each new format just needs a scanner that produces a `ScanResult`.

2. **Two-phase scan/import.** Scanner returns a ScanResult (no data read). User creates an ImportPlan. ImportEngine executes it. Clean separation for CLI and future GUI.

3. **Token-based filename parsing with configurable patterns.** Default patterns cover common microscope exports (`_ch00`, `_t00`, `_z00`). Users can override per microscope setup.

4. **Configurable Z-projection.** User chooses per-import: MIP, sum, mean, keep raw stack, or take a single slice. Applied during import, not as a separate step.

5. **Incremental imports are first-class.** ImportEngine checks for existing channels/regions/conditions and skips them. Users can add new regions or timepoints to existing experiments.

6. **ImportPlan serializable to YAML.** Optional but encouraged for reproducibility. The YAML file documents exactly what was imported and how.

7. **FLIM (.bin) is a separate future reader.** Not designed for now. The architecture supports it — a FLIM scanner would produce its own ScanResult with derived channels (lifetime maps, phasor components).

8. **No tile stitching.** Microscope software handles stitching. IO module imports already-stitched images.

## How Future Formats Plug In

When LIF/CZI support is needed:

```python
# lif_scanner.py
class LifScanner:
    def scan(self, path: Path) -> ScanResult:
        """Extract series/channels/metadata from LIF XML."""
        lif = LifFile(str(path))
        # ... build ScanResult from LIF metadata
        return scan_result
```

The `ImportEngine` doesn't change — it only consumes `ImportPlan` objects. The scanner produces the `ScanResult`, the user creates the `ImportPlan`, and the engine executes it. The engine needs a `read_image` callback or the plan references the reader to use.

Practically: `ImportPlan` would include a `reader: str` field ("tiff", "lif", "czi") and the engine dispatches to the appropriate reader function.

## Open Questions

*None — all resolved during brainstorming.*

## Comparison with Old PerCell

| Aspect | Old PerCell | PerCell 3 |
|--------|-------------|-----------|
| Formats | TIFF only, hardcoded | TIFF v1, extensible to LIF/CZI/FLIM |
| Filename parsing | Hardcoded regex, preprocessing script required | Configurable token patterns |
| Channel mapping | Numeric indices only | Named channels with color/role |
| Conditions | Parent directory name, no override | User-assigned in ImportPlan |
| Z-stacks | Separate plugin for MIP | Built-in configurable transform |
| Preview | None | ScanResult shows what will be imported |
| Incremental | Not supported | First-class — add regions/timepoints |
| Reproducibility | Not tracked | ImportPlan serialized to YAML |
| Metadata | TIFF tags only | TIFF tags + NGFF 0.4 in zarr |
