"""Tests for percell3.core.zarr_io."""

from pathlib import Path

import dask.array as da
import numpy as np
import pytest
import zarr

from percell3.core import zarr_io


@pytest.fixture
def images_zarr(tmp_path: Path) -> Path:
    p = tmp_path / "images.zarr"
    zarr_io.init_zarr_store(p)
    return p


@pytest.fixture
def labels_zarr(tmp_path: Path) -> Path:
    p = tmp_path / "labels.zarr"
    zarr_io.init_zarr_store(p)
    return p


@pytest.fixture
def masks_zarr(tmp_path: Path) -> Path:
    p = tmp_path / "masks.zarr"
    zarr_io.init_zarr_store(p)
    return p


class TestInitZarrStore:
    def test_creates_store(self, tmp_path):
        p = tmp_path / "test.zarr"
        zarr_io.init_zarr_store(p)
        root = zarr.open(str(p), mode="r")
        assert root.attrs["percell_version"] == "3.0.0"


class TestImageIO:
    def test_write_and_read_single_channel(self, images_zarr):
        data = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)
        gp = zarr_io.image_group_path("control", "r1")
        channels_meta = [{"name": "DAPI", "color": "#0000FF"}]

        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=0, num_channels=1,
            data=data, channels_meta=channels_meta,
        )

        result = zarr_io.read_image_channel_numpy(images_zarr, gp, channel_index=0)
        np.testing.assert_array_equal(result, data)

    def test_read_as_dask(self, images_zarr):
        data = np.random.randint(0, 65535, (128, 128), dtype=np.uint16)
        gp = zarr_io.image_group_path("control", "r1")
        channels_meta = [{"name": "DAPI", "color": "#0000FF"}]

        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=0, num_channels=1,
            data=data, channels_meta=channels_meta,
        )

        result = zarr_io.read_image_channel(images_zarr, gp, channel_index=0)
        assert isinstance(result, da.Array)
        np.testing.assert_array_equal(result.compute(), data)

    def test_multi_channel_write(self, images_zarr):
        dapi = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)
        gfp = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)
        gp = zarr_io.image_group_path("control", "r1")
        channels_meta = [
            {"name": "DAPI", "color": "#0000FF"},
            {"name": "GFP", "color": "#00FF00"},
        ]

        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=0, num_channels=2,
            data=dapi, channels_meta=channels_meta,
        )
        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=1, num_channels=2,
            data=gfp, channels_meta=channels_meta,
        )

        result_dapi = zarr_io.read_image_channel_numpy(images_zarr, gp, 0)
        result_gfp = zarr_io.read_image_channel_numpy(images_zarr, gp, 1)
        np.testing.assert_array_equal(result_dapi, dapi)
        np.testing.assert_array_equal(result_gfp, gfp)

    def test_ngff_metadata(self, images_zarr):
        data = np.random.randint(0, 65535, (128, 128), dtype=np.uint16)
        gp = zarr_io.image_group_path("control", "r1")
        channels_meta = [{"name": "DAPI", "color": "#0000FF"}]

        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=0, num_channels=1,
            data=data, channels_meta=channels_meta, pixel_size_um=0.65,
        )

        root = zarr.open(str(images_zarr), mode="r")
        group = root["control/r1"]
        attrs = dict(group.attrs)

        assert "multiscales" in attrs
        ms = attrs["multiscales"][0]
        assert ms["version"] == "0.4"
        assert any(a["name"] == "c" and a["type"] == "channel" for a in ms["axes"])
        assert any(a["name"] == "y" and a["type"] == "space" for a in ms["axes"])
        assert any(a["name"] == "x" and a["type"] == "space" for a in ms["axes"])

        assert "omero" in attrs
        assert attrs["omero"]["channels"][0]["label"] == "DAPI"

    def test_with_timepoint(self, images_zarr):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        gp = zarr_io.image_group_path("control", "r1", timepoint="t0")
        assert gp == "control/t0/r1"

        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=0, num_channels=1,
            data=data, channels_meta=[{"name": "DAPI"}],
        )
        result = zarr_io.read_image_channel_numpy(images_zarr, gp, 0)
        np.testing.assert_array_equal(result, data)

    def test_add_channel_resizes(self, images_zarr):
        """Adding a third channel after creating with 2 resizes the array."""
        gp = zarr_io.image_group_path("control", "r1")
        d1 = np.ones((64, 64), dtype=np.uint16)
        d2 = np.ones((64, 64), dtype=np.uint16) * 2

        # Write with num_channels=2
        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=0, num_channels=2,
            data=d1, channels_meta=[{"name": "DAPI"}, {"name": "GFP"}],
        )
        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=1, num_channels=2,
            data=d2, channels_meta=[{"name": "DAPI"}, {"name": "GFP"}],
        )

        # Now write a 3rd channel (resize to 3)
        d3 = np.ones((64, 64), dtype=np.uint16) * 3
        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=2, num_channels=3,
            data=d3,
            channels_meta=[{"name": "DAPI"}, {"name": "GFP"}, {"name": "RFP"}],
        )

        # Verify all 3 channels
        np.testing.assert_array_equal(
            zarr_io.read_image_channel_numpy(images_zarr, gp, 0), d1
        )
        np.testing.assert_array_equal(
            zarr_io.read_image_channel_numpy(images_zarr, gp, 2), d3
        )


