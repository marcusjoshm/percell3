---
title: Condensate Partitioning Ratio Plugin
type: feat
status: brainstormed
date: 2026-03-09
---

# Brainstorm: Condensate Partitioning Ratio Plugin

## What We're Building

A new PerCell 3 analysis plugin (`condensate_partitioning_ratio`) that measures the partitioning of individual condensates by comparing fluorescence intensity **inside** each particle (condensed phase) to fluorescence intensity in a **ring just outside** each particle (dilute phase).

**Core algorithm:**
1. Take particles from a condensed-phase threshold
2. Measure fluorescence intensity inside each particle (condensate)
3. Dilate each particle by `gap_pixels` (default 3px) to create an exclusion zone
4. Dilate again by `ring_pixels` (default 2px) to define the measurement ring
5. Measure fluorescence intensity in the outer ring only (dilute phase)
6. Report both measurements plus the partitioning ratio (condensate_mean / dilute_mean)

**Output:** Per-particle CSV with area (px and um2), mean intensity, integrated intensity for both phases, plus partitioning ratio column.

## Why This Approach

**Standalone plugin (Approach A)** — chosen over shared base class or extending bg_subtraction_core because:
- Self-contained, no coupling to split_halo internals
- bg_subtraction_core is conceptually about background *subtraction* (Gaussian peak detection), not ratio measurement
- Only 2 plugins would share a base class — premature abstraction per YAGNI
- Pattern duplication is ~100 lines of structural boilerplate (threshold resolution, per-cell iteration, CSV export), but these are stable patterns unlikely to change

**Why not extend split_halo:** Split_halo measures dilute phase per-cell (whole cell minus all particles). This plugin measures dilute phase per-particle (ring around each individual particle). Fundamentally different granularity.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Ring overlap between particles | Allow overlap | Only exclude other particles' *condensates* from each ring, not their rings. Simpler, and ring overlap doesn't bias the dilute measurement — it's still dilute phase in the overlapping region. |
| Ratio computation | Column in CSV: `condensate_mean / dilute_mean` | Single interpretable number per particle. User can compute other ratio variants from the raw columns. |
| Storage | CSV export only, no DB measurements | Keeps schema simple. Per-particle data doesn't fit the `measurements` table (keyed on cell_id, not particle_id). Matches split_halo pattern. |
| Channel handling | One measurement channel per plugin invocation | Simpler parameter schema. User runs plugin twice for two channels. Matches local_bg_subtraction pattern. |
| Edge particles (touching image boundary) | Measure available area, clip ring to image bounds | Don't discard particles just because their ring extends past the edge. Report actual measured area so user can filter if needed. |
| Background subtraction | None — raw intensities only | User's imaging conditions have high SNR and low background. For moderate/low SNR, the ratio `(S_c + B) / (S_d + B)` is compressed toward 1.0. Limitation documented; users with high background should consider bg subtraction as a future enhancement. |
| Exclusion from ring | Exclude other particles' condensate masks from ring | If particle B's condensate overlaps particle A's ring, that region is excluded from A's dilute measurement. Prevents condensed-phase signal from contaminating dilute measurement. |

## Parameters

```python
{
    "measurement_channel": str,      # required — channel to measure intensity in
    "particle_channel": str,         # required — channel whose particles define condensates
    "gap_pixels": int = 3,           # exclusion zone around particle (not measured); default 3 to clear PSF
    "ring_pixels": int = 2,          # measurement ring width beyond the gap
    "min_ring_pixels": int = 10,     # particles with ring area < this get NaN ratio
    "export_csv": bool = True,       # write per-particle CSV
}
```

## CSV Output Columns

```python
CSV_COLUMNS = [
    "particle_id",
    "cell_id",
    "cell_label",
    "fov_id",
    "fov_name",
    "condition",
    "bio_rep",
    "threshold_name",
    # Condensate (inside particle)
    "condensate_area_pixels",
    "condensate_area_um2",
    "condensate_mean_intensity",
    "condensate_integrated_intensity",
    # Dilute (outer ring)
    "dilute_area_pixels",
    "dilute_area_um2",
    "dilute_mean_intensity",
    "dilute_integrated_intensity",
    # Ratio
    "partitioning_ratio",   # condensate_mean / dilute_mean
]
```

## Algorithm Detail

### Two-Step Dilation Ring Construction

```
particle mask  →  dilate by gap_pixels  →  dilate by (gap_pixels + ring_pixels)
                  (inner boundary)          (outer boundary)

measurement_ring = outer_dilated & ~inner_dilated
```

For each particle in a cell:
1. Create single-particle binary mask from particle labels
2. Dilate by `gap_pixels` using `disk()` structuring element → inner boundary
3. Dilate by `gap_pixels + ring_pixels` → outer boundary
4. Ring = outer & ~inner
5. Clip ring to cell mask (particle must belong to a cell)
6. Exclude any other particles' condensate pixels from ring
7. If ring pixel count < `min_ring_pixels`, report NaN for dilute measurements and ratio
8. Otherwise, measure intensity in remaining ring pixels

### Exclusion Logic

```python
# For particle P in cell C:
particle_mask = (particle_labels == P)
all_other_particles = (particle_labels > 0) & ~particle_mask

inner = binary_dilation(particle_mask, disk(gap_pixels))
outer = binary_dilation(particle_mask, disk(gap_pixels + ring_pixels))
ring = outer & ~inner
ring = ring & cell_mask           # clip to cell boundary
ring = ring & ~all_other_particles  # exclude other condensates
```

