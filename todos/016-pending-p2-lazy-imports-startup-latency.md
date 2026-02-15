---
status: pending
priority: p2
issue_id: "016"
tags: [code-review, performance, cli]
dependencies: []
---
# Lazy Imports for CLI Startup Latency

## Problem Statement
Every CLI invocation (including `percell3 --help` and `percell3 --version`) eagerly imports all subcommand modules at the top of `main.py`. This transitively loads heavy scientific Python libraries (numpy, dask, zarr, pandas, tifffile, numcodecs) adding 2-5 seconds of startup latency on cold starts and 500ms-1500ms warm.

## Findings
- `main.py` lines 7-12 eagerly import every subcommand module
- `utils.py` line 12 imports `ExperimentStore` which triggers the full core import chain (dask, numpy, pandas, zarr)
- Even stub commands (`segment`, `measure`, `threshold`) trigger core imports via `utils.py`
- `percell3 --help` pays the full import cost despite needing zero domain logic
- Scripting workflows that invoke `percell3` in loops pay cumulative overhead

**Source:** performance-oracle CRITICAL-1, OPT-1

## Proposed Solutions
### Option A: Click LazyGroup (Recommended)
Use a custom `MultiCommand` or `click.Group` subclass that defers subcommand imports until the specific subcommand is invoked. Move top-level imports in `main.py` to a lazy-loading pattern.

Pros: Clean Click-native pattern, well-documented approach
Cons: Slightly more complex main.py
Effort: Medium

### Option B: Move heavy imports inside function bodies
Keep `main.py` imports but move `from percell3.core import ExperimentStore` from `utils.py` module-level to inside `open_experiment()`. Split lightweight utils (console, error_handler, make_progress) from heavy utils.

Pros: Minimal changes, stubs/help become instant
Cons: Doesn't fully solve the problem for commands that do import core
Effort: Small

## Acceptance Criteria
- [ ] `percell3 --help` completes in <500ms (no numpy/dask/zarr loaded)
- [ ] `percell3 --version` completes in <500ms
- [ ] Stub commands do not trigger heavy imports
- [ ] All existing tests still pass
- [ ] Each subcommand only loads its own dependencies

## Work Log
### 2026-02-13 - Code Review Discovery
Performance-oracle identified eager imports as the highest-impact performance issue in the CLI module.
