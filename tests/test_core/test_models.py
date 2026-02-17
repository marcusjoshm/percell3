"""Tests for percell3.core.models."""

from percell3.core.models import ChannelConfig, CellRecord, MeasurementRecord, FovInfo


class TestChannelConfig:
    def test_construction(self):
        ch = ChannelConfig(id=1, name="DAPI", role="nucleus", color="#0000FF")
        assert ch.id == 1
        assert ch.name == "DAPI"
        assert ch.role == "nucleus"
        assert ch.color == "#0000FF"

    def test_defaults(self):
        ch = ChannelConfig(id=1, name="DAPI")
        assert ch.role is None
        assert ch.excitation_nm is None
        assert ch.emission_nm is None
        assert ch.color is None
        assert ch.is_segmentation is False
        assert ch.display_order == 0

    def test_equality(self):
        a = ChannelConfig(id=1, name="DAPI")
        b = ChannelConfig(id=1, name="DAPI")
        assert a == b


class TestFovInfo:
    def test_construction(self):
        r = FovInfo(id=1, name="r1", condition="control", width=2048, height=2048)
        assert r.name == "r1"
        assert r.condition == "control"
        assert r.width == 2048

    def test_defaults(self):
        r = FovInfo(id=1, name="r1", condition="ctrl")
        assert r.timepoint is None
        assert r.pixel_size_um is None
        assert r.source_file is None


class TestCellRecord:
    def test_construction(self):
        c = CellRecord(
            fov_id=1, segmentation_id=1, label_value=5,
            centroid_x=100.0, centroid_y=200.0,
            bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
            area_pixels=1200.0,
        )
        assert c.label_value == 5
        assert c.area_pixels == 1200.0

    def test_optional_fields(self):
        c = CellRecord(
            fov_id=1, segmentation_id=1, label_value=1,
            centroid_x=0, centroid_y=0,
            bbox_x=0, bbox_y=0, bbox_w=10, bbox_h=10,
            area_pixels=100,
        )
        assert c.area_um2 is None
        assert c.perimeter is None
        assert c.circularity is None


class TestMeasurementRecord:
    def test_construction(self):
        m = MeasurementRecord(cell_id=1, channel_id=2, metric="mean_intensity", value=42.5)
        assert m.cell_id == 1
        assert m.metric == "mean_intensity"
        assert m.value == 42.5