class TestLabelIO:
    def test_write_and_read(self, labels_zarr):
        labels = np.zeros((256, 256), dtype=np.int32)
        labels[50:100, 50:100] = 1
        labels[150:200, 150:200] = 2
        gp = zarr_io.label_group_path("control", "r1")

        zarr_io.write_labels(labels_zarr, gp, labels)
        result = zarr_io.read_labels(labels_zarr, gp)
        np.testing.assert_array_equal(result, labels)

    def test_label_dtype_int32(self, labels_zarr):
        labels = np.ones((64, 64), dtype=np.uint16) * 5
        gp = zarr_io.label_group_path("control", "r1")
        zarr_io.write_labels(labels_zarr, gp, labels)

        root = zarr.open(str(labels_zarr), mode="r")
        arr = root[f"{gp}/0"]
        assert arr.dtype == np.int32

    def test_label_ngff_metadata(self, labels_zarr):
        labels = np.zeros((64, 64), dtype=np.int32)
        gp = zarr_io.label_group_path("control", "r1")
        zarr_io.write_labels(labels_zarr, gp, labels, source_image_path="../../images.zarr/control/r1")

        root = zarr.open(str(labels_zarr), mode="r")
        group = root["control/r1"]
        attrs = dict(group.attrs)
        assert "image-label" in attrs
        assert attrs["image-label"]["version"] == "0.4"
        assert "multiscales" in attrs

    def test_overwrite_labels(self, labels_zarr):
        gp = zarr_io.label_group_path("control", "r1")

        labels1 = np.ones((64, 64), dtype=np.int32)
        zarr_io.write_labels(labels_zarr, gp, labels1)

        labels2 = np.ones((64, 64), dtype=np.int32) * 2
        zarr_io.write_labels(labels_zarr, gp, labels2)

        result = zarr_io.read_labels(labels_zarr, gp)
        np.testing.assert_array_equal(result, labels2)


class TestMaskIO:
    def test_write_and_read(self, masks_zarr):
        mask = np.zeros((128, 128), dtype=bool)
        mask[20:80, 20:80] = True
        gp = zarr_io.mask_group_path("control", "r1", "GFP")

        zarr_io.write_mask(masks_zarr, gp, mask)
        result = zarr_io.read_mask(masks_zarr, gp)

        # Stored as uint8 0/255
        assert result.dtype == np.uint8
        assert result[50, 50] == 255
        assert result[0, 0] == 0

    def test_mask_path(self):
        gp = zarr_io.mask_group_path("control", "r1", "GFP")
        assert gp == "control/r1/threshold_GFP"

    def test_mask_path_with_timepoint(self):
        gp = zarr_io.mask_group_path("control", "r1", "GFP", timepoint="t0")
        assert gp == "control/t0/r1/threshold_GFP"


# === ndim validation tests ===


class TestNdimValidation:
    def test_write_image_rejects_3d(self, images_zarr):
        data_3d = np.zeros((1, 64, 64), dtype=np.uint16)
        gp = zarr_io.image_group_path("control", "r1")
        with pytest.raises(ValueError, match="Expected 2D"):
            zarr_io.write_image_channel(
                images_zarr, gp, channel_index=0, num_channels=1,
                data=data_3d, channels_meta=[{"name": "DAPI"}],
            )

    def test_write_labels_rejects_3d(self, labels_zarr):
        data_3d = np.zeros((64, 64, 1), dtype=np.int32)
        gp = zarr_io.label_group_path("control", "r1")
        with pytest.raises(ValueError, match="Expected 2D"):
            zarr_io.write_labels(labels_zarr, gp, data_3d)

    def test_write_mask_rejects_1d(self, masks_zarr):
        data_1d = np.zeros((100,), dtype=bool)
        gp = zarr_io.mask_group_path("control", "r1", "GFP")
        with pytest.raises(ValueError, match="Expected 2D"):
            zarr_io.write_mask(masks_zarr, gp, data_1d)

    def test_write_image_accepts_2d(self, images_zarr):
        data_2d = np.zeros((64, 64), dtype=np.uint16)
        gp = zarr_io.image_group_path("control", "r1")
        zarr_io.write_image_channel(
            images_zarr, gp, channel_index=0, num_channels=1,
            data=data_2d, channels_meta=[{"name": "DAPI"}],
        )
        result = zarr_io.read_image_channel_numpy(images_zarr, gp, 0)
        np.testing.assert_array_equal(result, data_2d)
