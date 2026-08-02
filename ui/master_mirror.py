"""Canonical on-disk mirror of the master store (SOP_Masterdata_<site>.xlsx).

After every store mutation the workbook is regenerated so the file on disk
is always the current reference document ("als er iets verandert, kijken we
naar de master-Excel"). Excel holds an exclusive lock on open files on
Windows, so a refresh can fail while someone is reading the mirror — that
must never fail silently: the module records a stale-marker with the reason
and the UI shows it; the next successful refresh clears it.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from ui import master_store

_mirror_dir: Optional[Path] = None
# Laatste refresh-uitkomst; None = nog nooit geprobeerd deze proces-run.
_state = {'stale': False, 'reason': '', 'path': '', 'refreshed_at': ''}


def set_mirror_dir(path) -> None:
    global _mirror_dir
    _mirror_dir = Path(path)


def mirror_path_for_site(site: str) -> Optional[Path]:
    if _mirror_dir is None:
        return None
    safe_site = ''.join(c for c in (site or 'site') if c.isalnum() or c in '-_') or 'site'
    return _mirror_dir / f'SOP_Masterdata_{safe_site}.xlsx'


def refresh_mirror() -> dict:
    """Regenerate the mirror from the current store. Returns the new status.

    A locked/unwritable file marks the mirror stale instead of raising:
    store mutations must never fail because someone has the workbook open.
    """
    record = master_store.get_current_master_record()
    if record is None or _mirror_dir is None:
        return dict(_state)
    master = record['master']
    site = str(((master.get('config') or {}).get('site')) or 'site')
    path = mirror_path_for_site(site)
    try:
        from modules.master_workbook import export_master_workbook
        _mirror_dir.mkdir(parents=True, exist_ok=True)
        export_master_workbook(master, path, site=site,
                               store_version=record.get('version'))
        _state.update(stale=False, reason='', path=str(path),
                      refreshed_at=datetime.now().isoformat(timespec='seconds'))
    except OSError as exc:
        # Typisch: bestand open in Excel (WinError 32) — markeer en ga door.
        _state.update(stale=True, path=str(path),
                      reason=f'Werkboek kon niet worden bijgewerkt ({exc.__class__.__name__}). '
                             'Staat het bestand nog open in Excel?')
    except Exception as exc:  # bv. IllegalCharacterError uit openpyxl
        # De store-save is al gelukt; een exportfout mag de mutatie-route
        # niet in een 500 laten eindigen. Markeren, nooit stil falen.
        _state.update(stale=True, path=str(path),
                      reason=f'Werkboek kon niet worden gegenereerd: {exc}')
    return dict(_state)


def mirror_status() -> dict:
    status = dict(_state)
    if not status['path']:
        record = master_store.get_current_master_record()
        if record is not None:
            site = str(((record['master'].get('config') or {}).get('site')) or 'site')
            path = mirror_path_for_site(site)
            status['path'] = str(path) if path else ''
            if path is not None and not path.exists():
                status['stale'] = True
                status['reason'] = 'Nog geen spiegel geschreven — exporteer of wijzig masterdata.'
    return status
