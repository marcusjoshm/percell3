# Module 1: Core — Acceptance Tests

These tests define what "done" looks like for Module 1. All must pass.

## Test 1: Create and open experiment

```python
def test_create_experiment(tmp_path):
    exp_path = tmp_path / "test.percell"
    exp = ExperimentStore.create(exp_path, name="Test Experiment")

    assert exp_path.exists()
    assert (exp_path / "experiment.db").exists()
    assert (exp_path / "images.zarr").exists()
    assert (exp_path / "labels.zarr").exists()
    assert (exp_path / "masks.zarr").exists()
    assert exp.name == "Test Experiment"
    exp.close()

def test_open_experiment(tmp_path):
    exp_path = tmp_path / "test.percell"
    ExperimentStore.create(exp_path, name="Test").close()
    exp = ExperimentStore.open(exp_path)
    assert exp.name == "Test"
    exp.close()

def test_context_manager(tmp_path):
    exp_path = tmp_path / "test.percell"
    with ExperimentStore.create(exp_path) as exp:
        exp.add_channel("DAPI")
    # Should be closed now, no error
```

## Test 2: Channel management

```python
def test_add_and_get_channels(experiment):
    experiment.add_channel("DAPI", role="nucleus", color="#0000FF")
    experiment.add_channel("GFP", role="signal", color="#00FF00")

    channels = experiment.get_channels()
    assert len(channels) == 2
    assert channels[0].name == "DAPI"
    assert channels[0].role == "nucleus"

    dapi = experiment.get_channel("DAPI")
    assert dapi.color == "#0000FF"

def test_duplicate_channel_raises(experiment):
    experiment.add_channel("DAPI")
    with pytest.raises(DuplicateError):
        experiment.add_channel("DAPI")
```

## Test 3: Condition/region hierarchy

```python
def test_conditions_and_regions(experiment):
    experiment.add_condition("control")
    experiment.add_condition("treated")
    experiment.add_region("region_1", condition="control", width=2048, height=2048)
    experiment.add_region("region_2", condition="control", width=2048, height=2048)
    experiment.add_region("region_1", condition="treated", width=2048, height=2048)

    assert experiment.get_conditions() == ["control", "treated"]
    control_regions = experiment.get_regions(condition="control")
    assert len(control_regions) == 2
```

## Test 4: Write and read OME-Zarr image

```python
def test_write_and_read_image(experiment):
    experiment.add_channel("DAPI")
    experiment.add_condition("control")
    experiment.add_region("region_1", condition="control", width=512, height=512)

    data = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
    experiment.write_image("region_1", "control", "DAPI", data)

    # Read back as dask array
    result_dask = experiment.read_image("region_1", "control", "DAPI")
    assert isinstance(result_dask, da.Array)

    # Read back as numpy
    result_np = experiment.read_image_numpy("region_1", "control", "DAPI")
    np.testing.assert_array_equal(result_np, data)

def test_multi_channel_image(experiment):
    experiment.add_channel("DAPI")
    experiment.add_channel("GFP")
    experiment.add_condition("control")
    experiment.add_region("r1", condition="control", width=256, height=256)

    dapi = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)
    gfp = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)

    experiment.write_image("r1", "control", "DAPI", dapi)
    experiment.write_image("r1", "control", "GFP", gfp)

    result_dapi = experiment.read_image_numpy("r1", "control", "DAPI")
    result_gfp = experiment.read_image_numpy("r1", "control", "GFP")

    np.testing.assert_array_equal(result_dapi, dapi)
    np.testing.assert_array_equal(result_gfp, gfp)
```

## Test 5: Cell records

```python
def test_add_and_query_cells(experiment):
    experiment.add_channel("DAPI", role="nucleus")
    experiment.add_condition("control")
    region_id = experiment.add_region("r1", condition="control")
    seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

    cells = [
        CellRecord(region_id=region_id, segmentation_id=seg_id,
                   label_value=i, centroid_x=100+i, centroid_y=200+i,
                   bbox_x=80+i, bbox_y=180+i, bbox_w=40, bbox_h=40,
                   area_pixels=1200+i*10)
        for i in range(1, 51)
    ]
    cell_ids = experiment.add_cells(cells)
    assert len(cell_ids) == 50

    df = experiment.get_cells(condition="control")
    assert len(df) == 50

    df_filtered = experiment.get_cells(min_area=1400)
    assert len(df_filtered) < 50
```

## Test 6: Measurements

```python
def test_measurements(experiment):
    # ... (setup channels, conditions, regions, cells as above)

    measurements = [
        MeasurementRecord(cell_id=cid, channel_id=gfp_id,
                          metric="mean_intensity", value=np.random.rand() * 1000)
        for cid in cell_ids
    ]
    experiment.add_measurements(measurements)

    df = experiment.get_measurements(channels=["GFP"], metrics=["mean_intensity"])
    assert len(df) == len(cell_ids)

    pivot = experiment.get_measurement_pivot()
    assert "GFP_mean_intensity" in pivot.columns

def test_measure_second_channel_independently(experiment):
    """Key test: measure a channel that wasn't used for segmentation."""
    # Segment on DAPI, then measure GFP without re-segmenting
    # ... setup ...
    experiment.add_measurements(gfp_measurements)
    experiment.add_measurements(rfp_measurements)

    pivot = experiment.get_measurement_pivot()
    assert "GFP_mean_intensity" in pivot.columns
    assert "RFP_mean_intensity" in pivot.columns
```

## Test 7: Label images

```python
def test_write_and_read_labels(experiment):
    # ... setup ...
    labels = np.zeros((512, 512), dtype=np.int32)
    labels[100:150, 100:150] = 1
    labels[200:260, 200:260] = 2

    experiment.write_labels("r1", "control", labels, segmentation_run_id=seg_id)
    result = experiment.read_labels("r1", "control")
    np.testing.assert_array_equal(result, labels)
```

## Test 8: NGFF metadata compliance

```python
def test_zarr_has_ngff_metadata(experiment):
    """Verify the OME-Zarr has valid NGFF 0.4 multiscales metadata."""
    # ... write an image ...
    import zarr
    store = zarr.open(str(experiment.images_zarr_path), mode="r")
    group = store["control/r1"]
    attrs = dict(group.attrs)

    assert "multiscales" in attrs
    ms = attrs["multiscales"][0]
    assert ms["version"] == "0.4"
    assert any(a["name"] == "y" and a["type"] == "space" for a in ms["axes"])
    assert any(a["name"] == "x" and a["type"] == "space" for a in ms["axes"])
```

## Test 9: Export

```python
def test_export_csv(experiment, tmp_path):
    # ... setup with cells and measurements ...
    csv_path = tmp_path / "results.csv"
    experiment.export_csv(csv_path, channels=["GFP"])
    df = pd.read_csv(csv_path)
    assert "cell_id" in df.columns
    assert "GFP_mean_intensity" in df.columns
```

## Test 10: Portability

```python
def test_percell_directory_is_portable(experiment, tmp_path):
    """Copying the .percell directory should produce a working experiment."""
    import shutil
    copy_path = tmp_path / "copy.percell"
    shutil.copytree(experiment.path, copy_path)

    with ExperimentStore.open(copy_path) as exp2:
        assert exp2.get_channels() == experiment.get_channels()
        assert exp2.get_cell_count() == experiment.get_cell_count()
```
