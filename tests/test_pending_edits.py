import pytest

from ui.pending_edits import canonical_pending_edit_key, pending_edit_key


pytestmark = pytest.mark.no_fixture


def test_pending_edit_key_joins_four_parts():
    key = pending_edit_key("01. Demand forecast", "MAT-1", "Aux", "2025-12")

    assert key == "01. Demand forecast||MAT-1||Aux||2025-12"


def test_pending_edit_key_strips_aux_column_whitespace():
    key = pending_edit_key("01. Demand forecast", "MAT-1", "  Aux  ", "2025-12")

    assert key == "01. Demand forecast||MAT-1||Aux||2025-12"


def test_pending_edit_key_empty_aux_column():
    key = pending_edit_key("01. Demand forecast", "MAT-1", None, "2025-12")

    assert key == "01. Demand forecast||MAT-1||||2025-12"


def test_canonical_pending_edit_key_normalizes_whitespace():
    drifted = "01. Demand forecast||MAT-1|| Aux ||2025-12"

    assert canonical_pending_edit_key(drifted) == "01. Demand forecast||MAT-1||Aux||2025-12"


def test_canonical_pending_edit_key_malformed_returns_stripped_input():
    assert canonical_pending_edit_key("not||a||valid") == "not||a||valid"
    assert canonical_pending_edit_key("") == ""
    assert canonical_pending_edit_key(None) == ""


def test_trim_stack_group_aware_drops_whole_groups():
    """F2: trimming must never split a bulk group; singles pop one at a time."""
    from ui.pending_edits import trim_stack_group_aware

    group = [{"group_id": "g1", "i": i} for i in range(3)]
    singles = [{"i": 100 + i} for i in range(4)]
    stack = group + singles
    trim_stack_group_aware(stack, cap=6)  # over by 1 -> whole group of 3 drops
    assert stack == singles

    stack2 = [{"i": 0}] + [{"group_id": "g2", "i": i} for i in range(3)]
    trim_stack_group_aware(stack2, cap=3)  # over by 1 -> single head pops
    assert all(e.get("group_id") == "g2" for e in stack2)
    assert len(stack2) == 3

    under = [{"i": 1}, {"i": 2}]
    trim_stack_group_aware(under, cap=5)
    assert len(under) == 2
