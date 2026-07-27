"""Central master-source resolver, rebuild guards, and the master-
consistency check (June-2026 failure class: transactional references to
materials without an active master record)."""

import json

import pytest

from modules.data_loader import DataLoader
from modules.models import BOMItem, Material, ProductType
from ui import master_store
from ui.master_source import (
    NO_MASTER_ERROR,
    resolve_for_new_session,
    resolve_for_session,
)

pytestmark = pytest.mark.no_fixture


@pytest.fixture
def store_path(tmp_path):
    path = tmp_path / 'master_store.json'
    master_store.set_store_path(path)
    yield path
    master_store.set_store_path(tmp_path / 'gone.json')


def _write_store(path, version=3):
    path.write_text(json.dumps({
        'master': {'schema_version': 1},
        'version': version,
    }), encoding='utf-8')


class TestResolveForNewSession:
    def test_store_wins(self, store_path, tmp_path):
        _write_store(store_path)
        legacy = tmp_path / 'master.xlsm'
        legacy.write_bytes(b'x')
        src = resolve_for_new_session({'master_file': str(legacy)})
        assert src.kind == 'store'
        assert src.file_path is None
        assert src.master_data == {'schema_version': 1}
        assert 'v3' in src.label

    def test_legacy_file_fallback(self, store_path, tmp_path):
        legacy = tmp_path / 'master.xlsm'
        legacy.write_bytes(b'x')
        src = resolve_for_new_session({'master_file': str(legacy)})
        assert src.kind == 'legacy_file'
        assert src.file_path == str(legacy)
        assert src.master_data is None

    def test_missing_legacy_file_is_no_source(self, store_path, tmp_path):
        src = resolve_for_new_session({'master_file': str(tmp_path / 'weg.xlsm')})
        assert src is None

    def test_nothing_configured_is_no_source(self, store_path):
        assert resolve_for_new_session({}) is None


class TestResolveForSession:
    def test_workbook_session_keeps_workbook_and_gets_overlay(self, store_path):
        _write_store(store_path)
        src = resolve_for_session({'file_path': 'c:/x/werkboek.xlsm'})
        assert src.kind == 'workbook'
        assert src.file_path == 'c:/x/werkboek.xlsm'
        assert src.master_data == {'schema_version': 1}
        assert 'app-masterdata' in src.label

    def test_workbook_session_without_store(self, store_path):
        src = resolve_for_session({'file_path': 'c:/x/werkboek.xlsm'})
        assert src.kind == 'workbook'
        assert src.master_data is None
        assert src.label == 'werkboek'

    def test_store_session(self, store_path):
        _write_store(store_path, version=7)
        src = resolve_for_session({'file_path': ''})
        assert src.kind == 'store'
        assert src.file_path is None
        assert 'v7' in src.label

    def test_no_source(self, store_path):
        assert resolve_for_session({'file_path': ''}) is None

    def test_apply_to_session_records_metadata(self, store_path):
        _write_store(store_path)
        sess = {'file_path': '', 'metadata': {}}
        resolve_for_session(sess).apply_to_session(sess)
        assert sess['metadata']['master_source_kind'] == 'store'
        assert 'app-masterdata' in sess['metadata']['master_source']

    def test_apply_to_session_tolerates_missing_metadata(self, store_path):
        _write_store(store_path)
        sess = {'file_path': ''}
        resolve_for_session(sess).apply_to_session(sess)  # geen crash
        assert 'metadata' not in sess


class TestRebuildGuards:
    def test_store_session_without_extracts_returns_none(self, store_path):
        # Voorheen: DataLoader.load_all viel door naar pd.read_excel(None)
        # en crashte. Nu weigert de rebuild netjes.
        from ui.engine_rebuild import build_clean_engine_for_session
        _write_store(store_path)
        sess = {
            'file_path': '',
            'extract_files': None,
            'parameters': {'planning_month': '2026/06'},
        }
        assert build_clean_engine_for_session(sess, {}) is None

    def test_error_message_is_shared(self):
        assert 'masterdata' in NO_MASTER_ERROR.lower()


def _mat(num, active=True):
    return Material(material_number=num, name=f'{num} naam',
                    product_type=ProductType.RAW_MATERIAL,
                    product_family='F', is_active=active)


def _bom(parent, component):
    return BOMItem(plant='NLK1', parent_material=parent, parent_name='',
                   component_material=component, component_name='',
                   quantity_per=1.0)


class TestMasterConsistency:
    def _loader(self):
        dl = DataLoader(master_data={'schema_version': 1})
        dl.materials = {'A': _mat('A'), 'B': _mat('B', active=False)}
        return dl

    def test_flags_missing_and_inactive_references(self):
        dl = self._loader()
        dl.bom = [_bom('A', 'X')]              # X ontbreekt in master
        dl.forecasts = {'B': {'2026-06': 5.0}}  # B is gedeactiveerd
        # Stock is bewust GEEN referentiebron: de stock-sheet is een
        # volledige SAP-dump (spares, consignatie) en zou honderden
        # stock-only meldingen produceren die het echte signaal begraven.
        dl.stock_levels = {'C': 5.0}
        dl._check_master_consistency()
        by_mat = {w['material']: w for w in dl.master_consistency_warnings}
        assert by_mat['X']['issue'] == 'missing'
        assert by_mat['X']['referenced_in'] == ['BOM']
        assert by_mat['B']['issue'] == 'inactive'
        assert 'C' not in by_mat

    def test_clean_data_produces_no_warnings(self):
        dl = self._loader()
        dl.bom = [_bom('A', 'A')]
        dl.forecasts = {'A': {'2026-06': 5.0}}
        dl.stock_levels = {'A': 2.0}
        dl._check_master_consistency()
        assert dl.master_consistency_warnings == []

    def test_no_materials_means_no_judgement(self):
        # Zonder masterdata (kale extract-preview) is er niets om tegen te
        # toetsen; dan geen ruis produceren.
        dl = DataLoader(master_data={'schema_version': 1})
        dl.bom = [_bom('A', 'X')]
        dl._check_master_consistency()
        assert dl.master_consistency_warnings == []
