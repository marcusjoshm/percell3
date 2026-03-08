---
status: pending
priority: p3
issue_id: "133"
tags: [code-review, architecture, code-quality]
dependencies: []
---

# Hardcoded particle metric names in select_measurements

## Problem Statement

`select_measurements()` has hardcoded particle metric name filtering logic. If `PARTICLE_SUMMARY_METRICS` in `particle_analyzer.py` changes, the query logic may not filter correctly.

## Findings

- **Found by:** kieran-python-reviewer
- Metric names like `particle_count`, `total_particle_area` are referenced in multiple places
- No single constant definition shared between query and analysis code (partly due to the layering violation in todo 122)
- Adding a new particle metric requires updating multiple locations

## Proposed Solutions

### Solution A: Define metric categories in a shared constants module

Create a lightweight constants module in `percell3.core` that defines metric categories without importing analysis code.

**Pros:** Single source of truth without layering violations
**Cons:** Minor organizational change
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] Metric names defined in one place
- [ ] No hardcoded metric strings scattered across modules

## Technical Details

- **File:** `src/percell3/core/queries.py` — metric filtering
- **File:** `src/percell3/measure/particle_analyzer.py` — `PARTICLE_SUMMARY_METRICS`
- **Related:** todo 122 (layering violation)
