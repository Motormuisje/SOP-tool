"""JSON-safe payload builders for the Flask UI."""

from datetime import datetime
from enum import Enum

from modules.models import LineType
from ui.pending_edits import aux_str


def moq_warnings_payload(engine) -> dict:
    """Build moq_raw_needs dict for frontend MOQ warning rendering."""
    return {'moq_raw_needs': getattr(engine, 'all_purch_raw_needs', {}) or {}}


def uom_suspects_payload(engine) -> dict:
    """UoM-guard state for the frontend confirmation dialog.

    Suspects/warnings come from the engine's loaded data (modules/uom_guard),
    annotated with the stored installation-wide decisions (ui/uom_store):
    confirmed factors, and dismissals so the dialog never re-asks an
    answered question.
    """
    from ui import uom_store
    data = getattr(engine, 'data', None) if engine is not None else None
    dismissed = uom_store.get_dismissed()
    suspects = []
    for s in (getattr(data, 'uom_suspects', None) or []):
        entry = s.to_dict()
        entry['dismissed'] = bool(dismissed.get(s.component_material))
        suspects.append(entry)
    return {
        'suspects': suspects,
        'open_suspects': sum(1 for s in suspects if not s['dismissed']),
        'recipe_warnings': [w.to_dict() for w in (getattr(data, 'uom_recipe_warnings', None) or [])],
        'applied': [
            {'component': component, 'factor': factor, 'rows': rows}
            for component, factor, rows in (getattr(data, 'uom_overrides_applied', None) or [])
        ],
        'overrides': uom_store.get_confirmed_overrides(),
        'dismissed': sorted(dismissed),
        # Componenten waarvan de dosering na conversie < 0.1 g/ton uitkomt:
        # sterk signaal dat de bron intussen zelf gecorrigeerd is en de
        # opgeslagen factor dubbelop werkt. Console-only was onzichtbaar.
        'double_conversion': list(getattr(data, 'uom_double_warnings', None) or []),
    }


def value_results_payload(engine) -> dict:
    value_results = {
        lt: [row_payload(row) for row in rows]
        for lt, rows in (getattr(engine, 'value_results', {}) or {}).items()
    }
    return {
        'value_results': value_results,
        'consolidation': value_results.get(LineType.CONSOLIDATION.value, []),
    }


def planning_value_payload(engine) -> dict:
    return {
        'periods': list(getattr(engine.data, 'periods', []) or []),
        'results': {
            lt: [row_payload(row) for row in rows]
            for lt, rows in (getattr(engine, 'results', {}) or {}).items()
        },
        **value_results_payload(engine),
        **moq_warnings_payload(engine),
    }


def json_safe(value):
    """Convert row payloads to plain JSON types.

    Some test doubles and optional model fields can contain objects such as
    MagicMock. API responses should stay serializable even when an optional
    display-only field has an unexpected object value.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float('inf'), float('-inf')):
            return None
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(json_safe(k)): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, Enum):
        return json_safe(value.value)
    try:
        item = value.item
    except AttributeError:
        item = None
    if callable(item):
        try:
            return json_safe(item())
        except Exception:
            pass
    return str(value)


def row_payload(row) -> dict:
    payload = json_safe(row.to_dict())
    # Aux columns leave the API as canonical STRINGS. Numeric aux values
    # (0, 150.0) serialized as JSON numbers before, and every falsy-zero
    # `aux || ''` in the frontend then built a different edit key than the
    # backend ('' vs '0') — an undone edit resurrected after restart.
    payload['aux_column'] = aux_str(payload.get('aux_column'))
    payload['aux_2_column'] = aux_str(payload.get('aux_2_column'))
    return payload
