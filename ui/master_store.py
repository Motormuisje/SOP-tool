"""Persistence for the app-managed master store (master-config vervanging).

The store file holds the serialized master data (see modules/master_data.py)
plus bookkeeping: version counter, import source and timestamps. Same atomic
write + corrupt-quarantine pattern as the session store.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

MASTER_STORE_FILENAME = 'master_store.json'

# Module-level store location, set once at app boot (ui/app.py). Read-side
# consumers (workflow calculate, engine rebuilds) use the mtime-cached
# accessor so every rebuild sees the LATEST store without re-reading the
# file on every request.
_store_path: Optional[Path] = None
_cache = {'mtime': None, 'record': None}


def set_store_path(path) -> None:
    global _store_path
    _store_path = Path(path)
    _cache['mtime'] = None
    _cache['record'] = None


def get_store_path() -> Optional[Path]:
    return _store_path


def get_current_master_record() -> Optional[dict]:
    """The latest stored master record, or None when no store exists."""
    if _store_path is None:
        return None
    try:
        mtime = _store_path.stat().st_mtime
    except OSError:
        _cache['mtime'] = None
        _cache['record'] = None
        return None
    if _cache['mtime'] != mtime:
        _cache['record'] = load_master_store(_store_path)
        _cache['mtime'] = mtime
    return _cache['record']


def load_master_store(store_path: Path) -> Optional[dict]:
    """The stored master dict, or None when absent/corrupt (quarantined)."""
    if not store_path.exists():
        return None
    try:
        with open(store_path, 'r', encoding='utf-8') as f:
            store = json.load(f)
        return store if isinstance(store, dict) and store.get('master') else None
    except Exception as exc:
        print(f'[master_store] load error: {exc}')
        try:
            corrupt_path = store_path.with_name(
                f'{store_path.name}.corrupt-{datetime.now().strftime("%Y%m%d%H%M%S")}')
            store_path.replace(corrupt_path)
            print(f'[master_store] corrupt store moved to: {corrupt_path}')
        except Exception as move_exc:
            print(f'[master_store] corrupt store could not be moved: {move_exc}')
        return None


def save_master_store(store_path: Path, master: dict, *, source_filename: str = '',
                      previous: Optional[dict] = None, edited: bool = False) -> dict:
    """Persist the master dict atomically; returns the full store record."""
    version = int((previous or {}).get('version') or 0) + 1
    record = {
        'version': version,
        'imported_at': (previous or {}).get('imported_at') if edited else datetime.now().isoformat(),
        'source_filename': (previous or {}).get('source_filename') if edited else source_filename,
        'edited_at': datetime.now().isoformat() if edited else (previous or {}).get('edited_at'),
        'master': master,
    }
    if not edited and not record['imported_at']:
        record['imported_at'] = datetime.now().isoformat()
    tmp_path = store_path.with_name(f'{store_path.name}.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(record, f, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, store_path)
    # Cache expliciet invalideren: twee saves binnen één (gecoalescede)
    # mtime-tick lieten de mtime-cache anders het pre-save-record serveren,
    # waarmee de compare-and-swap in de routes op stale data kon slagen —
    # precies de lost update die hij moet voorkomen.
    _cache['mtime'] = None
    _cache['record'] = None
    return record


def master_counts(master: dict) -> dict:
    """Dataset sizes for status displays and import diffs."""
    from modules.master_data import FTE_DATASETS

    counts = {
        'materials': len(master.get('materials') or []),
        'machines': len(master.get('machines') or []),
        'safety_stock': len(master.get('safety_stock') or {}),
        'purchase': len((master.get('purchase') or {}).get('lead_times') or {}),
        'sales_prices': len(master.get('sales_prices') or {}),
        'material_costs': len(master.get('material_costs') or {}),
        'machine_costs': len(master.get('machine_costs') or {}),
        'valuation_params': 1 if master.get('valuation_params') else 0,
    }
    counts.update({name: len(master.get(name) or {}) for name in FTE_DATASETS})
    return counts
