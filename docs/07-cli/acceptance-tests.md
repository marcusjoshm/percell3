# Module 7: CLI — Acceptance Tests

## Test 1: Create experiment

```python
def test_create(tmp_path):
    runner = CliRunner()
    exp_path = str(tmp_path / "test.percell")
    result = runner.invoke(cli, ["create", exp_path, "--name", "My Experiment"])

    assert result.exit_code == 0
    assert Path(exp_path).exists()
    assert (Path(exp_path) / "experiment.db").exists()
```

## Test 2: Import LIF file

```python
def test_import_lif(tmp_path, sample_lif_path):
    exp_path = str(tmp_path / "test.percell")
    runner = CliRunner()
    runner.invoke(cli, ["create", exp_path])
    result = runner.invoke(cli, [
        "import", str(sample_lif_path),
        "-e", exp_path,
        "--condition", "control",
    ])

    assert result.exit_code == 0
    with ExperimentStore.open(Path(exp_path)) as store:
        assert len(store.get_channels()) > 0
        assert len(store.get_regions()) > 0
```

## Test 3: Segment command

```python
def test_segment(experiment_with_images_cli):
    exp_path = str(experiment_with_images_cli)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "segment",
        "-e", exp_path,
        "--channel", "DAPI",
        "--model", "cyto3",
    ])

    assert result.exit_code == 0
    with ExperimentStore.open(Path(exp_path)) as store:
        assert store.get_cell_count() > 0
```

## Test 4: Measure command

```python
def test_measure(experiment_after_segment_cli):
    exp_path = str(experiment_after_segment_cli)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "measure",
        "-e", exp_path,
        "--channels", "GFP", "RFP",
    ])

    assert result.exit_code == 0
    with ExperimentStore.open(Path(exp_path)) as store:
        pivot = store.get_measurement_pivot()
        assert "GFP_mean_intensity" in pivot.columns
```

## Test 5: Export command

```python
def test_export(experiment_with_measurements_cli, tmp_path):
    exp_path = str(experiment_with_measurements_cli)
    csv_path = str(tmp_path / "results.csv")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "export",
        "-e", exp_path,
        csv_path,
    ])

    assert result.exit_code == 0
    df = pd.read_csv(csv_path)
    assert len(df) > 0
```

## Test 6: Query command

```python
def test_query_cells(experiment_with_cells_cli):
    exp_path = str(experiment_with_cells_cli)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "query", "cells",
        "-e", exp_path,
        "--format", "csv",
    ])

    assert result.exit_code == 0
    assert "cell_id" in result.output or "centroid_x" in result.output
```

## Test 7: Help text

```python
def test_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "create" in result.output
    assert "import" in result.output
    assert "segment" in result.output
    assert "measure" in result.output

def test_command_help():
    runner = CliRunner()
    for cmd in ["create", "import", "segment", "measure", "export", "query"]:
        result = runner.invoke(cli, [cmd, "--help"])
        assert result.exit_code == 0
```

## Test 8: Error handling

```python
def test_open_nonexistent_experiment():
    runner = CliRunner()
    result = runner.invoke(cli, [
        "segment",
        "-e", "/nonexistent/path.percell",
        "--channel", "DAPI",
    ])
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "error" in result.output.lower()
```

## Test 9: Plugin commands

```python
def test_plugin_list():
    runner = CliRunner()
    result = runner.invoke(cli, ["plugin", "list"])
    assert result.exit_code == 0
    assert "intensity_grouping" in result.output

def test_plugin_run(experiment_with_measurements_cli):
    exp_path = str(experiment_with_measurements_cli)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "plugin", "run", "intensity_grouping",
        "-e", exp_path,
        "--params", "channel=GFP", "n_groups=3",
    ])
    assert result.exit_code == 0
```
