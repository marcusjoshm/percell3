---
status: complete
priority: p1
issue_id: "091"
tags: [code-review, correctness, io, sanitization]
dependencies: []
---

# ImportEngine Uses Unsanitized `plan.bio_rep` After Sanitized Insert

## Problem Statement

In `ImportEngine.execute()`, the code sanitizes `plan.bio_rep` when inserting into the DB (`store.add_bio_rep(sanitize_name(plan.bio_rep))`), but then continues using the raw unsanitized `plan.bio_rep` value in subsequent calls like `store.get_fovs(condition=condition, bio_rep=plan.bio_rep)` and `store.write_image(..., bio_rep=plan.bio_rep)`. If `plan.bio_rep` contains leading/trailing whitespace (e.g., `" N2 "`), the DB stores `"N2"` but lookups use `" N2 "`, causing `BioRepNotFoundError`.

## Findings

- **Found by:** kieran-python-reviewer
- **Evidence:**
  - `engine.py:84-86`: Comparison uses raw `plan.bio_rep`, insert uses `sanitize_name(plan.bio_rep)`
  - `engine.py:134`: `store.get_fovs(condition=condition, bio_rep=plan.bio_rep)` — raw value
  - `engine.py:177`: `store.write_image(..., bio_rep=plan.bio_rep)` — raw value

## Proposed Solutions

### Solution A: Sanitize once at the top (Recommended)
- After reading the plan, normalize: `bio_rep_name = sanitize_name(plan.bio_rep)` and use `bio_rep_name` throughout
- **Pros:** Single point of sanitization, consistent
- **Cons:** None
- **Effort:** Small
- **Risk:** Low

## Recommended Action

Solution A

## Technical Details

**Affected files:**
- `src/percell3/io/engine.py` (~lines 84-177)

## Acceptance Criteria

- [ ] `plan.bio_rep` is sanitized once at the start of `execute()`
- [ ] All subsequent references use the sanitized value
- [ ] Test with whitespace-containing bio_rep name passes

## Work Log

- 2026-02-17: Identified during code review of feat/data-model-bio-rep-fov branch

## Resources

- PR branch: feat/data-model-bio-rep-fov
