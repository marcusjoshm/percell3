# Module 5: Plugins — Acceptance Tests

## Test 1: Plugin ABC contract

```python
def test_plugin_abc():
    """AnalysisPlugin requires info(), validate(), and run()."""
    with pytest.raises(TypeError):
        # Can't instantiate without implementing abstract methods
        AnalysisPlugin()

class DummyPlugin(AnalysisPlugin):
    def info(self):
        return PluginInfo(name="dummy", version="1.0", description="Test")
    def validate(self, store):
        return []
    def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
        return PluginResult(measurements_written=0, cells_processed=0,
                           custom_outputs={}, warnings=[])

def test_dummy_plugin_instantiates():
    plugin = DummyPlugin()
    assert plugin.info().name == "dummy"
```

## Test 2: Plugin registry discovers built-in plugins

```python
def test_registry_discovers_builtins():
    registry = PluginRegistry()
    registry.discover()

    plugins = registry.list_plugins()
    names = [p.name for p in plugins]
    assert "intensity_grouping" in names
    assert "colocalization" in names
```

## Test 3: Intensity grouping plugin

```python
def test_intensity_grouping(experiment_with_measurements):
    store = experiment_with_measurements
    registry = PluginRegistry()
    registry.discover()

    result = registry.run_plugin("intensity_grouping", store, parameters={
        "channel": "GFP",
        "method": "quantile",
        "n_groups": 3,
        "group_names": ["low", "medium", "high"],
    })

    assert result.cells_processed == store.get_cell_count()

    # Check measurements written
    df = store.get_measurements(metrics=["GFP_group"])
    assert len(df) == store.get_cell_count()
    assert set(df["value"].unique()).issubset({0, 1, 2})
```

## Test 4: Colocalization plugin

```python
def test_colocalization(experiment_with_measurements):
    store = experiment_with_measurements
    registry = PluginRegistry()
    registry.discover()

    result = registry.run_plugin("colocalization", store, parameters={
        "channel_a": "GFP",
        "channel_b": "RFP",
    })

    df = store.get_measurements(metrics=["pearson_r"])
    assert len(df) > 0
    assert all(-1 <= v <= 1 for v in df["value"])
```

## Test 5: Plugin validation

```python
def test_plugin_validation_fails(experiment_empty):
    store = experiment_empty  # No channels, no cells
    registry = PluginRegistry()
    registry.discover()

    plugin = registry.get_plugin("intensity_grouping")
    errors = plugin.validate(store)
    assert len(errors) > 0  # Should report missing channels/cells
```

## Test 6: Analysis run tracking

```python
def test_plugin_logs_analysis_run(experiment_with_measurements):
    store = experiment_with_measurements
    registry = PluginRegistry()
    registry.discover()

    result = registry.run_plugin("intensity_grouping", store, parameters={
        "channel": "GFP", "method": "quantile", "n_groups": 2,
    })

    # Should be tracked in analysis_runs table
    # (verified via direct SQL or ExperimentStore method)
```
