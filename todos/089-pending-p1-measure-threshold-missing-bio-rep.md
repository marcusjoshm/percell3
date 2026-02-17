---
status: pending
priority: p1
issue_id: "089"
tags: [code-review, correctness, measure, threshold, bio-rep]
dependencies: []
---

# Measurer/ThresholdEngine Missing `bio_rep` Parameter + Positional Argument Bug

## Problem Statement

The `Measurer.measure_fov()`, `Measurer.measure_cells()`, `ThresholdEngine.threshold_fov()`, and `BatchMeasurer.measure_experiment()` methods do not accept or pass a `bio_rep` parameter. They call `store.read_labels()`, `store.read_image_numpy()`, and `store.write_mask()` without `bio_rep`, relying on auto-resolution. When an experiment has >1 bio rep, `_resolve_bio_rep(None)` raises `BioRepNotFoundError`, crashing the entire measurement pipeline.

Additionally, there is a **positional argument bug**: `store.read_labels(fov, condition, timepoint)` passes `timepoint` in the `bio_rep` position (3rd arg), since `ExperimentStore.read_labels` signature is `(fov, condition, bio_rep=None, timepoint=None)`. This silently resolves the wrong bio rep or raises a cryptic error.

## Findings

- **Found by:** kieran-python-reviewer, code-simplicity-reviewer, security-sentinel, performance-oracle, agent-native-reviewer (all 5 agents)
- **Evidence:**
  - `measurer.py:80`: `labels = store.read_labels(fov, condition, timepoint)` — timepoint in bio_rep position
  - `measurer.py:86`: `image = store.read_image_numpy(fov, condition, channel, timepoint)` — timepoint in bio_rep position
  - `measurer.py:132-134`: Same pattern in `measure_cells()`
  - `thresholding.py:77`: `image = store.read_image_numpy(fov, condition, channel, timepoint)` — timepoint in bio_rep position
  - `thresholding.py:95`: `store.write_mask(...)` missing bio_rep
  - `batch.py:95-99`: `fov_info.bio_rep` available but not passed through

## Proposed Solutions

### Solution A: Add bio_rep parameter and fix positional args (Recommended)
- Add `bio_rep: str | None = None` to `measure_fov()`, `measure_cells()`, `threshold_fov()`, `measure_experiment()`
- Switch all store calls to keyword arguments: `store.read_labels(fov, condition, bio_rep=bio_rep, timepoint=timepoint)`
- In `BatchMeasurer`, pass `bio_rep=fov_info.bio_rep`
- **Pros:** Complete fix, explicit about argument order
- **Cons:** None
- **Effort:** Small
- **Risk:** Low

## Recommended Action

Solution A

## Technical Details

**Affected files:**
- `src/percell3/measure/measurer.py` (lines 33-96, 119-160)
- `src/percell3/measure/thresholding.py` (lines 41-108)
- `src/percell3/measure/batch.py` (lines 48-134)

## Acceptance Criteria

- [ ] `measure_fov()` accepts `bio_rep: str | None = None` and passes it through
- [ ] `measure_cells()` accepts `bio_rep: str | None = None` and passes it through
- [ ] `threshold_fov()` accepts `bio_rep: str | None = None` and passes it through
- [ ] `BatchMeasurer.measure_experiment()` passes `fov_info.bio_rep` to `measure_fov()`
- [ ] All store calls use keyword arguments (no positional ambiguity)
- [ ] Tests pass with single and multiple bio reps

## Work Log

- 2026-02-17: Identified during code review of feat/data-model-bio-rep-fov branch

## Resources

- PR branch: feat/data-model-bio-rep-fov