## Plugin Structure

Following split_halo pattern:
- `info()` → name `"condensate_partitioning_ratio"`, version, description
- `required_inputs()` → `[SEGMENTATION, THRESHOLD]`
- `validate()` → check channels exist, cells exist, thresholds exist
- `get_parameter_schema()` → measurement_channel, particle_channel, gap_pixels, ring_pixels, min_ring_pixels, export_csv
- `run()` → per-FOV → per-cell → per-particle processing, CSV export

### Threshold Resolution

Reuse split_halo's config-matrix-first pattern:
1. Try `store.get_fov_config(fov_id)` to find threshold IDs
2. Fall back to `source_fov_id` matching if config doesn't specify

### File Locations

- Plugin: `src/percell3/plugins/builtin/condensate_partitioning_ratio.py`
- Tests: `tests/test_plugins/test_condensate_partitioning_ratio.py`
- Auto-discovered by PluginRegistry (no registration needed)

## Resolved Questions

1. **Should the ring exclude other particles' rings or just their condensates?**
   → Just condensates. Ring-ring overlap is fine — overlapping regions are still dilute phase. Only condensed-phase pixels would bias the measurement. *(User rationale: simpler implementation, and the overlapping ring area is genuinely dilute phase.)*

2. **Should we report multiple ratio types (mean, integrated, area-normalized)?**
   → Report one ratio (mean/mean) as the primary column. Users can derive other ratios from the raw columns in the CSV. *(User rationale: keep output simple, raw data is there for custom analysis.)*

3. **Should this plugin also write to the SQLite measurements table?**
   → No, CSV only. The measurements table is keyed on cell_id, not particle_id. Per-particle data goes to CSV following the established split_halo pattern. *(User rationale: no schema changes, CSV is sufficient for downstream Prism analysis.)*

4. **Should background subtraction be applied before computing the ratio?**
   → No. User's imaging conditions have high SNR where background is negligible. Mathematically, for non-zero background B the ratio `(S_c + B) / (S_d + B)` is compressed toward 1.0, so this assumption only holds for high-SNR conditions. Documented as a known limitation. *(User rationale: imaging conditions have high SNR and low background; simplicity preferred for v1.)*

5. **What happens when a particle's ring has zero dilute pixels (e.g., completely overlapped by other particles)?**
   → Report NaN for dilute measurements and partitioning ratio. The CSV row is still emitted so the user can see it was measured but had no dilute area. *(Follows split_halo convention for empty regions.)*

## Red Team Resolutions

**Red team review:** `.workflows/brainstorm-research/condensate-partitioning-ratio/red-team--opus.md`

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Background subtraction dismissal compresses ratio toward 1.0 | CRITICAL | **Accepted limitation.** User's imaging has high SNR. Documented that raw ratio is only valid for high-SNR conditions. Future enhancement could add optional bg subtraction. |
| 2 | PSF bleedthrough into 2px ring contaminates dilute measurement | SERIOUS | **Mitigated.** Increased `gap_pixels` default from 2 to 3 to better clear the PSF. Documented as known limitation. |
| 3 | Per-particle dilute measurement has poor statistics for small rings | SERIOUS | **Mitigated.** Added `min_ring_pixels` parameter (default 10). Particles with ring area below threshold get NaN ratio. |
| 4 | Brainstorm contradicts research on bg_subtraction_core reuse | SERIOUS | **Acknowledged.** Consistent with decision not to apply bg subtraction. If bg subtraction is added later, reusing `estimate_background_gaussian()` is the obvious path. |
| 5 | No minimum ring area validation | SERIOUS | **Fixed.** Added `min_ring_pixels` parameter (see #3). |
| 6-10 | Ring overlap correlation, boilerplate estimate, area_um2 None handling, overconfident "no open questions", cross-channel implications | MINOR | **Batch-acknowledged.** Boilerplate estimate corrected to ~100 lines. |

## Known Limitations

1. **No background subtraction:** Raw intensity ratios are valid only for high-SNR imaging conditions. For moderate/low SNR, the ratio is systematically compressed toward 1.0. Consider adding bg subtraction as a future enhancement.
2. **PSF contamination:** The dilute-phase ring measurement includes PSF bleedthrough from the condensate, especially for small condensates. Increasing `gap_pixels` mitigates this but cannot eliminate it.
3. **Ring overlap correlation:** Adjacent particles share ring pixels, creating statistical correlation between their dilute measurements. Users doing per-cell summary statistics should be aware the effective sample size may be smaller than particle count.
4. **Cross-channel measurement:** When `measurement_channel` differs from `particle_channel`, the condensate boundary may not correspond to any structure in the measurement channel. The ratio is only biologically meaningful when the boundary is relevant for both channels.
5. **pixel_size_um may be None:** For imported images without calibration metadata, `area_um2` columns will report NaN.

## Open Questions

None — all questions resolved.

## Sources

- Research: `.workflows/brainstorm-research/condensate-partitioning-ratio/repo-research.md`
- Research: `.workflows/brainstorm-research/condensate-partitioning-ratio/context-research.md`
- Reference implementation: `src/percell3/plugins/builtin/split_halo_condensate_analysis.py`
- Core algorithms: `src/percell3/plugins/builtin/bg_subtraction_core.py`
- Plugin ABC: `src/percell3/plugins/base.py`
