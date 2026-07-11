"""Flask routes for the app-managed master store (master-config vervanging).

Import parses a master workbook ONCE with the existing xlsm loaders and
stores the serialized result; afterwards the monthly multi-file run needs no
base workbook. The app is the source of truth: re-import over an existing
store requires an explicit confirmation (diff shown first), and edits bump
the store version. Edits apply at the NEXT calculation — no auto-rebuild.
"""

import contextlib
import io
from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from modules.master_data import hydrate_loader, serialize_master
from ui import master_store

# Datasets exposed for view/edit, with their expected container type.
_DATASETS = {
    'config': dict,
    'fte': dict,
    'materials': list,
    'machines': list,
    'safety_stock': dict,
    'purchase': dict,
    'sales_prices': dict,
    'material_costs': dict,
    'machine_costs': dict,
    'valuation_params': (dict, type(None)),
}


def _status_payload(record) -> dict:
    if record is None:
        return {'exists': False}
    return {
        'exists': True,
        'version': record.get('version'),
        'imported_at': record.get('imported_at'),
        'edited_at': record.get('edited_at'),
        'source_filename': record.get('source_filename'),
        'counts': master_store.master_counts(record.get('master') or {}),
    }


def _validate_master(master: dict) -> None:
    """Validation by hydration: if a fresh DataLoader accepts the dict, every
    consumer will — no second validation rulebook to keep in sync."""
    from modules.data_loader import DataLoader

    probe = DataLoader(master_data=master)
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(probe, master)


def create_master_data_blueprint(
    global_config: dict,
    get_upload_dir: Callable[[], Path],
) -> Blueprint:
    bp = Blueprint('master_data', __name__)

    @bp.route('/api/master_data', methods=['GET'])
    def master_status():
        return jsonify(_status_payload(master_store.get_current_master_record()))

    @bp.route('/api/master_data/import', methods=['POST'])
    def import_master():
        """Parse a master workbook once and store the serialized result.

        Source: uploaded 'file' (multipart), else the config-tab master_file.
        Over an existing store a diff is returned first; pass confirm=true
        (form or JSON) to overwrite — the app owns the data.
        """
        store_path = master_store.get_store_path()
        if store_path is None:
            return jsonify({'error': 'Masterdata-opslag is niet geconfigureerd.'}), 500

        source_path = None
        source_name = ''
        if 'file' in request.files and request.files['file'].filename:
            upload = request.files['file']
            if not upload.filename.lower().endswith(('.xlsm', '.xlsx')):
                return jsonify({'error': 'Alleen .xlsm- of .xlsx-bestanden worden geaccepteerd.'}), 400
            safe_name = secure_filename(upload.filename)
            if not safe_name:
                return jsonify({'error': f'Ongeldige bestandsnaam: "{upload.filename}"'}), 400
            upload_dir = get_upload_dir()
            upload_dir.mkdir(parents=True, exist_ok=True)
            source_path = upload_dir / safe_name
            upload.save(str(source_path))
            source_name = upload.filename
        elif global_config.get('master_file') and Path(global_config['master_file']).exists():
            source_path = Path(global_config['master_file'])
            source_name = global_config.get('master_filename') or source_path.name
        else:
            return jsonify({'error': 'Geen bronbestand: upload een masterbestand of configureer er één in de Config-tab.'}), 400

        try:
            from modules.data_loader import DataLoader
            with contextlib.redirect_stdout(io.StringIO()):
                loader = DataLoader(excel_file=str(source_path))
                loader.load_all()
                master = serialize_master(loader)
                _validate_master(master)
        except Exception:
            return jsonify({'error': 'Kon het masterbestand niet inlezen. Controleer of alle vereiste sheets aanwezig zijn.'}), 400

        previous = master_store.get_current_master_record()
        confirm = str(request.form.get('confirm')
                      or (request.get_json(silent=True) or {}).get('confirm')
                      or '').lower() in ('true', '1', 'yes')
        if previous is not None and not confirm:
            return jsonify({
                'needs_confirm': True,
                'current': _status_payload(previous),
                'incoming': {
                    'source_filename': source_name,
                    'counts': master_store.master_counts(master),
                },
                'message': 'Er is al masterdata in de app (inclusief eventuele bewerkingen). '
                           'Importeren overschrijft die. Bevestig om door te gaan.',
            })

        record = master_store.save_master_store(
            store_path, master, source_filename=source_name, previous=previous)
        payload = _status_payload(record)
        payload['success'] = True
        return jsonify(payload)

    @bp.route('/api/master_data/<dataset>', methods=['GET'])
    def get_dataset(dataset):
        if dataset not in _DATASETS:
            return jsonify({'error': f'Onbekende dataset "{dataset}".'}), 404
        record = master_store.get_current_master_record()
        if record is None:
            return jsonify({'error': 'Geen masterdata in de app. Importeer eerst een masterbestand.'}), 400
        return jsonify({'dataset': dataset,
                        'value': (record.get('master') or {}).get(dataset),
                        'version': record.get('version')})

    @bp.route('/api/master_data/<dataset>', methods=['PATCH'])
    def patch_dataset(dataset):
        """Full-replace edit of one dataset; validated by hydration, version
        bump. Changes apply at the next calculation."""
        if dataset not in _DATASETS:
            return jsonify({'error': f'Onbekende dataset "{dataset}".'}), 404
        record = master_store.get_current_master_record()
        if record is None:
            return jsonify({'error': 'Geen masterdata in de app. Importeer eerst een masterbestand.'}), 400
        body = request.get_json(force=True, silent=True) or {}
        if 'value' not in body:
            return jsonify({'error': 'Verwacht een "value"-veld met de nieuwe dataset-inhoud.'}), 400
        value = body['value']
        expected = _DATASETS[dataset]
        if not isinstance(value, expected):
            return jsonify({'error': f'Ongeldig type voor "{dataset}".'}), 400

        candidate = dict(record.get('master') or {})
        candidate[dataset] = value
        try:
            _validate_master(candidate)
        except Exception as exc:
            return jsonify({'error': f'Wijziging geweigerd: {exc}'}), 400

        store_path = master_store.get_store_path()
        new_record = master_store.save_master_store(
            store_path, candidate, previous=record, edited=True)
        payload = _status_payload(new_record)
        payload.update({'success': True, 'requires_recalculate': True})
        return jsonify(payload)

    return bp
