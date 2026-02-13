---
status: pending
priority: p3
issue_id: "013"
tags: [code-review, quality]
dependencies: []
---
# Missing ExperimentStore.__repr__

## Problem Statement
ExperimentStore has no `__repr__` method. Printing a store instance gives an unhelpful default object representation, making debugging and interactive use harder.

## Findings
- `print(store)` outputs something like `<percell3.core.store.ExperimentStore object at 0x...>`
- The store's path is the most useful identifying information
- Other key info (e.g., number of conditions/regions) could also be included

## Proposed Solutions
### Option 1
Add a concise `__repr__` method:
```python
def __repr__(self) -> str:
    return f"ExperimentStore({self._path!r})"
```

## Acceptance Criteria
- [ ] `ExperimentStore` has a `__repr__` method
- [ ] Output includes the experiment path
- [ ] Unit test verifies repr output format

## Work Log
### 2026-02-12 - Code Review Discovery
