# Module 6: Workflow — Acceptance Tests

## Test 1: DAG validation

```python
def test_dag_validates_acyclic():
    dag = WorkflowDAG()
    dag.add_step(MockStep("a", inputs=[], outputs=["x"]))
    dag.add_step(MockStep("b", inputs=["x"], outputs=["y"]))
    dag.add_step(MockStep("c", inputs=["y"], outputs=["z"]))

    errors = dag.validate()
    assert len(errors) == 0

def test_dag_rejects_cycle():
    dag = WorkflowDAG()
    dag.add_step(MockStep("a", inputs=["z"], outputs=["x"]))
    dag.add_step(MockStep("b", inputs=["x"], outputs=["y"]))
    dag.add_step(MockStep("c", inputs=["y"], outputs=["z"]))
    dag.auto_connect()

    errors = dag.validate()
    assert any("cycle" in e.lower() for e in errors)
```

## Test 2: Topological execution order

```python
def test_execution_order():
    dag = WorkflowDAG()
    dag.add_step(MockStep("measure", inputs=["labels"], outputs=["measurements"]))
    dag.add_step(MockStep("import", inputs=[], outputs=["images"]))
    dag.add_step(MockStep("segment", inputs=["images"], outputs=["labels"]))
    dag.auto_connect()

    order = dag.execution_order()
    assert order.index("import") < order.index("segment")
    assert order.index("segment") < order.index("measure")
```

## Test 3: Default complete workflow

```python
def test_complete_workflow(tmp_path, sample_lif_path):
    with ExperimentStore.create(tmp_path / "test.percell") as store:
        dag = complete_analysis_workflow(
            source_path=sample_lif_path,
            channel_seg="DAPI",
            channels_measure=["GFP", "RFP"],
        )

        engine = WorkflowEngine(store, dag)
        result = engine.run()

        assert result.steps_failed == 0
        assert store.get_cell_count() > 0
        assert len(store.get_measurements()) > 0
```

## Test 4: Re-run single step

```python
def test_rerun_measure_step(experiment_after_segment):
    store = experiment_after_segment
    dag = measure_only_workflow(channels=["GFP", "RFP", "Cy5"])

    engine = WorkflowEngine(store, dag)
    result = engine.run()

    # Should measure Cy5 without re-segmenting
    pivot = store.get_measurement_pivot()
    assert "Cy5_mean_intensity" in pivot.columns
```

## Test 5: Workflow state persistence

```python
def test_workflow_state_persists(tmp_path):
    with ExperimentStore.create(tmp_path / "test.percell") as store:
        dag = WorkflowDAG()
        dag.add_step(MockStep("step_a"))
        engine = WorkflowEngine(store, dag)
        engine.run()

    # Reopen and check state
    with ExperimentStore.open(tmp_path / "test.percell") as store:
        state = WorkflowState(store)
        assert state.is_completed("step_a")
```

## Test 6: YAML serialization round-trip

```python
def test_yaml_round_trip(tmp_path):
    dag = complete_analysis_workflow(
        source_path=Path("data/exp.lif"),
        channel_seg="DAPI",
        channels_measure=["GFP"],
    )

    yaml_path = tmp_path / "workflow.yaml"
    serializer = WorkflowSerializer()
    serializer.save(dag, yaml_path)

    loaded_dag = serializer.load(yaml_path)
    assert loaded_dag.execution_order() == dag.execution_order()
```

## Test 7: Skip completed steps

```python
def test_skip_completed(experiment_after_import):
    store = experiment_after_import
    dag = complete_analysis_workflow(...)
    engine = WorkflowEngine(store, dag)

    result = engine.run()
    # Import step should be skipped since data already exists
    assert result.steps_skipped >= 1
```
