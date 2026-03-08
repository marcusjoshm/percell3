---
status: pending
priority: p3
issue_id: 159
tags: [code-review, quality, io]
dependencies: []
---

# Use Literal Types for TileConfig grid_type and order

## Problem Statement

`TileConfig.grid_type` and `TileConfig.order` are typed as `str` but only accept specific values validated at runtime. Using `Literal` types would improve IDE support and static analysis.

## Findings

- **Source**: kieran-python-reviewer
- **Location**: `src/percell3/io/models.py:61-64`

## Proposed Solutions

### Option A: Add type aliases with Literal
- **Effort**: Small

```python
from typing import Literal

GridType = Literal["row_by_row", "column_by_column", "snake_by_row", "snake_by_column"]
TileOrder = Literal["right_and_down", "left_and_down", "right_and_up", "left_and_up"]
```

## Acceptance Criteria

- [ ] `grid_type` and `order` use Literal type annotations
- [ ] Runtime validation remains in `__post_init__`

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | |
