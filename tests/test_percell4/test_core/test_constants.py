"""Tests for percell4.core.constants."""

from __future__ import annotations

from enum import StrEnum

from percell4.core.constants import (
    ENTITY_TABLES,
    MERGE_TABLE_ORDER,
    SCOPE_DISPLAY,
    SCOPE_MASK_INSIDE,
    SCOPE_MASK_OUTSIDE,
    SCOPE_WHOLE_ROI,
    VALID_TRANSITIONS,
    FovStatus,
)


class TestFovStatus:
    """Tests for the FovStatus StrEnum."""

    def test_is_str_enum(self) -> None:
        assert issubclass(FovStatus, StrEnum)

    def test_all_values_present(self) -> None:
        expected = {
            "pending",
            "imported",
            "segmented",
            "measured",
            "analyzing",
            "qc_pending",
            "qc_done",
            "stale",
            "deleting",
            "deleted",
        }
        actual = {s.value for s in FovStatus}
        assert actual == expected

    def test_str_comparison(self) -> None:
        """FovStatus members compare equal to their string values."""
        assert FovStatus.pending == "pending"
        assert FovStatus.deleted == "deleted"

    def test_member_count(self) -> None:
        assert len(FovStatus) == 10


class TestValidTransitions:
    """Tests for VALID_TRANSITIONS mapping."""

    def test_maps_all_fov_status_values(self) -> None:
        for status in FovStatus:
            assert status in VALID_TRANSITIONS, f"Missing transition entry for {status}"

    def test_no_extra_keys(self) -> None:
        fov_statuses = set(FovStatus)
        assert set(VALID_TRANSITIONS.keys()) == fov_statuses

    def test_deleted_is_terminal(self) -> None:
        assert VALID_TRANSITIONS[FovStatus.deleted] == set()

    def test_pending_can_only_go_to_imported(self) -> None:
        assert VALID_TRANSITIONS[FovStatus.pending] == {FovStatus.imported}

    def test_deleting_goes_to_deleted(self) -> None:
        assert FovStatus.deleted in VALID_TRANSITIONS[FovStatus.deleting]

    def test_stale_allows_reimport(self) -> None:
        assert FovStatus.imported in VALID_TRANSITIONS[FovStatus.stale]

    def test_all_transition_targets_are_valid_statuses(self) -> None:
        """Every target status in transition sets must be a valid FovStatus."""
        for source, targets in VALID_TRANSITIONS.items():
            for target in targets:
                assert target in FovStatus, (
                    f"Invalid transition target: {source} -> {target}"
                )


class TestMergeTableOrder:
    """Tests for MERGE_TABLE_ORDER and ENTITY_TABLES."""

    def test_merge_table_order_contains_all_entity_tables(self) -> None:
        assert set(MERGE_TABLE_ORDER) == ENTITY_TABLES

    def test_no_duplicates_in_merge_order(self) -> None:
        assert len(MERGE_TABLE_ORDER) == len(set(MERGE_TABLE_ORDER))

    def test_entity_tables_is_frozenset(self) -> None:
        assert isinstance(ENTITY_TABLES, frozenset)

    def test_experiments_first(self) -> None:
        assert MERGE_TABLE_ORDER[0] == "experiments"


class TestScopeDisplay:
    """Tests for SCOPE_DISPLAY and scope constants."""

    def test_keys_match_scope_constants(self) -> None:
        expected_keys = {SCOPE_WHOLE_ROI, SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE}
        assert set(SCOPE_DISPLAY.keys()) == expected_keys

    def test_whole_roi_displays_as_whole_cell(self) -> None:
        assert SCOPE_DISPLAY[SCOPE_WHOLE_ROI] == "whole_cell"

    def test_mask_scopes_display_unchanged(self) -> None:
        assert SCOPE_DISPLAY[SCOPE_MASK_INSIDE] == "mask_inside"
        assert SCOPE_DISPLAY[SCOPE_MASK_OUTSIDE] == "mask_outside"
