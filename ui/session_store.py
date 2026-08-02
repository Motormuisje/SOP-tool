"""Persistence helpers for UI planning-session metadata."""

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Callable

from ui.parsers import format_purchased_and_produced


def save_sessions_to_disk(
    sessions: dict,
    active_session_id: str | None,
    sessions_store: Path,
    machine_overrides_from_engine: Callable[[dict, object], dict],
) -> None:
    """Persist session metadata without engine objects."""
    serializable = {}
    # Iterate over a snapshot: background threads (warmup/autorun) may insert
    # or delete sessions concurrently, and iterating the live dict would raise
    # "dictionary changed size during iteration" and lose the save.
    for sid, sess in list(sessions.items()):  # NOSONAR(S7504) list() is a deliberate snapshot
        # Persist current valuation_params per-session so rebuilds after
        # restart use the correct per-session values, not the shared global config.
        engine = sess.get('engine')
        vp_obj = getattr(getattr(engine, 'data', None), 'valuation_params', None)
        if vp_obj is not None:
            sess_vp = {
                '1': vp_obj.direct_fte_cost_per_month,
                '2': vp_obj.indirect_fte_cost_per_month,
                '3': vp_obj.overhead_cost_per_month,
                '4': vp_obj.sga_cost_per_month,
                '5': vp_obj.depreciation_per_year,
                '6': vp_obj.net_book_value,
                '7': vp_obj.days_sales_outstanding,
                '8': vp_obj.days_payable_outstanding,
            }
        else:
            # Sessieveld eerst (zelfde volgorde als PAP hieronder): het wordt
            # bij elke VP-save geschreven en is dus verser dan de baseline.
            # Baseline-eerst persisteerde de PRE-EDIT waarden zodra de engine
            # weg was (bv. na de cross-sessie-invalidatie van een
            # UoM-beslissing) en draaide een VP-edit stil terug na herstart.
            sess_vp = sess.get('valuation_params') or (sess.get('reset_baseline') or {}).get('valuation_params')
        # Persist purchased_and_produced per-session for the same reason as
        # valuation_params: cold rebuilds after restart must not inherit the
        # last-active session's PAP from the shared global config. Stored in
        # the string format config_overrides accepts ("MAT:0.5, ...").
        pap_obj = getattr(getattr(engine, 'data', None), 'purchased_and_produced', None)
        if pap_obj is not None:
            # A live engine is authoritative; {} formats to '' which means
            # DELIBERATELY CLEARED (distinct from None = never persisted).
            sess_pap = format_purchased_and_produced(pap_obj)
        else:
            sess_pap = sess.get('purchased_and_produced')
            if sess_pap is None:
                baseline_pap = (sess.get('reset_baseline') or {}).get('purchased_and_produced')
                sess_pap = format_purchased_and_produced(baseline_pap) if baseline_pap else None
        serializable[sid] = {
            'id': sess.get('id', sid),
            'file_path': sess.get('file_path', ''),
            'extract_files': sess.get('extract_files'),
            'filename': sess.get('filename', ''),
            'custom_name': sess.get('custom_name'),
            'is_snapshot': sess.get('is_snapshot', False),
            'metadata': sess.get('metadata', {}),
            'uploaded_at': sess.get('uploaded_at', ''),
            'parameters': sess.get('parameters'),
            'pending_edits': sess.get('pending_edits', {}),
            'value_aux_overrides': sess.get('value_aux_overrides', {}),
            'machine_overrides': (
                machine_overrides_from_engine(sess, engine)
                if engine is not None
                else sess.get('machine_overrides', {})
            ),
            # L4 starting stock (Dict[str, float]) and L7/L9/L11/L12 capacity
            # (Dict[str, Dict[str, Dict[str, float]]]) — both JSON-safe.
            'inventory_overrides': sess.get('inventory_overrides', {}),
            'capacity_overrides': sess.get('capacity_overrides', {}),
            'valuation_params': sess_vp,
            'purchased_and_produced': sess_pap,
            # Forecast defaults are per-session config: a cold rebuild must
            # never inherit them from the shared global config.
            'forecast_defaults': (
                ((getattr(engine, 'config_overrides', None) or {}).get('forecast_defaults') or {})
                if engine is not None
                else (sess.get('forecast_defaults') or {})
            ),
            # Added products (Fase 3): per-session config, same authority
            # rule as forecast_defaults (live engine wins, else session).
            'added_products': (
                ((getattr(engine, 'config_overrides', None) or {}).get('added_products') or [])
                if engine is not None
                else (sess.get('added_products') or [])
            ),
            # Annotations (Fase 2.1): pure metadata, JSON-safe.
            'comments': sess.get('comments', {}),
            # Material groups: named per-session material sets + the globally
            # active one (view metadata; no engine involvement).
            'material_groups': sess.get('material_groups', {}),
            'active_material_group': sess.get('active_material_group'),
        }
    store = {
        'active_session_id': active_session_id,
        'sessions': serializable,
    }
    tmp_path = sessions_store.with_name(f'{sessions_store.name}.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(store, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, sessions_store)


def save_scenarios_to_disk(scenarios: dict, scenarios_store: Path) -> None:
    """Persist saved scenarios (atomic, same pattern as the sessions store).

    Scenario payloads are built from request JSON and row dicts, so they are
    JSON-safe; default=str covers any stray non-JSON value.
    """
    store = {'scenarios': scenarios}
    tmp_path = scenarios_store.with_name(f'{scenarios_store.name}.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(store, f, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, scenarios_store)


def load_scenarios_from_disk(scenarios_store: Path) -> dict:
    """Restore saved scenarios; tolerate a missing or corrupt store file."""
    if not scenarios_store.exists():
        return {}
    try:
        with open(scenarios_store, 'r', encoding='utf-8') as f:
            store = json.load(f)
        scenarios = store.get('scenarios', {})
        return scenarios if isinstance(scenarios, dict) else {}
    except Exception as exc:
        print(f'[scenarios] load error: {exc}')
        try:
            corrupt_path = scenarios_store.with_name(
                f'{scenarios_store.name}.corrupt-{datetime.now().strftime("%Y%m%d%H%M%S")}'
            )
            scenarios_store.replace(corrupt_path)
            print(f'[scenarios] corrupt store moved to: {corrupt_path}')
        except Exception as move_exc:
            print(f'[scenarios] corrupt store could not be moved: {move_exc}')
        return {}


def load_sessions_from_disk(sessions_store: Path) -> tuple[dict, str | None]:
    """Restore session metadata from sessions_store.json on startup."""
    loaded_sessions = {}
    if not sessions_store.exists():
        return loaded_sessions, None

    try:
        with open(sessions_store, 'r', encoding='utf-8') as f:
            store = json.load(f)
        for sid, data in store.get('sessions', {}).items():
            loaded_sessions[sid] = {
                'id': data.get('id', sid),
                'file_path': data.get('file_path', ''),
                'extract_files': data.get('extract_files'),
                'filename': data.get('filename', ''),
                'custom_name': data.get('custom_name'),
                'is_snapshot': data.get('is_snapshot', False),
                'engine': None,
                'value_results': {},
                'metadata': data.get('metadata', {}),
                'uploaded_at': data.get('uploaded_at', ''),
                'parameters': data.get('parameters'),
                'pending_edits': data.get('pending_edits', {}),
                'value_aux_overrides': data.get('value_aux_overrides', {}),
                'machine_overrides': data.get('machine_overrides', {}),
                # Default to {} (not None) for sessions written before these
                # fields existed — downstream code uses dict.setdefault and
                # would crash on None.
                'inventory_overrides': data.get('inventory_overrides') or {},
                'capacity_overrides': data.get('capacity_overrides') or {},
                'valuation_params': data.get('valuation_params'),
                # None for store files written before this field existed.
                'purchased_and_produced': data.get('purchased_and_produced'),
                'forecast_defaults': data.get('forecast_defaults') or {},
                # [] for store files written before this field existed.
                'added_products': data.get('added_products') or [],
                'comments': data.get('comments') or {},
                'material_groups': data.get('material_groups') or {},
                'active_material_group': data.get('active_material_group'),
                'undo_stack': [],
                'redo_stack': [],
                'restore_status': 'cold' if data.get('parameters') is not None else 'pending',
                'restore_error': None,
            }
        saved_active = store.get('active_session_id')
        if saved_active and saved_active in loaded_sessions:
            active_session_id = saved_active
        elif loaded_sessions:
            active_session_id = next(iter(loaded_sessions))
        else:
            active_session_id = None
        return loaded_sessions, active_session_id
    except Exception as exc:
        print(f'[sessions] load error: {exc}')
        try:
            corrupt_path = sessions_store.with_name(
                f'{sessions_store.name}.corrupt-{datetime.now().strftime("%Y%m%d%H%M%S")}'
            )
            sessions_store.replace(corrupt_path)
            print(f'[sessions] corrupt store moved to: {corrupt_path}')
        except Exception as move_exc:
            print(f'[sessions] corrupt store could not be moved: {move_exc}')
        return {}, None
