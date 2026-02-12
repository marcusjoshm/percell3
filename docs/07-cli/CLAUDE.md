# CLAUDE.md — Module 7: CLI (percell3.cli)

## Your Task
Build the Click-based command-line interface. This wraps all other modules
into user-facing commands with Rich terminal output.

## Read First
1. `../00-overview/architecture.md`
2. `../01-core/spec.md`
3. `./spec.md`

## Output Location
- Source: `src/percell3/cli/`
- Tests: `tests/test_cli/`

## Files to Create
```
src/percell3/cli/
├── __init__.py
├── main.py                  # Top-level Click group
├── create.py                # percell3 create
├── import_cmd.py            # percell3 import (import is a reserved word)
├── segment.py               # percell3 segment
├── measure.py               # percell3 measure
├── threshold.py             # percell3 threshold
├── query.py                 # percell3 query
├── export.py                # percell3 export
├── plugin.py                # percell3 plugin list|run
├── workflow.py              # percell3 workflow run|list
└── utils.py                 # Shared CLI utilities (Rich console, etc.)
```

## Acceptance Criteria
1. `percell3 create` creates a new .percell directory
2. `percell3 import` imports LIF/TIFF/CZI files
3. `percell3 segment` runs Cellpose segmentation
4. `percell3 measure` runs measurements on specified channels
5. `percell3 export` exports CSV results
6. All commands show Rich progress bars for long operations
7. `percell3 --help` shows complete help text for all commands
8. Exit codes: 0 for success, 1 for user error, 2 for internal error

## Dependencies You Can Use
click, rich, all percell3 modules

## Key Constraints
- All commands take `--experiment / -e` to specify the .percell directory
- Use Rich console for all output (tables, progress bars, status)
- Commands should be composable and scriptable
- Handle errors gracefully with user-friendly messages
