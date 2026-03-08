---
status: pending
priority: p3
issue_id: "131"
tags: [code-review, architecture, cleanup]
dependencies: []
---

# Plugin CSV exports accumulate outside database without cleanup

## Problem Statement

Plugins write CSV result files to the experiment directory but these are not tracked in the database. Re-running a plugin creates new CSVs without removing old ones, leading to accumulation of stale export files.

## Findings

- **Found by:** data-integrity-guardian
- Plugins like `local_bg_subtraction` and `split_halo_condensate_analysis` write CSV files
- No mechanism to track which CSVs belong to which analysis run
- Re-running analysis creates new files alongside (or overwriting) old ones
- User may be confused by multiple CSV files from different runs

## Proposed Solutions

### Solution A: Overwrite CSV with deterministic filename

Use a deterministic filename pattern (e.g., `{plugin_name}_{channel}.csv`) so re-runs overwrite previous exports.

**Pros:** Simple, self-cleaning
**Cons:** Loses history of previous runs
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] Plugin CSVs use deterministic filenames
- [ ] Re-running a plugin overwrites the previous CSV

## Technical Details

- **File:** `src/percell3/plugins/` — plugin CSV export methods
