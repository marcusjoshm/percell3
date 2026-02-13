---
title: "Implement IO Module: Token Scanner + Import Engine for TIFF"
type: feat
date: 2026-02-12
---

# Implement IO Module: Token Scanner + Import Engine for TIFF

## Overview

Build Module 2 (percell3.io) — a two-phase import system that scans TIFF directories, lets users map the discovered structure to experiment concepts, and executes imports into ExperimentStore. Import plans are serializable to YAML for reproducibility. TIFF-only for v1; architecture supports future LIF/CZI/FLIM readers.

## Problem Statement

PerCell 2's IO was fragile: TIFF-only with hardcoded filename regex, no preview of what would be imported, no channel name mapping, no Z-projection support, and no incremental imports. Users had to run a preprocessing script to normalize filenames before import. Adding a new microscope's naming convention required code changes.

PerCell 3 needs an IO module that:
- Scans directories and parses filenames with configurable token patterns
- Shows a preview of what was found before reading any pixel data
- Lets users map tokens to named channels/conditions/regions
- Applies configurable transforms (MIP, etc.) during import
- Supports incremental imports (add regions/timepoints to existing experiments)
- Produces a reproducible YAML record of every import

## Proposed Solution

**Token Scanner + Import Plan** architecture (from brainstorm):

1. **Scan**: `FileScanner.scan(path, token_config) -> ScanResult` — walks directory, tokenizes filenames, groups by dimensions
2. **Plan**: User creates an `ImportPlan` from the ScanResult — assigns condition/channel/region names, transforms
3. **Execute**: `ImportEngine.execute(plan, store) -> ImportResult` — reads files, applies transforms, writes to ExperimentStore
4. **Serialize**: `ImportPlan.to_yaml()` / `ImportPlan.from_yaml()` — reproducible record

## Technical Approach

### Architecture

```
src/percell3/io/
├── __init__.py              # Public API: scan, import_into, models
├── scanner.py               # FileScanner — directory walk + token parsing
├── models.py                # TokenConfig, ScanResult, ImportPlan, ImportResult, etc.
├── engine.py                # ImportEngine — reads files, applies transforms, writes to store
├── tiff.py                  # TIFF reading + metadata extraction via tifffile
├── transforms.py            # Z-projection transforms (MIP, sum, mean)
├── serialization.py         # ImportPlan YAML serialization
└── _sanitize.py             # Name sanitization helpers

tests/test_io/
├── conftest.py              # Fixtures: mock TIFF dirs, experiment stores
├── test_scanner.py          # FileScanner tests
├── test_models.py           # Data model tests
├── test_engine.py           # ImportEngine integration tests
├── test_tiff.py             # TIFF reading tests
├── test_transforms.py       # Z-projection tests
├── test_serialization.py    # YAML round-trip tests
└── test_sanitize.py         # Name sanitization tests
```

### Data Models (`models.py`)

```python
@dataclass(frozen=True)
class TokenConfig:
    """Configurable token patterns for filename parsing."""
    channel: str = r"_ch(\d+)"
    timepoint: str = r"_t(\d+)"
    z_slice: str = r"_z(\d+)"
    region: str | None = None  # optional — derived from remaining text if None

@dataclass(frozen=True)
class DiscoveredFile:
    """A single file with its parsed tokens."""
    path: Path
    tokens: dict[str, str]   # {"channel": "00", "timepoint": "00", "z": "03"}
    shape: tuple[int, ...]   # from TIFF header (no pixel read)
    dtype: str               # "uint8", "uint16", "float32"
    pixel_size_um: float | None

@dataclass(frozen=True)
class ScanResult:
    """What the scanner found — presented to user for review."""
    source_path: Path
    files: list[DiscoveredFile]
    channels: list[str]       # unique channel token values
    regions: list[str]        # unique region identifiers
    timepoints: list[str]     # unique timepoint values
    z_slices: list[str]       # unique z values (empty if 2D)
    pixel_size_um: float | None
    warnings: list[str]

@dataclass(frozen=True)
class ChannelMapping:
    """Map a discovered channel token to a named channel."""
    token_value: str
    name: str
    role: str | None = None
    color: str | None = None

@dataclass(frozen=True)
class ZTransform:
    """How to handle Z-stacks."""
    method: str  # "mip", "sum", "mean", "keep", "slice"
    slice_index: int | None = None

@dataclass
class ImportPlan:
    """Complete specification for an import."""
    source_path: Path
    condition: str
    channel_mappings: list[ChannelMapping]
    region_names: dict[str, str]  # token -> display name
    z_transform: ZTransform
    pixel_size_um: float | None
    token_config: TokenConfig
    def to_yaml(self, path: Path) -> None: ...
    @classmethod
    def from_yaml(cls, path: Path) -> ImportPlan: ...

@dataclass(frozen=True)
class ImportResult:
    """What happened during import."""
    regions_imported: int
    channels_registered: int
    images_written: int
    skipped: int  # already existed
    warnings: list[str]
    elapsed_seconds: float
```

