"""Pending edit key helpers and undo-stack utilities."""

UNDO_STACK_CAP = 200


def trim_stack_group_aware(stack: list, cap: int = UNDO_STACK_CAP) -> None:
    """Trim an undo/redo stack from the front without splitting bulk groups.

    Bulk edits push contiguous entries sharing a ``group_id``; dropping only
    part of such a group would make a later group-undo restore a partial
    bulk silently. When the oldest entry belongs to a group, the whole group
    is dropped together.
    """
    while len(stack) > cap:
        head = stack[0]
        gid = head.get('group_id') if isinstance(head, dict) else None
        if gid:
            while stack and isinstance(stack[0], dict) and stack[0].get('group_id') == gid:
                stack.pop(0)
        else:
            stack.pop(0)


def aux_str(value) -> str:
    """Canonical string form of an aux column, for edit keys and JSON payloads.

    Only None (and '') collapse to ''. Numeric aux values keep their value:
    zero is a REAL aux (e.g. an L01 row with 0 actuals), so `aux or ''` is
    wrong — it made the backend key ('') diverge from the frontend key ('0'),
    splitting one cell over two pending-edit entries; the stale one then
    resurrected an undone edit on restart. Int-like floats render without the
    trailing '.0' so Python matches JavaScript's String(150.0) === '150'.
    """
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def pending_edit_key(line_type, material_number, aux_column, period) -> str:
    return (
        f"{str(line_type)}||"
        f"{str(material_number)}||"
        f"{aux_str(aux_column)}||"
        f"{str(period)}"
    )


def canonical_pending_edit_key(key: str) -> str:
    parts = str(key or '').split('||')
    if len(parts) != 4:
        return str(key or '').strip()
    line_type, material_number, aux_column, period = parts
    return pending_edit_key(line_type, material_number, aux_column, period)
