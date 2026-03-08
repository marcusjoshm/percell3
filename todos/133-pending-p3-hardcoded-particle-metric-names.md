---
status: pending
priority: p3
issue_id: "133"
tags: [code-review, architecture, code-quality]
dependencies: []
---

# Hardcoded particle metric names in select_measurements

## Problem Statement

`select_measurements()` has hardcoded particle metric name filtering logic. A shared `PARTICLE_SUMMARY_METRICS` constant exists in `src/percell3/core/constants.py`, but `queries.py` does not use it — instead it has its own hardcoded string literal list.

## Findings

- **Found by:** kieran-python-reviewer
- **Verified:** 2026-03-08
- `src/percell3/core/constants.py` correctly defines `PARTICLE_SUMMARY_METRICS` (11 metrics)
- `src/percell3/core/queries.py:781-785` has a hardcoded string literal with only 8 of the 11 metrics:
  - Hardcoded: `particle_count`, `total_particle_area`, `mean_particle_area`, `max_particle_area`, `particle_coverage_fraction`, `mean_particle_mean_intensity`, `mean_particle_integrated_intensity`, `total_particle_integrated_intensity`
  - Missing from hardcoded list: `total_particle_area_pixels`, `mean_particle_area_pixels`, `max_particle_area_pixels`
- This means scoped queries (e.g., `scope='mask_inside'`) will incorrectly exclude the `*_pixels` particle metrics
- Additionally, metric names like `"mean_intensity"`, `"area_pixels"`, `"circularity"` appear as column names/field names across many files (schema columns, model fields, plugin CSV headers) — these are domain property names, not the same concern as the query filtering bug

## Proposed Solutions

### Solution A: Use constants.PARTICLE_SUMMARY_METRICS in select_measurements (Recommended)

Replace the hardcoded string literal in `queries.py:781-785` with a reference to `constants.PARTICLE_SUMMARY_METRICS`.

**Pros:** Single source of truth, fixes the 3 missing metrics
**Cons:** Minor import addition
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] `select_measurements` uses `PARTICLE_SUMMARY_METRICS` from constants
- [ ] All 11 particle metrics correctly included in scope filter

## Technical Details

- **File:** `src/percell3/core/queries.py:781-785` — hardcoded metric list (should use constants)
- **File:** `src/percell3/core/constants.py` — canonical `PARTICLE_SUMMARY_METRICS` list
- **Related:** todo 122 (layering violation)