### Key Integration Points

**ExperimentStore methods called by ImportEngine:**
- `store.add_channel(name, role, color)` — register channels (idempotent: catch DuplicateError)
- `store.add_condition(name)` — register condition (idempotent)
- `store.add_region(name, condition, width, height, pixel_size_um, source_file)` — register region
- `store.write_image(region, condition, channel, data)` — write 2D numpy array
- `store.get_channels()` / `store.get_conditions()` / `store.get_regions()` — check what exists

**Name sanitization constraint:**
Names must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$`. The `_sanitize.py` module provides:
```python
def sanitize_name(value: str, fallback: str = "unnamed") -> str:
    """Sanitize a string for use as a channel/condition/region name.

    Replaces spaces with underscores, strips invalid chars,
    falls back if result is empty.
    """
```

**ndim constraint:**
`write_image()` requires 2D `(Y, X)` arrays. Z-stacks must be projected in `transforms.py` before writing.

### Implementation Phases

#### Phase 1: Data Models + Scanner (~30 min)

Files: `models.py`, `scanner.py`, `_sanitize.py`, `__init__.py`

- Define all frozen dataclasses: TokenConfig, DiscoveredFile, ScanResult, ChannelMapping, ZTransform, ImportPlan, ImportResult
- Implement `FileScanner.scan(path, token_config) -> ScanResult`:
  - Walk directory for `.tif`/`.tiff` files
  - Parse filename tokens using regex from TokenConfig
  - Extract shape/dtype/pixel_size from TIFF headers (via `tifffile.TiffFile`, no pixel read)
  - Group files by channel/region/timepoint/z
  - Report warnings (inconsistent shapes, missing tokens, etc.)
- Implement `sanitize_name()` helper
- Tests: `test_scanner.py`, `test_models.py`, `test_sanitize.py`

**Tests (~15):**
- Token parsing: standard patterns (`_ch00_t00_z00`), custom patterns
- Directory scanning: single-channel flat, multi-channel, with timepoints, with z-slices
- Edge cases: no matching files, inconsistent shapes, missing tokens
- Name sanitization: spaces, special chars, empty input, already-valid

#### Phase 2: TIFF Reading + Transforms (~25 min)

Files: `tiff.py`, `transforms.py`

- Implement `read_tiff(path) -> np.ndarray` — thin wrapper around `tifffile.imread`
- Implement `read_tiff_metadata(path) -> dict` — pixel size, shape, dtype from TIFF tags
  - Try OME-XML first, then ImageJ metadata, then resolution tags, then None
- Implement Z-projection transforms:
  - `project_mip(stack) -> np.ndarray` — `np.max(stack, axis=0)`
  - `project_sum(stack) -> np.ndarray` — `np.sum(stack, axis=0)`
  - `project_mean(stack) -> np.ndarray` — `np.mean(stack, axis=0).astype(stack.dtype)`
  - `apply_z_transform(files, transform) -> np.ndarray` — loads z-slices, applies method
- Tests: `test_tiff.py`, `test_transforms.py`

**Tests (~10):**
- Read single TIFF, multi-page TIFF
- Metadata extraction from tags
- MIP/sum/mean on synthetic 3D stack
- Slice selection
- dtype preservation after projection

#### Phase 3: Import Engine (~30 min)

Files: `engine.py`

- Implement `ImportEngine.execute(plan, store, progress_callback?) -> ImportResult`:
  1. Register channels (skip existing via try/except DuplicateError)
  2. Register condition (skip existing)
  3. For each region in plan:
     a. Check if region already exists → skip and warn
     b. Group files by channel
     c. If z_slices present, apply Z-transform per channel
     d. Read 2D image data per channel
     e. Register region with width/height/pixel_size/source_file
     f. Write each channel image via `store.write_image()`
  4. Report ImportResult with counts and warnings
- Handle incremental imports: check existing channels/conditions/regions, skip duplicates
- Tests: `test_engine.py`

**Tests (~12):**
- Single-channel single-region import
- Multi-channel import
- Multi-region import
- Import with Z-projection (MIP)
- Incremental import (add region to existing experiment)
- Incremental import (add timepoint)
- Channel mapping (rename ch00 → DAPI)
- Region renaming
- Progress callback called correctly
- Duplicate region skipped with warning
- Invalid source path raises error
- Empty directory raises error

#### Phase 4: YAML Serialization (~15 min)

Files: `serialization.py`, update `models.py`

- Implement `ImportPlan.to_yaml(path)` — write plan as YAML with all fields
- Implement `ImportPlan.from_yaml(path)` — load plan from YAML, validate
- YAML format uses PyYAML (already in deps via workflow module's pyyaml)
- Tests: `test_serialization.py`

**Tests (~6):**
- Round-trip: create plan → to_yaml → from_yaml → assert equal
- Load from file with all fields
- Load with missing optional fields (defaults applied)
- Invalid YAML raises clear error
- Path serialization (absolute → relative to source)
- Token config serialization

#### Phase 5: Public API + Integration (~15 min)

Files: `__init__.py`, `conftest.py`

- Wire up public API in `__init__.py`:
  ```python
  from percell3.io.scanner import FileScanner
  from percell3.io.engine import ImportEngine
  from percell3.io.models import (
      TokenConfig, ScanResult, ImportPlan, ImportResult,
      ChannelMapping, ZTransform, DiscoveredFile,
  )
  ```
- Add convenience function:
  ```python
  def scan(path: Path, token_config: TokenConfig | None = None) -> ScanResult:
      """Scan a directory for TIFF files. Convenience wrapper."""
      return FileScanner().scan(path, token_config or TokenConfig())
  ```
- Create `tests/test_io/conftest.py` with shared fixtures
- Run full test suite to verify no regressions

**Tests (~3):**
- End-to-end: scan directory → create plan → execute → verify store contents
- End-to-end with YAML round-trip
- Verify all public names importable from `percell3.io`

## Acceptance Criteria

### Functional
- [x] `FileScanner.scan()` discovers TIFF files and parses tokens correctly
- [x] `ScanResult` shows channels, regions, timepoints, z-slices found
- [x] `ImportEngine.execute()` writes all images into ExperimentStore
- [x] Channel mapping works (rename ch00 → "DAPI")
- [x] Region renaming works
- [x] Z-projection (MIP, sum, mean, slice) produces correct 2D output
- [x] Incremental imports: add regions/timepoints to existing experiment
- [x] Duplicate detection: skip existing regions with warning
- [x] `ImportPlan.to_yaml()` / `from_yaml()` round-trips correctly
- [x] Progress callback fires with correct counts

### Data Safety
- [x] Names sanitized before passing to ExperimentStore
- [x] 3D arrays never passed to `write_image()` — always projected first
- [x] Invalid source paths raise clear errors early
- [x] Empty directories produce meaningful error, not crash

### Quality
- [x] Type hints on all public functions
- [x] Google-style docstrings
- [x] Frozen dataclasses for value objects
- [x] All `X | None` style (no `Optional[X]`)
- [x] No direct Zarr/SQLite access — all through ExperimentStore

### Testing
- [x] All existing 204 tests still pass
- [x] ~60 new IO module tests (80 actual)
- [x] Total test count ~265 (284 actual)

## Dependencies & Risks

**Dependencies:**
- Core module (Module 1): complete and tested
- `tifffile>=2023.7`: already in pyproject.toml
- `pyyaml>=6.0`: already in pyproject.toml (workflow extra, but move to core deps)

**Risks:**

1. **Token pattern edge cases.** Different microscopes use different naming conventions. Mitigate: make patterns configurable, test with multiple real-world examples, provide sensible defaults.

2. **TIFF metadata inconsistency.** Not all TIFFs have pixel size metadata. Mitigate: graceful fallback to None, let user override in ImportPlan.

3. **Large file performance.** Scanning directories with thousands of TIFFs could be slow. Mitigate: scanner only reads TIFF headers (not pixels), which is fast. ImportEngine reads pixels one-at-a-time.

4. **PyYAML dependency scope.** Currently in `[workflow]` extras. Either move to core deps or add to `[io]` extras. Low risk — PyYAML is a standard dependency.

## Future Considerations

- **LIF reader**: Add `LifScanner` that produces `ScanResult` from LIF XML metadata. Reuses `ImportEngine`.
- **CZI reader**: Same pattern via `aicspylibczi`.
- **FLIM .bin reader**: Separate reader producing derived channels (lifetime maps, phasor).
- **GUI integration**: `ScanResult` is the data source for a file mapping UI. `ImportPlan` is what the UI produces.
- **Pyramid generation**: Currently writes single-resolution. Could add downsampled levels in future.

## References

- Brainstorm: `docs/brainstorms/2026-02-12-io-module-design-brainstorm.md`
- IO spec: `docs/02-io/spec.md`
- IO conventions: `docs/02-io/CLAUDE.md`
- IO acceptance tests: `docs/02-io/acceptance-tests.md`
- Core ExperimentStore: `src/percell3/core/experiment_store.py`
- Core zarr_io: `src/percell3/core/zarr_io.py`
- Name validation: `src/percell3/core/experiment_store.py:7-26`
- Security patterns: `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
