"""Tests for percell4.core.db_types — UUID type aliases and helpers."""

from __future__ import annotations

import pytest

from percell4.core.db_types import (
    BioRepId,
    CellIdentityId,
    ChannelId,
    ConditionId,
    ExperimentId,
    FovId,
    IntensityGroupId,
    PipelineRunId,
    RoiId,
    RoiTypeDefinitionId,
    SegmentationSetId,
    ThresholdMaskId,
    TimepointId,
    new_uuid,
    str_to_uuid,
    uuid_to_str,
    validate_uuid_bytes,
)


class TestNewUuid:
    """Tests for new_uuid()."""

    def test_returns_bytes(self) -> None:
        result = new_uuid()
        assert isinstance(result, bytes)

    def test_returns_16_bytes(self) -> None:
        result = new_uuid()
        assert len(result) == 16

    def test_unique_each_call(self) -> None:
        a = new_uuid()
        b = new_uuid()
        assert a != b


class TestRoundTrip:
    """Tests for uuid_to_str / str_to_uuid round-trip."""

    def test_bytes_to_str_to_bytes(self) -> None:
        original = new_uuid()
        s = uuid_to_str(original)
        recovered = str_to_uuid(s)
        assert recovered == original

    def test_str_to_bytes_to_str(self) -> None:
        canonical = "550e8400-e29b-41d4-a716-446655440000"
        b = str_to_uuid(canonical)
        recovered = uuid_to_str(b)
        assert recovered == canonical

    def test_uuid_str_format(self) -> None:
        b = new_uuid()
        s = uuid_to_str(b)
        # Canonical UUID format: 8-4-4-4-12 hex digits
        parts = s.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]


class TestValidateUuidBytes:
    """Tests for validate_uuid_bytes()."""

    def test_accepts_valid_uuid(self) -> None:
        b = new_uuid()
        # Should not raise
        validate_uuid_bytes(b, "test")

    def test_rejects_wrong_length_short(self) -> None:
        with pytest.raises(ValueError, match="expected 16 bytes, got 8"):
            validate_uuid_bytes(b"\x00" * 8, "short_id")

    def test_rejects_wrong_length_long(self) -> None:
        with pytest.raises(ValueError, match="expected 16 bytes, got 32"):
            validate_uuid_bytes(b"\x00" * 32, "long_id")

    def test_rejects_empty_bytes(self) -> None:
        with pytest.raises(ValueError, match="expected 16 bytes, got 0"):
            validate_uuid_bytes(b"", "empty")

    def test_rejects_non_bytes_str(self) -> None:
        with pytest.raises(ValueError, match="expected bytes, got str"):
            validate_uuid_bytes("not-bytes", "bad_type")  # type: ignore[arg-type]

    def test_rejects_non_bytes_int(self) -> None:
        with pytest.raises(ValueError, match="expected bytes, got int"):
            validate_uuid_bytes(42, "bad_type")  # type: ignore[arg-type]

    def test_rejects_non_bytes_none(self) -> None:
        with pytest.raises(ValueError, match="expected bytes, got NoneType"):
            validate_uuid_bytes(None, "bad_type")  # type: ignore[arg-type]

    def test_error_message_includes_name(self) -> None:
        with pytest.raises(ValueError, match="my_field"):
            validate_uuid_bytes(b"\x00", "my_field")


class TestTypeAliasesExist:
    """Verify that all TypeAlias names are importable and resolve to bytes."""

    @pytest.mark.parametrize(
        "alias",
        [
            FovId,
            RoiId,
            SegmentationSetId,
            CellIdentityId,
            ExperimentId,
            ConditionId,
            ChannelId,
            BioRepId,
            TimepointId,
            ThresholdMaskId,
            PipelineRunId,
            IntensityGroupId,
            RoiTypeDefinitionId,
        ],
    )
    def test_alias_is_bytes(self, alias: type) -> None:
        assert alias is bytes
