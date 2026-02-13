---
title: "Fix P2/P3 Code Review Findings in IO and Workflow Modules"
type: refactor
date: 2026-02-13
---

# Fix P2/P3 Code Review Findings in IO and Workflow Modules

## Overview

Address 10 remaining findings from the multi-agent code review of the IO and Workflow modules on `feat/io-module`. The P1 items (integer overflow, memory blowup, silent fallback, ReDoS) are already fixed. These P2/P3 items improve security, remove dead code, and clean up minor quality issues.

## Problem Statement

The code review identified 6 P2 (important) and 4 P3 (nice-to-have) items. Two P2 items have security implications (XXE in XML parsing, symlink traversal). The rest are dead code, missing validation, and code quality improvements. All fixes are small-to-medium complexity and can be completed in a single pass.

## Technical Approach

### Phase 1: Security Hardening (P2 — security items)

#### 1.1 XXE Protection in OME-XML Parsing

**File:** `src/percell3/io/tiff.py:56-58`

`xml.etree.ElementTree.fromstring()` is vulnerable to XXE attacks via crafted TIFF files with hostile OME-XML metadata.

**Fix:** Replace with `defusedxml.ElementTree.fromstring()`.

```python
# Before
import xml.etree.ElementTree as ET
root = ET.fromstring(tif.ome_metadata)

# After
from defusedxml.ElementTree import fromstring as safe_fromstring
root = safe_fromstring(tif.ome_metadata)
```

- [x] Add `defusedxml>=0.7` to `pyproject.toml` dependencies
- [x] Replace `ET.fromstring` with `defusedxml` in `tiff.py`
- [x] Add test: crafted XML with entity expansion is rejected

#### 1.2 Symlink Guard in Scanner

**File:** `src/percell3/io/scanner.py:107-113`

`Path.rglob("*")` follows symlinks by default, enabling directory escape and circular symlink loops.

**Fix:** Filter out symlinks in `_find_tiffs`.

```python
# Before
for child in path.rglob("*"):
    if child.is_file() and child.suffix.lower() in self.TIFF_EXTENSIONS:
        results.append(child)

# After
for child in path.rglob("*"):
    if child.is_symlink():
        continue
    if child.is_file() and child.suffix.lower() in self.TIFF_EXTENSIONS:
        results.append(child)
```

- [x] Add symlink guard to `_find_tiffs`
- [x] Add test: symlinked TIFF files are skipped
- [x] Add test: symlinked directories are not followed

### Phase 2: Input Validation (P2 — correctness items)

#### 2.1 ZTransform Method Validation

**File:** `src/percell3/io/models.py:79-84`

`ZTransform.method` accepts any string; validation only happens at execution time.

**Fix:** Add `__post_init__` validation.

```python
_VALID_Z_METHODS = frozenset({"mip", "sum", "mean", "keep", "slice"})

@dataclass(frozen=True)
class ZTransform:
    method: str
    slice_index: int | None = None

    def __post_init__(self) -> None:
        if self.method not in _VALID_Z_METHODS:
            raise ValueError(
                f"Invalid Z-transform method: {self.method!r}. "
                f"Must be one of {sorted(_VALID_Z_METHODS)}"
            )
        if self.method == "slice" and self.slice_index is None:
            raise ValueError("slice_index is required when method is 'slice'")
```

- [x] Add `_VALID_Z_METHODS` constant and `__post_init__` to `ZTransform`
- [x] Update `test_transforms.py::test_unknown_method_raises` — error now raises at construction, not at `apply_z_transform`
- [x] Update `test_transforms.py::test_slice_requires_index` — same: error at construction
- [x] Add test: valid methods all construct successfully
- [x] Verify YAML deserialization in `test_serialization.py` still works

### Phase 3: Dead Code Removal (P2 — cleanup)

#### 3.1 Remove `_VALID_NAME_RE` from `_sanitize.py`

**File:** `src/percell3/io/_sanitize.py:7`

Unused compiled regex. The same pattern lives in `core/experiment_store.py` where it IS used.

- [x] Delete line 7: `_VALID_NAME_RE = re.compile(...)`
- [x] `re` import still needed for `_INVALID_CHARS_RE`

#### 3.2 Remove `steps_ready` from `WorkflowDAG`

**File:** `src/percell3/workflow/dag.py:170-180`

Never called by engine, tests, or any production code. The engine uses `state.is_completed()` + topological order instead.

