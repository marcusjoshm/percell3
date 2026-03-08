---
status: complete
priority: p2
issue_id: "081"
tags: [plan-review, architecture, planning-gap]
dependencies: []
---

# ImportPlan and ImportResult Models Need bio_rep Fields

## Problem Statement

`ImportPlan` and `ImportResult` models need bio_rep fields. The plan mentions this briefly but doesn't detail how the import pipeline threads bio_rep through.

## Findings

- **Agent-native**: "ImportPlan needs a `bio_rep_map: dict[str, str]` parallel to `condition_map`."
- **Spec-flow**: "ImportPlan has `condition: str` as default. Should also have `bio_rep: str = 'N1'`."
- Current `ImportPlan` at `io/models.py` has `condition_map` and `region_names`. Needs bio_rep field.

## Proposed Solutions

### A) Add bio_rep field to ImportPlan and ImportResult

Add `bio_rep: str = "N1"` field to `ImportPlan`. Add `bio_rep` to `ImportResult`. Thread through `ImportEngine.execute()`.

- **Pros**: Simple, follows existing condition pattern, minimal disruption.
- **Cons**: Default value "N1" may conflict with issue 070 (bio_rep default design).
- **Effort**: Small.
- **Risk**: Low.

### B) Add bio_rep_map for multi-file imports

Add `bio_rep_map: dict[str, str]` to `ImportPlan` (parallel to `condition_map`), mapping file/series names to bio rep names. Single-file imports use `bio_rep` field, multi-file imports use `bio_rep_map`.

- **Pros**: Supports complex import scenarios, consistent with condition_map pattern.
- **Cons**: More complex model, may be YAGNI for initial implementation.
- **Effort**: Medium.
- **Risk**: Low.

### C) Use bio_rep: str | None = None (matching issue 070 pattern)

If issue 070 adopts auto-resolve for None, use the same pattern here. `None` means "use the single existing bio rep or create default".

- **Pros**: Consistent with issue 070 decision.
- **Cons**: Depends on issue 070 resolution.
- **Effort**: Small.
- **Risk**: Low (depends on 070).

## Technical Details

Current `ImportPlan` model (`io/models.py`):
```python
@dataclass
class ImportPlan:
    source_path: Path
    condition_map: dict[str, str]
    region_names: list[str]
    channel_map: dict[str, str]
    ...
```

Needs to become:
```python
@dataclass
class ImportPlan:
    source_path: Path
    condition_map: dict[str, str]
    bio_rep: str = "N1"          # or str | None = None
    region_names: list[str]
    channel_map: dict[str, str]
    ...
```

Threading through the pipeline:
1. CLI `--bio-rep` flag sets `ImportPlan.bio_rep`
2. `ImportEngine.execute()` reads `plan.bio_rep`
3. `ImportEngine` calls `store.add_fov(bio_rep=plan.bio_rep, ...)`
4. `ImportResult` records the bio_rep used

Affected files:
- `src/percell3/io/models.py` — ImportPlan, ImportResult dataclasses
- `src/percell3/io/engine.py` — ImportEngine.execute()
- `src/percell3/cli/import_cmd.py` — CLI flag threading

## Acceptance Criteria

- [ ] ImportPlan has bio_rep field
- [ ] ImportEngine passes bio_rep to `store.add_fov()`
- [ ] ImportResult includes bio_rep info
- [ ] CLI `--bio-rep` flag populates ImportPlan.bio_rep
- [ ] Default value aligns with issue 070 decision

## Work Log

- 2026-02-17 — Identified by agent-native and spec-flow reviewers during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
- Related: todos/070-pending-p1-bio-rep-parameter-design-auto-resolve.md
