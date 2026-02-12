# CLAUDE.md — Module 5: Plugins (percell3.plugins)

## Your Task
Build the plugin system. Define AnalysisPlugin ABC, implement discovery via
entry_points, create built-in plugins, scaffold the FLIM-Phasor plugin.

## Read First
1. `../00-overview/architecture.md`
2. `../01-core/spec.md`
3. `./spec.md`

## Output Location
- Source: `src/percell3/plugins/`
- Tests: `tests/test_plugins/`

## Files to Create
```
src/percell3/plugins/
├── __init__.py
├── base.py                  # AnalysisPlugin ABC
├── registry.py              # Plugin discovery and management
├── builtin/
│   ├── __init__.py
│   ├── intensity_grouping.py   # Cell grouping by intensity
│   ├── colocalization.py       # Channel colocalization metrics
│   └── flim_phasor.py          # Scaffold for FLIM-Phasor integration
```

## Acceptance Criteria
1. AnalysisPlugin ABC can be subclassed with name, description, required_channels, run()
2. PluginRegistry discovers built-in plugins automatically
3. PluginRegistry discovers external plugins via entry_points
4. IntensityGrouping plugin correctly groups cells by intensity thresholds
5. Colocalization plugin computes Pearson/Manders coefficients per cell
6. Plugins can write measurements back to ExperimentStore

## Dependencies You Can Use
importlib.metadata, numpy, scipy, percell3.core

## Dependencies You Must NOT Use
cellpose, readlif, click, rich
