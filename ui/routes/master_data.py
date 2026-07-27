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
from ui import master_mirror, master_store

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
    master = record.get('master') or {}
    cfg = master.get('config') or {}
    actuals = (master.get('purchase') or {}).get('actuals') or {}
    return {
        'exists': True,
        'version': record.get('version'),
        'imported_at': record.get('imported_at'),
        'edited_at': record.get('edited_at'),
        'source_filename': record.get('source_filename'),
        'counts': master_store.master_counts(master),
        # Purchase actuals are MONTH data frozen at import: surface how many
        # and from which anchor month, so nobody mistakes them for current.
        'actuals_materials': len(actuals),
        'anchor_month': str(cfg.get('initial_date') or '')[:7],
        'mirror': master_mirror.mirror_status(),
    }


def _workbook_diff(previous: dict, incoming: dict) -> dict:
    """Human-readable diff for the import confirmation dialog.

    Materials get name-level detail (they are the sensitive dataset:
    references, deactivation semantics); other datasets report counts.
    """
    prev_mats = {m['material_number']: m for m in previous.get('materials') or []}
    new_mats = {m['material_number']: m for m in incoming.get('materials') or []}
    added = sorted(set(new_mats) - set(prev_mats))
    removed = sorted(set(prev_mats) - set(new_mats))
    changed = sorted(
        mn for mn in set(prev_mats) & set(new_mats)
        if prev_mats[mn] != new_mats[mn])

    dataset_changes = {}
    for key in ('config', 'fte', 'machines', 'safety_stock', 'purchase',
                'sales_prices', 'material_costs', 'machine_costs',
                'valuation_params'):
        if (previous.get(key) or None) != (incoming.get(key) or None):
            dataset_changes[key] = True
    return {
        'materials_added': [{'material': mn, 'name': new_mats[mn].get('name', '')}
                            for mn in added],
        'materials_removed': [{'material': mn, 'name': prev_mats[mn].get('name', '')}
                              for mn in removed],
        'materials_changed': [{'material': mn, 'name': new_mats[mn].get('name', '')}
                              for mn in changed],
        'datasets_changed': sorted(dataset_changes),
    }


