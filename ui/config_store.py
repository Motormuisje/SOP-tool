"""Persistence and folder resolution helpers for UI global config."""

import json
import logging
import os
from pathlib import Path


def load_global_config(config_file: Path) -> dict:
    if not config_file.exists():
        return {}
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as exc:
        logging.getLogger(__name__).error(f'global_config load error: {exc}')
        return {}


def save_global_config(config_file: Path, global_config: dict) -> None:
    # Atomic write (same pattern as session_store.save_sessions_to_disk):
    # write to a temp file, fsync, then os.replace. A crash mid-write can no
    # longer corrupt global_config.json (which load_global_config would then
    # silently replace with {}).
    tmp_path = config_file.with_name(f'{config_file.name}.tmp')
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(global_config, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, config_file)
    except Exception as exc:
        print(f'[global_config] save error: {exc}')
        try:
            tmp_path.unlink()
        except OSError:
            pass


def sync_global_config_from_engine(engine, global_config, format_pap) -> None:
    """Pull the active session's engine state back into global_config so all
    subsequent reads/writes use values that belong to the active session.

    Note: ``inventory_overrides`` (L4 starting stock per material) and
    ``capacity_overrides`` (L7/L9/L11/L12 per line_type/material/period) are
    deliberately NOT synced here. They are per-session edit stores (like
    ``pending_edits``) and live exclusively on the session dict; copying
    them to ``_global_config`` would cause cross-session contamination on
    active-session switch.
    """
    if engine is None or getattr(engine, 'data', None) is None:
        return
    vp = getattr(engine.data, 'valuation_params', None)
    if vp is not None:
        global_config['valuation_params'] = {
            '1': vp.direct_fte_cost_per_month,
            '2': vp.indirect_fte_cost_per_month,
            '3': vp.overhead_cost_per_month,
            '4': vp.sga_cost_per_month,
            '5': vp.depreciation_per_year,
            '6': vp.net_book_value,
            '7': vp.days_sales_outstanding,
            '8': vp.days_payable_outstanding,
        }
    pap = getattr(engine.data, 'purchased_and_produced', None)
    if pap is not None:
        global_config['purchased_and_produced'] = format_pap(pap)
    # Forecast defaults are per-session; mirror the ACTIVE session's value into
    # global config so the config UI and fresh /api/calculate runs see it, and
    # so a stale value from the previous session cannot linger.
    fd = (getattr(engine, 'config_overrides', None) or {}).get('forecast_defaults')
    global_config['forecast_defaults'] = fd or {}
    # Added products (Fase 3) are per-session; mirror the ACTIVE session's
    # list into global config so fresh /api/calculate runs keep them and a
    # stale list from the previous session cannot linger.
    ap = (getattr(engine, 'config_overrides', None) or {}).get('added_products')
    global_config['added_products'] = list(ap or [])


def resolve_folder_paths(global_config: dict, default_folders: dict) -> tuple[Path, Path, Path]:
    folders = global_config.get('folders', {})
    uploads = folders.get('uploads') or default_folders['uploads']
    exports = folders.get('exports') or default_folders['exports']
    sessions = folders.get('sessions') or default_folders['sessions']
    return Path(uploads), Path(exports), Path(sessions)


def ensure_folder_paths(uploads_dir: Path, exports_dir: Path, sessions_dir: Path) -> None:
    uploads_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)


def apply_folder_config(global_config: dict, default_folders: dict) -> tuple[Path, Path, Path]:
    uploads_dir, exports_dir, sessions_dir = resolve_folder_paths(global_config, default_folders)
    ensure_folder_paths(uploads_dir, exports_dir, sessions_dir)
    return uploads_dir, exports_dir, sessions_dir / 'sessions_store.json'
