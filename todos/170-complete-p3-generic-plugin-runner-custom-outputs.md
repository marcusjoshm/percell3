---
status: pending
priority: p3
issue_id: 170
tags: [code-review, agent-native, cli]
dependencies: []
---

# Generic plugin runner ignores custom_outputs

## Problem Statement

The generic plugin runner in `cli/menu.py` prints `cells_processed` and `measurements_written` but ignores `custom_outputs`. For image_calculator, the critical output is `derived_fov_id`. Users and agents have no way to learn which FOV was created without querying the store.

## Findings

- **Source**: agent-native-reviewer (Finding #2)
- **Location**: `src/percell3/cli/menu.py:409-413`

## Proposed Solutions

### Option A: Print custom_outputs in generic runner (Recommended)

```python
for key, val in result.custom_outputs.items():
    console.print(f"  {key}: {val}")
```

- **Effort**: Small
- **Risk**: None

## Acceptance Criteria

- [ ] Generic plugin runner prints all custom_outputs key-value pairs

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-03 | Created from code review | Surface plugin outputs to users |
