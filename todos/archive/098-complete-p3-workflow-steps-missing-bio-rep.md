---
status: complete
priority: p3
issue_id: "098"
tags: [code-review, workflow, agent-native, bio-rep]
dependencies: []
---

# Workflow Steps Don't Expose `bio_rep` Parameter

## Problem Statement

The `ImportLif`, `ImportTiff`, `Segment`, `Measure`, and `Threshold` workflow steps in `workflow/defaults.py` do not include `bio_rep` in their `parameters` lists or pass it through in `execute()`.

## Findings

- **Found by:** agent-native-reviewer
- **Evidence:** `workflow/defaults.py` — no bio_rep in step parameters

## Proposed Solutions

### Solution A: Add bio_rep StepParameter to relevant steps
- Add `StepParameter("bio_rep", "str", default="N1")` to each step
- Forward in `execute()`
- **Effort:** Small | **Risk:** Low

## Work Log

- 2026-02-17: Identified during code review
