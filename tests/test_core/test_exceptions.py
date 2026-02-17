"""Tests for percell3.core.exceptions."""

import pytest

from percell3.core.exceptions import (
    ChannelNotFoundError,
    ConditionNotFoundError,
    DuplicateError,
    ExperimentError,
    ExperimentNotFoundError,
    FovNotFoundError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_experiment_error(self):
        for exc_cls in (ExperimentNotFoundError, ChannelNotFoundError,
                        ConditionNotFoundError, FovNotFoundError, DuplicateError):
            assert issubclass(exc_cls, ExperimentError)

    def test_catch_all_with_base(self):
        with pytest.raises(ExperimentError):
            raise ChannelNotFoundError("DAPI")

    def test_experiment_not_found_message(self):
        exc = ExperimentNotFoundError("/some/path")
        assert "/some/path" in str(exc)
        assert exc.path == "/some/path"

    def test_channel_not_found_message(self):
        exc = ChannelNotFoundError("GFP")
        assert "GFP" in str(exc)
        assert exc.name == "GFP"

    def test_condition_not_found_message(self):
        exc = ConditionNotFoundError("control")
        assert "control" in str(exc)
        assert exc.name == "control"

    def test_fov_not_found_message(self):
        exc = FovNotFoundError("fov_1")
        assert "fov_1" in str(exc)
        assert exc.name == "fov_1"

    def test_duplicate_error_with_entity_and_name(self):
        exc = DuplicateError("channel", "DAPI")
        assert "channel" in str(exc)
        assert "DAPI" in str(exc)

    def test_duplicate_error_default_message(self):
        exc = DuplicateError()
        assert "Duplicate" in str(exc)
