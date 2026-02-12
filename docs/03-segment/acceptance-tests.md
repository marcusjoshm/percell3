# Module 3: Segment — Acceptance Tests

## Test 1: Cellpose adapter runs on synthetic image

```python
def test_cellpose_segment_synthetic():
    """Cellpose can segment a synthetic image with known cells."""
    adapter = CellposeAdapter()
    # Create image with bright circular regions on dark background
    image = np.zeros((512, 512), dtype=np.uint16)
    rr, cc = disk((100, 100), 30)
    image[rr, cc] = 50000
    rr, cc = disk((300, 300), 40)
    image[rr, cc] = 45000

    params = SegmentationParams(channel="DAPI", model_name="cyto3", diameter=60)
    labels = adapter.segment(image, params)

    assert labels.shape == (512, 512)
    assert labels.dtype == np.int32
    assert labels.max() >= 2  # At least 2 cells detected
```

## Test 2: Label processor extracts correct properties

```python
def test_label_processor():
    processor = LabelProcessor()
    labels = np.zeros((256, 256), dtype=np.int32)
    labels[50:80, 50:80] = 1   # 30x30 square = 900 pixels
    labels[150:200, 150:200] = 2  # 50x50 square = 2500 pixels

    cells = processor.extract_cells(labels, region_id=1, segmentation_id=1,
                                    pixel_size_um=0.65)
    assert len(cells) == 2
    assert cells[0].label_value == 1
    assert cells[0].area_pixels == 900
    assert cells[0].area_um2 == pytest.approx(900 * 0.65**2, rel=0.01)
    assert cells[1].area_pixels == 2500
    # Check bbox
    assert cells[0].bbox_x == 50
    assert cells[0].bbox_w == 30
```

## Test 3: Full segmentation pipeline with ExperimentStore

```python
def test_segment_experiment(experiment_with_images):
    """End-to-end: segment -> labels stored -> cells in database."""
    store = experiment_with_images  # fixture with DAPI image already imported

    seg_id = segment_experiment(store, SegmentationParams(channel="DAPI"))

    # Labels should be stored
    labels = store.read_labels("region_1", "control")
    assert labels.shape == (512, 512)
    assert labels.max() > 0

    # Cells should be in database
    cell_count = store.get_cell_count()
    assert cell_count > 0

    df = store.get_cells()
    assert "centroid_x" in df.columns
    assert "area_pixels" in df.columns
```

## Test 4: Import pre-existing labels

```python
def test_import_labels(experiment_with_images):
    store = experiment_with_images
    labels = np.zeros((512, 512), dtype=np.int32)
    labels[100:150, 100:150] = 1
    labels[200:260, 200:260] = 2

    importer = RoiImporter()
    seg_id = importer.import_labels(labels, store, "region_1", "control")

    assert store.get_cell_count() == 2
    stored_labels = store.read_labels("region_1", "control")
    np.testing.assert_array_equal(stored_labels, labels)
```

## Test 5: Segmentation on non-DAPI channel

```python
def test_segment_any_channel(experiment_with_multichannel):
    """Can segment on GFP instead of DAPI."""
    store = experiment_with_multichannel
    seg_id = segment_experiment(store, SegmentationParams(channel="GFP"))
    assert store.get_cell_count() > 0
```
