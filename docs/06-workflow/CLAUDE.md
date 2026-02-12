# CLAUDE.md — Module 6: Workflow (percell3.workflow)

## Your Task
Build the DAG-based workflow engine. Steps declare inputs/outputs.
The engine resolves execution order and tracks state.

## Read First
1. `../00-overview/architecture.md`
2. `../01-core/spec.md`
3. `./spec.md`

## Output Location
- Source: `src/percell3/workflow/`
- Tests: `tests/test_workflow/`

## Files to Create
```
src/percell3/workflow/
├── __init__.py
├── step.py                  # WorkflowStep base class
├── dag.py                   # DAG builder and validator
├── engine.py                # Workflow execution engine
├── state.py                 # Step state tracking
├── defaults.py              # Pre-built workflows
└── serialization.py         # Save/load workflows as YAML
```

## Acceptance Criteria
1. WorkflowStep declares inputs, outputs, and parameters
2. DAG builder validates no cycles and all inputs are satisfied
3. Engine executes steps in dependency order
4. Can re-run a single step without re-running the full workflow
5. Default "complete analysis" workflow runs import->segment->measure->export
6. Workflow state persisted in SQLite (which steps ran, when, with what params)

## Dependencies You Can Use
networkx (optional), pyyaml, percell3.core, percell3.io, percell3.segment, percell3.measure, percell3.plugins

## Dependencies You Must NOT Use
click, rich (those belong to CLI)