def _deactivate_missing_materials(previous: dict, incoming: dict) -> list:
    """Missing rows are never silently deleted: materials present in the
    store but absent from the imported workbook are appended DEACTIVATED
    (all other fields preserved). Returns the affected material numbers."""
    new_nums = {m['material_number'] for m in incoming.get('materials') or []}
    deactivated = []
    for material in previous.get('materials') or []:
        if material['material_number'] not in new_nums:
            kept = dict(material)
            kept['is_active'] = False
            incoming.setdefault('materials', []).append(kept)
            deactivated.append(material['material_number'])
    return deactivated


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
        master_mirror.refresh_mirror()
        payload = _status_payload(record)
        payload['success'] = True
        return jsonify(payload)

    @bp.route('/api/master_workbook/export', methods=['GET'])
    def export_master_workbook_route():
        """Download het per-site masterwerkboek en ververs meteen de spiegel
        op schijf — de download en de spiegel zijn hetzelfde bestand."""
        record = master_store.get_current_master_record()
        if record is None:
            return jsonify({'error': 'Geen masterdata in de app om te exporteren.'}), 400
        status = master_mirror.refresh_mirror()
        if status.get('stale'):
            return jsonify({'error': status.get('reason') or 'Spiegel kon niet worden geschreven.'}), 409
        from flask import send_file
        return send_file(status['path'], as_attachment=True,
                         download_name=Path(status['path']).name)

    @bp.route('/api/master_workbook/import', methods=['POST'])
    def import_master_workbook_route():
        """Importeer een (bewerkt) masterwerkboek: parse eigen formaat,
        sitecheck, versiecheck, diff + bevestiging, deactiveer-semantiek
        voor ontbrekende materialen, actuals van de huidige store behouden."""
        from modules.master_workbook import MasterWorkbookError, parse_master_workbook

        store_path = master_store.get_store_path()
        if store_path is None:
            return jsonify({'error': 'Masterdata-opslag is niet geconfigureerd.'}), 500
        if 'file' not in request.files or not request.files['file'].filename:
            return jsonify({'error': 'Geen bestand meegestuurd.'}), 400
        upload = request.files['file']
        safe_name = secure_filename(upload.filename)
        if not safe_name or not safe_name.lower().endswith('.xlsx'):
            return jsonify({'error': 'Verwacht een .xlsx-masterwerkboek (uit de export).'}), 400
        upload_dir = get_upload_dir()
        upload_dir.mkdir(parents=True, exist_ok=True)
        source_path = upload_dir / safe_name
        upload.save(str(source_path))

        try:
            incoming, meta = parse_master_workbook(source_path)
        except MasterWorkbookError as exc:
            return jsonify({'error': str(exc)}), 400

        previous_record = master_store.get_current_master_record()
        previous = (previous_record or {}).get('master') or {}

        # Sitevalidatie: een WSK-werkboek hoort in de ANK-app te botsen.
        current_site = str((previous.get('config') or {}).get('site')
                           or global_config.get('site') or '').strip()
        workbook_site = str(meta.get('site') or '').strip()
        if current_site and workbook_site and workbook_site != current_site:
            return jsonify({'error': f'Dit werkboek is van site {workbook_site}, '
                                     f'maar deze installatie draait {current_site}. '
                                     'Import geweigerd.'}), 400

        # Actuals zijn maanddata en staan niet in het werkboek: behouden.
        incoming['purchase']['actuals'] = dict(
            (previous.get('purchase') or {}).get('actuals') or {})

        # Excel-precisieverlies ('' vs None, 15-cijferige floats) terugzetten
        # naar de exacte store-waarde: een ongewijzigde round-trip geeft een
        # lege diff en muteert de store niet.
        from modules.master_workbook import absorb_equivalents
        absorb_equivalents(previous, incoming)

        deactivated = _deactivate_missing_materials(previous, incoming)

        try:
            _validate_master(incoming)
        except Exception as exc:
            return jsonify({'error': f'Werkboek geweigerd bij validatie: {exc}'}), 400

        confirm = str(request.form.get('confirm')
                      or (request.get_json(silent=True) or {}).get('confirm')
                      or '').lower() in ('true', '1', 'yes')
        stale_export = None
        if previous_record is not None:
            try:
                exported_version = int(float(meta.get('store_version') or 0))
            except (TypeError, ValueError):
                exported_version = 0
            if exported_version != int(previous_record.get('version') or 0):
                stale_export = {
                    'exported_from_version': exported_version,
                    'store_version': previous_record.get('version'),
                }
        if previous_record is not None and not confirm:
            return jsonify({
                'needs_confirm': True,
                'diff': _workbook_diff(previous, incoming),
                'deactivated': deactivated,
                'stale_export': stale_export,
                'message': 'Controleer de wijzigingen en bevestig om door te voeren.',
            })

        record = master_store.save_master_store(
            store_path, incoming, source_filename=upload.filename,
            previous=previous_record)
        master_mirror.refresh_mirror()
        payload = _status_payload(record)
        payload.update({'success': True, 'requires_recalculate': True,
                        'deactivated': deactivated})
        return jsonify(payload)

    @bp.route('/api/master_data/materials/add', methods=['POST'])
    def add_material_to_master():
        """Voeg een minimaal materiaal toe aan de store (of heractiveer een
        gedeactiveerd exemplaar). Actieknop bij de consistentiecheck: een
        materiaal dat wél in de extracts staat maar niet (actief) in de
        masterdata — de juni-2026-fout-klasse — is zo direct dichtbaar."""
        record = master_store.get_current_master_record()
        if record is None:
            return jsonify({'error': 'Geen masterdata in de app. Importeer eerst masterdata.'}), 400
        body = request.get_json(force=True, silent=True) or {}
        number = str(body.get('material') or '').strip()
        if not number:
            return jsonify({'error': 'Materiaalnummer ontbreekt.'}), 400

        candidate = dict(record.get('master') or {})
        materials = [dict(m) for m in candidate.get('materials') or []]
        existing = next((m for m in materials if m.get('material_number') == number), None)
        if existing is not None:
            if existing.get('is_active'):
                return jsonify({'error': f'{number} staat al actief in de masterdata.'}), 400
            existing['is_active'] = True
            action = 'reactivated'
        else:
            materials.append({
                'material_number': number,
                'name': str(body.get('name') or '').strip(),
                'product_type': str(body.get('product_type') or 'Other'),
                'product_family': str(body.get('product_family') or ''),
                'is_active': True,
            })
            action = 'added'
        candidate['materials'] = materials
        try:
            _validate_master(candidate)
        except Exception as exc:
            return jsonify({'error': f'Wijziging geweigerd: {exc}'}), 400
        new_record = master_store.save_master_store(
            master_store.get_store_path(), candidate, previous=record, edited=True)
        master_mirror.refresh_mirror()
        payload = _status_payload(new_record)
        payload.update({'success': True, 'action': action, 'material': number,
                        'requires_recalculate': True})
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
        # De spiegel op schijf blijft de actuele stand ("kijk naar de
        # master-Excel"), ook na grid-edits in de app.
        master_mirror.refresh_mirror()
        payload = _status_payload(new_record)
        payload.update({'success': True, 'requires_recalculate': True})
        return jsonify(payload)

    return bp
