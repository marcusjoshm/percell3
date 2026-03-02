"""Tests for Phase 4: plugin input requirements."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Test: Plugin input requirements
# ---------------------------------------------------------------------------


class TestPluginInputRequirements:
    """Tests for PluginInputRequirement framework."""

    def test_base_class_returns_empty(self):
        """AnalysisPlugin.required_inputs() defaults to empty."""
        from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult

        class DummyPlugin(AnalysisPlugin):
            def info(self):
                return PluginInfo(name="test", version="1.0", description="test")

            def validate(self, store):
                return []

            def run(self, store, cell_ids=None, parameters=None, progress_callback=None):
                return PluginResult(measurements_written=0, cells_processed=0)

        plugin = DummyPlugin()
        assert plugin.required_inputs() == []

    def test_input_kind_enum(self):
        from percell3.plugins.base import InputKind

        assert InputKind.SEGMENTATION == "segmentation"
        assert InputKind.THRESHOLD == "threshold"

    def test_split_halo_declares_inputs(self):
        from percell3.plugins.builtin.split_halo_condensate_analysis import (
            SplitHaloCondensateAnalysisPlugin,
        )
        from percell3.plugins.base import InputKind

        plugin = SplitHaloCondensateAnalysisPlugin()
        inputs = plugin.required_inputs()
        assert len(inputs) == 2
        kinds = {inp.kind for inp in inputs}
        assert InputKind.SEGMENTATION in kinds
        assert InputKind.THRESHOLD in kinds

    def test_local_bg_declares_inputs(self):
        from percell3.plugins.builtin.local_bg_subtraction import (
            LocalBGSubtractionPlugin,
        )
        from percell3.plugins.base import InputKind

        plugin = LocalBGSubtractionPlugin()
        inputs = plugin.required_inputs()
        assert len(inputs) == 2
        kinds = {inp.kind for inp in inputs}
        assert InputKind.SEGMENTATION in kinds
        assert InputKind.THRESHOLD in kinds

    def test_requirement_channel_filter(self):
        from percell3.plugins.base import InputKind, PluginInputRequirement

        req = PluginInputRequirement(kind=InputKind.THRESHOLD, channel="GFP")
        assert req.channel == "GFP"
        assert req.kind == InputKind.THRESHOLD