- [x] Remove `steps_ready` method from `WorkflowDAG`
- [x] Keep `can_run` on `WorkflowStep` (documented extension point)
- [x] Keep `test_can_run_default_true` (tests the extension point)

### Phase 4: Code Quality (P3 — nice-to-have)

#### 4.1 Consolidate Grouping Helpers in Engine

**File:** `src/percell3/io/engine.py:170-199`

`_group_by_region` and `_group_by_channel` are identical except for the token key and default value.

**Fix:** Replace with a single `_group_by_token` function.

```python
def _group_by_token(
    files: list[DiscoveredFile], key: str, default: str,
) -> dict[str, list[DiscoveredFile]]:
    groups: dict[str, list[DiscoveredFile]] = defaultdict(list)
    for f in files:
        groups[f.tokens.get(key, default)].append(f)
    return dict(groups)
```

- [x] Replace `_group_by_region` and `_group_by_channel` with `_group_by_token`
- [x] Update call sites in `execute()` (lines 81, 107)
- [x] Keep `_group_by_z` separate (different return type)

#### 4.2 Cache SQLite Connection in WorkflowState

**File:** `src/percell3/workflow/state.py:55-56`

Opens a new `sqlite3.Connection` for every operation. For N workflow steps, this means 2N+ connection open/close cycles.

**Fix:** Cache connection at init time.

```python
def __init__(self, store: Any) -> None:
    self._db_path = Path(store.db_path)
    self._conn = sqlite3.connect(str(self._db_path))
    self._ensure_table()

def _connect(self) -> sqlite3.Connection:
    return self._conn

def close(self) -> None:
    if self._conn:
        self._conn.close()
        self._conn = None
```

- [x] Cache connection in `__init__`
- [x] Update `_connect()` to return cached connection
- [x] Add `close()` method
- [x] `from_db_path()` works via `__init__` (no changes needed)
- [x] Verify `test_persistence_across_connections` still passes

### Items Deferred (Not in This Plan)

These P3 items are intentionally deferred — they're larger refactors with limited benefit:

- **P3-1: Stateless classes** (`FileScanner`, `ImportEngine`) — Converting to module-level functions would touch many call sites and imports across the codebase. The class-based API is conventional and not harmful. Defer until a broader API redesign.

- **P3-4: Unrestricted `source_path`** — Path boundary enforcement requires design decisions about what constitutes "allowed roots." The `ImportEngine.execute()` already validates the path exists. Adding more restrictions risks breaking legitimate use cases (e.g., NFS mounts, absolute paths in YAML plans). Defer until CLI module where user-facing path handling is centralized.

- **P2-4: Scanner metadata I/O on every TIFF** — Optimizing to sample-based metadata reads is a performance enhancement that changes behavior (users may not see inconsistent shape warnings for un-sampled files). Defer to a separate performance sprint or address when real-world usage data shows it's a bottleneck.

## Acceptance Criteria

### Security
- [x] OME-XML parsing uses `defusedxml` (no stdlib `xml.etree.ElementTree`)
- [x] Scanner does not follow symlinks

### Correctness
- [x] `ZTransform("invalid")` raises `ValueError` at construction time
- [x] `ZTransform("slice")` without `slice_index` raises at construction time

### Cleanup
- [x] `_VALID_NAME_RE` removed from `_sanitize.py`
- [x] `steps_ready` removed from `WorkflowDAG`
- [x] `_group_by_region` and `_group_by_channel` consolidated into `_group_by_token`
- [x] `WorkflowState` reuses a single SQLite connection

### Quality
- [x] All existing tests still pass (295 total — 289 original + 6 new)
- [x] New tests added for symlink guard, XXE, ZTransform validation
- [x] No regressions in IO or Workflow module functionality

## Dependencies & Risks

**Dependencies:**
- `defusedxml>=0.7` — new dependency for XXE protection. Well-established, no license issues (PSF).

**Risks:**

1. **ZTransform validation may break existing test expectations.** Tests that construct `ZTransform(method="invalid")` to test error handling at *execution* time will now get the error at *construction* time. Need to update those tests.

2. **WorkflowState connection caching changes lifecycle semantics.** Tests that verify persistence across separate connections (`test_persistence_across_connections`) may need adjustment. Must ensure the cached connection still commits properly.

## References

- Prior P1 fixes: `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md`
- Core security patterns: `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
- IO module plan: `docs/plans/2026-02-12-feat-io-module-tiff-import-plan.md`
- IO spec: `docs/02-io/spec.md`
