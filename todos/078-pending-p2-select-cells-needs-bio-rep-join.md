---
status: pending
priority: p2
issue_id: "078"
tags: [plan-review, architecture, api-design]
dependencies: []
---

# select_cells() Needs Bio Rep JOIN to Include bio_rep_name in Results

## Problem Statement

After Phase 2, a CellRecord alone doesn't tell you which biological replicate it belongs to. `select_cells()` needs to JOIN biological_replicates and include `bio_rep_name` in results.

## Findings

- **Python reviewer**: "Currently select_cells() returns condition_name and region_name. After Phase 2, it should also return bio_rep_name."
- Currently `queries.py` `select_cells()` JOINs regions and conditions. Must add bio_reps JOIN.

## Proposed Solutions

### A) Update select_cells() to LEFT JOIN biological_replicates

Add a LEFT JOIN from fovs to biological_replicates via `fovs.bio_rep_id` and include `bio_rep_name` in the SELECT clause and result dicts.

- **Pros**: Complete cell provenance in query results, enables downstream grouping.
- **Cons**: Slightly wider result rows.
- **Effort**: Small.
- **Risk**: Low.

### B) Add separate get_bio_rep_for_fov() lookup

Keep select_cells() unchanged. Add a helper method to look up bio_rep from FOV.

- **Pros**: Minimal change to existing query.
- **Cons**: N+1 query pattern if caller needs bio_rep for many cells.
- **Effort**: Small.
- **Risk**: Medium (performance).

## Technical Details

Current `select_cells()` SQL structure (queries.py):
```sql
SELECT c.cell_id, c.label, r.name AS region_name, cond.name AS condition_name, ...
FROM cells c
JOIN regions r ON c.region_id = r.region_id
JOIN conditions cond ON r.condition_id = cond.condition_id
```

After Phase 2, should become:
```sql
SELECT c.cell_id, c.label, f.name AS fov_name, cond.name AS condition_name,
       br.name AS bio_rep_name, ...
FROM cells c
JOIN fovs f ON c.fov_id = f.fov_id
JOIN conditions cond ON f.condition_id = cond.condition_id
LEFT JOIN biological_replicates br ON f.bio_rep_id = br.bio_rep_id
```

Also affects:
- `get_measurement_pivot()` — should include bio_rep column
- Export CSV — should include bio_rep column
- Any downstream code that iterates cell results

## Acceptance Criteria

- [ ] `select_cells()` returns `bio_rep_name` in result dicts
- [ ] `get_measurement_pivot()` includes bio_rep column
- [ ] Export CSV includes bio_rep column
- [ ] LEFT JOIN used (not INNER JOIN) so NULL bio_rep_id doesn't exclude rows

## Work Log

- 2026-02-17 — Identified by Python reviewer during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
