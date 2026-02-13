---
title: "P1 Security and Correctness Issues in IO Module Z-Projection and TokenConfig"
date: 2026-02-13
category: logic-errors
severity: p1
modules:
  - io
files:
  - src/percell3/io/transforms.py
  - src/percell3/io/engine.py
  - src/percell3/io/models.py
tags:
  - integer-overflow
  - memory-optimization
  - z-projection
  - regex-validation
  - redos
  - silent-fallback
  - error-handling
  - security
  - microscopy-import
status: resolved
branch: feat/io-module
---

# P1: IO Module Z-Projection and Input Validation Fixes

## Problem Statement

The PerCell 3 IO module's Z-projection pipeline and filename parsing logic contained four P1-severity issues identified during multi-agent code review. These issues span data correctness, memory safety, error handling, and security — but share a common root cause: insufficient validation and edge-case handling at system boundaries.

The most critical issue was a ReDoS (Regular Expression Denial of Service) vulnerability in `TokenConfig` that accepted arbitrary user-controlled regex patterns without validation. Additionally, `project_sum` on uint16 Z-stacks suffered from integer overflow without explicit dtype casting, leading to incorrect scientific results. The Z-projection implementation loaded entire Z-stacks into memory (~320MB peak for typical 20-slice 2048x2048 uint16 images) instead of streaming slice-by-slice. Finally, a standalone `apply_z_transform_array` function duplicated logic from `transforms.py` and silently fell back to MIP projection for unknown methods.

All four issues were resolved with proper fixes: regex validation with length limits, dtype casting for safe accumulation, streaming Z-projection, and explicit error raising for unknown methods.

## Fix 1: Integer Overflow in `project_sum`

### Root Cause

When summing uint16 Z-slices, NumPy's `np.sum` without an explicit dtype uses the input dtype. For uint16 (max 65,535), summing 100 slices of high-intensity pixels produces values up to 6,000,000 — silently wrapping around and producing incorrect measurements.

### Fix

Explicitly use `dtype=np.int64` for integer accumulation (`src/percell3/io/transforms.py`):

```python
# Before
def project_sum(stack: np.ndarray) -> np.ndarray:
    return np.sum(stack, axis=0)

# After
def project_sum(stack: np.ndarray) -> np.ndarray:
    if np.issubdtype(stack.dtype, np.integer):
        return np.sum(stack, axis=0, dtype=np.int64)
    return np.sum(stack, axis=0)
```

### Verification

```python
def test_no_overflow_uint16(self):
    stack = np.full((100, 2, 2), 60000, dtype=np.uint16)
    result = project_sum(stack)
    assert result[0, 0] == 6_000_000
    assert result.dtype == np.int64
```

## Fix 2: Memory-Efficient Streaming Z-Projection

### Root Cause

`apply_z_transform()` loaded all Z-slices into a list then called `np.stack()`, creating two full copies of the stack. For 20 slices of 2048x2048 uint16 (~8MB each), peak memory was ~320MB per projection (list + stacked copy).

### Fix

Streaming accumulation in `src/percell3/io/transforms.py` — only one slice in memory at a time:

```python
# Before
slices = [read_tiff(p) for p in z_files]
stack = np.stack(slices, axis=0)
return project_mip(stack)

# After — streaming, ~16MB peak instead of ~320MB
first = read_tiff(z_files[0])
if transform.method == "mip":
    result = first.copy()
    for p in z_files[1:]:
        np.maximum(result, read_tiff(p), out=result)
    return result
if transform.method == "sum":
    acc = first.astype(np.int64) if np.issubdtype(first.dtype, np.integer) else first.astype(np.float64)
    for p in z_files[1:]:
        acc += read_tiff(p)
    return acc
if transform.method == "mean":
    acc = first.astype(np.float64)
    for p in z_files[1:]:
        acc += read_tiff(p)
    return (acc / len(z_files)).astype(first.dtype)
```

### Verification

Existing `TestApplyZTransform` tests (MIP, sum, mean, slice) all pass with the streaming implementation, producing identical results.

## Fix 3: Silent MIP Fallback Removal

### Root Cause

`apply_z_transform_array` in `engine.py` silently fell back to MIP for unknown transform methods:

```python
# Before — silent fallback hides bugs
if transform.method == "slice":
    idx = transform.slice_index or 0  # Also wrong: 0 is falsy
    return data[idx]
# Default: MIP
return project_mip(data)  # Unknown methods silently become MIP
```

### Fix

Replaced with `_project_array()` that raises `ValueError` for unknown methods and validates `slice_index` (`src/percell3/io/engine.py`):

