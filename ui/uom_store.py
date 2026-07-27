"""Persistence for confirmed UoM conversion decisions (uom_overrides.json).

A UoM conversion is a property of the MATERIAL (its SAP base unit), not of a
planning session: once the user confirms that a component is kg-entered in
ton-based recipes, that holds for every workbook and extract this
installation loads. The store therefore lives next to global_config.json in
the app data root (one per site installation) rather than in
sessions_store.json — engine rebuilds read it fresh via the mtime-cached
accessor, so all six state-sync paths see the same factors without carrying
per-session copies.

Shape:
{
  "overrides": {"200003726": 0.001, ...},   confirmed conversion factors
  "dismissed": {"400000482": true, ...},    explicit "leave as-is" answers
  "updated": "2026-07-27T..."
}

Dismissed components are remembered so the confirmation dialog never re-asks
a question the user already answered; they stay visible in the suspects
response, marked as dismissed, and can be cleared to re-decide.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

UOM_STORE_FILENAME = 'uom_overrides.json'

_store_path: Optional[Path] = None
_cache = {'mtime': None, 'record': None}

_EMPTY = {'overrides': {}, 'dismissed': {}}


def set_store_path(path) -> None:
    global _store_path
    _store_path = Path(path)
    _cache['mtime'] = None
    _cache['record'] = None


def get_store_path() -> Optional[Path]:
    return _store_path


def _load_record() -> dict:
    if _store_path is None:
        return dict(_EMPTY)
    try:
        mtime = _store_path.stat().st_mtime
    except OSError:
        _cache['mtime'] = None
        _cache['record'] = None
        return dict(_EMPTY)
    if _cache['mtime'] != mtime:
        _cache['record'] = _read_store(_store_path)
        _cache['mtime'] = mtime
    return _cache['record'] or dict(_EMPTY)


def _read_store(store_path: Path) -> dict:
    try:
        with open(store_path, 'r', encoding='utf-8') as f:
            store = json.load(f)
        if not isinstance(store, dict):
            return dict(_EMPTY)
        return {
            'overrides': {str(k): float(v) for k, v in (store.get('overrides') or {}).items()
                          if v not in (None, 0)},
            'dismissed': {str(k): True for k in (store.get('dismissed') or {})},
        }
    except Exception as exc:
        print(f'[uom_store] load error: {exc}')
        return dict(_EMPTY)


def _save_record(record: dict) -> None:
    if _store_path is None:
        return
    payload = {
        'overrides': record.get('overrides') or {},
        'dismissed': record.get('dismissed') or {},
        'updated': datetime.now().isoformat(timespec='seconds'),
    }
    # Atomic write (same pattern as config_store/session_store): a crash
    # mid-write must not corrupt confirmed conversion factors.
    tmp_path = _store_path.with_name(f'{_store_path.name}.tmp')
    try:
        _store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _store_path)
        _cache['mtime'] = None
        _cache['record'] = None
    except Exception as exc:
        print(f'[uom_store] save error: {exc}')
        try:
            tmp_path.unlink()
        except OSError:
            pass


def get_confirmed_overrides() -> Dict[str, float]:
    """Confirmed conversion factors, {component -> factor}. Read by
    engine_rebuild.get_config_overrides on every rebuild path."""
    return dict(_load_record().get('overrides') or {})


def get_dismissed() -> Dict[str, bool]:
    return dict(_load_record().get('dismissed') or {})


def record_decisions(decisions) -> dict:
    """Apply a batch of user decisions and persist.

    Each decision: {'component': str, 'action': 'convert'|'dismiss'|'clear',
    'factor': float (convert only, defaults to 0.001)}.
    'clear' forgets both a stored override and a dismissal, so the component
    is judged afresh on the next load. Returns the new store state.
    """
    record = _load_record()
    overrides = dict(record.get('overrides') or {})
    dismissed = dict(record.get('dismissed') or {})
    for decision in decisions or []:
        component = str(decision.get('component') or '').strip()
        action = decision.get('action')
        if not component or action not in ('convert', 'dismiss', 'clear'):
            continue
        overrides.pop(component, None)
        dismissed.pop(component, None)
        if action == 'convert':
            try:
                factor = float(decision.get('factor', 0.001) or 0.001)
            except (TypeError, ValueError):
                factor = 0.001
            if factor > 0 and factor != 1:
                overrides[component] = factor
        elif action == 'dismiss':
            dismissed[component] = True
    new_record = {'overrides': overrides, 'dismissed': dismissed}
    _save_record(new_record)
    return new_record
