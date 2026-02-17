---
status: pending
priority: p3
issue_id: "086"
tags: [plan-review, naming, schema]
dependencies: []
---

# Table Name: bio_reps Not biological_replicates

## Problem Statement

The plan uses `biological_replicates` as the table name. Other tables use short names: channels, conditions, fovs. `bio_reps` would be more consistent and ergonomic for SQL queries.

## Findings

Architecture strategist: "The table name biological_replicates is verbose for SQL queries. bio_reps is more consistent with existing naming."

## Proposed Solutions

### A) Rename table to bio_reps

- **Effort:** Trivial
- **Risk:** None

Change the CREATE TABLE statement and all references from `biological_replicates` to `bio_reps`. This aligns with the existing convention: channels, conditions, fovs, cells, measurements — all short, plural nouns.

## Technical Details

Current table names in the schema follow a consistent pattern of short plural nouns:

- `channels` (not `imaging_channels`)
- `conditions` (not `experimental_conditions`)
- `fovs` (not `fields_of_view`)
- `cells` (not `segmented_cells`)

Using `biological_replicates` breaks this convention. `bio_reps` maintains consistency and is less tedious to type in ad-hoc SQL queries against the SQLite database.

## Acceptance Criteria

- [ ] Plan uses bio_reps as table name (consistent with channels, conditions, fovs)

## Work Log

_No work performed yet._

## Resources

- Plan review: architecture strategist feedback
- Current schema: `src/percell3/core/schema.py`