```python
def _project_array(data: np.ndarray, transform: ZTransform) -> np.ndarray:
    if transform.method == "mip":
        return project_mip(data)
    if transform.method == "sum":
        return project_sum(data)
    if transform.method == "mean":
        return project_mean(data)
    if transform.method == "slice":
        if transform.slice_index is None:
            raise ValueError("slice_index is required when method is 'slice'")
        if transform.slice_index < 0 or transform.slice_index >= data.shape[0]:
            raise ValueError(f"slice_index {transform.slice_index} out of range")
        return data[transform.slice_index]
    raise ValueError(f"Unknown Z-transform method: {transform.method!r}")
```

### Verification

```python
def test_unknown_method_raises(self, tmp_path):
    with pytest.raises(ValueError, match="Unknown"):
        apply_z_transform([p], ZTransform(method="invalid"))
```

## Fix 4: ReDoS Prevention via Regex Validation

### Root Cause

`TokenConfig` accepted arbitrary regex patterns with no validation. Malicious or malformed patterns (e.g., `(a+)+`) could cause catastrophic backtracking (ReDoS), freezing the import pipeline.

### Fix

Added `__post_init__()` validation to `TokenConfig` (`src/percell3/io/models.py`):

```python
_MAX_PATTERN_LENGTH = 200

@dataclass(frozen=True)
class TokenConfig:
    channel: str = r"_ch(\d+)"
    timepoint: str = r"_t(\d+)"
    z_slice: str = r"_z(\d+)"
    region: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("channel", "timepoint", "z_slice", "region"):
            pattern = getattr(self, field_name)
            if pattern is None:
                continue
            if len(pattern) > _MAX_PATTERN_LENGTH:
                raise ValueError(f"Token pattern '{field_name}' exceeds max length {_MAX_PATTERN_LENGTH}")
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex for '{field_name}': {e}") from e
```

### Verification

```python
def test_invalid_regex_raises(self):
    with pytest.raises(ValueError, match="Invalid regex"):
        TokenConfig(channel=r"_ch([\d+")

def test_excessively_long_pattern_raises(self):
    with pytest.raises(ValueError, match="exceeds max length"):
        TokenConfig(channel="a" * 201)
```

## Prevention Strategies

### Integer Overflow in Accumulation

- **Rule**: Always specify `dtype` in `np.sum()`, `np.mean()`, `np.cumsum()` on integer arrays
- **Detection**: Search for `np\.sum\([^)]*\)` without `dtype=` parameter in code review
- **Test pattern**: Create max-value input arrays and verify sums exceed dtype.max

### Memory-Bounded Image Processing

- **Rule**: Never load >10 full-resolution images into memory via list comprehension + `np.stack()`
- **Detection**: Flag list comprehensions followed by `np.stack()` where list elements are array loads
- **Estimate**: `n_images * height * width * dtype_size` — if >1 GB, refactor to streaming

### Explicit Error Handling

- **Rule**: Never use bare `else:` clauses as catch-alls for user input. Validate enum-like parameters explicitly
- **Detection**: Flag any function accepting string "method" or "mode" parameters without validation
- **Test pattern**: For every valid method, add a test for an invalid method that asserts `ValueError`

### User-Controlled Regex Safety

- **Rule**: Never pass user-controlled strings directly to `re.compile()` without length limits and compilation checks
- **Detection**: Flag `re.search()` / `re.compile()` with variable (non-constant) pattern arguments
- **Alternative**: Prefer glob patterns (`fnmatch`) over regex for file filtering when possible

## General Lessons

1. **Fail Fast and Loud**: Silent failures hide bugs. Raise descriptive errors at function boundaries.
2. **Memory is a Constraint**: Microscopy images are large. Assume datasets 10x larger than test data.
3. **Integer Dtypes are Traps**: NumPy's silent overflow is a footgun. Use float64 for accumulation.
4. **User Input is Hostile Until Validated**: Treat config files and CLI args as potentially malicious.
5. **Test the Unhappy Path**: For every happy-path test, write at least one unhappy-path test.

## Related Documentation

- `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md` — Establishes input validation patterns for ExperimentStore names, exception hierarchy discipline
- `docs/plans/2026-02-12-feat-io-module-tiff-import-plan.md` — IO module implementation plan with Z-projection design
- `docs/02-io/spec.md` — IO module specification with dtype handling and Z-stack behavior
- `docs/brainstorms/2026-02-12-io-module-design-brainstorm.md` — Design decisions establishing lazy loading as architectural principle
- `CLAUDE.md` — Hexagonal architecture, ExperimentStore as center, no global state

## Code Review Checklist (IO Module)

- [ ] No `np.sum()` / `np.mean()` without explicit `dtype` on integer arrays
- [ ] No list comprehensions loading >10 images into memory at once
- [ ] All enum-like parameters validated with explicit error for invalid values
- [ ] No `re.search()` with user-controlled patterns without validation
- [ ] All public functions have docstrings with "Raises" sections
- [ ] All new image operations have overflow + edge-case tests
- [ ] No bare `else:` clauses as catch-alls for user input
