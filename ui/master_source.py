"""Single decision point for which master-data source a session uses.

Historically four sources existed: a full base workbook per session, the
app-managed master store, the legacy global master_file fallback, and a
base_file upload alongside the extracts (unreachable from the UI, removed).
Upload, calculate, rebuild and autorun each encoded their own variant of
this choice with their own error message; this module is the one place
where the order lives, and the resolved source is recorded on the session
so the UI can show what a session actually calculated from.

Priority:
- an existing session's own workbook always stays its base (the app master
  store overlays it at load time when present);
- otherwise the app master store (extracts supply transactional data);
- otherwise the legacy master_file (deprecated; disappears in Fase 3);
- otherwise: no source (NO_MASTER_ERROR).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ui import master_store

NO_MASTER_ERROR = ('Geen masterdata: importeer masterdata in de Config-tab '
                   '(of upload een basiswerkboek).')


@dataclass
class MasterSource:
    kind: str                    # 'workbook' | 'store' | 'legacy_file'
    file_path: Optional[str]     # base workbook path; None on the store path
    master_data: Optional[dict]  # store payload for the engine (overlay or full)
    label: str                   # user-facing description, stored on the session

    def apply_to_session(self, sess: dict) -> None:
        """Record the resolved source on the session for the sidebar."""
        meta = sess.get('metadata')
        if isinstance(meta, dict):
            meta['master_source'] = self.label
            meta['master_source_kind'] = self.kind


def _store_master():
    record = master_store.get_current_master_record()
    if record is None:
        return None, None
    return record['master'], record.get('version')


def resolve_for_new_session(global_config: dict) -> Optional[MasterSource]:
    """Source for a fresh extracts-only upload (no workbook of its own)."""
    master, version = _store_master()
    if master is not None:
        return MasterSource('store', None, master, f'app-masterdata (v{version})')
    legacy = global_config.get('master_file')
    if legacy and Path(legacy).exists():
        return MasterSource('legacy_file', str(legacy), None,
                            f'legacy masterbestand ({Path(legacy).name})')
    return None


def resolve_for_session(sess: dict) -> Optional[MasterSource]:
    """Source for calculate/rebuild of an existing session.

    A session with its own workbook keeps it as base; the store rides along
    as overlay (app is the source of truth for master entities). A session
    without workbook ('' marker) calculates entirely from the store.
    """
    master, version = _store_master()
    file_path = sess.get('file_path') or None
    if file_path:
        label = 'werkboek'
        if master is not None:
            label += f' + app-masterdata (v{version})'
        return MasterSource('workbook', file_path, master, label)
    if master is not None:
        return MasterSource('store', None, master, f'app-masterdata (v{version})')
    return None
