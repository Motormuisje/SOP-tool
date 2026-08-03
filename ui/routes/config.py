"""Configuration-related Flask routes."""

import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
from typing import Callable

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from modules.data_loader import DataLoader


_MISSING = object()  # sentinel: sleutel bestond niet vóór deze request


def _sanitize_forecast_defaults(raw) -> dict:
    """Coerce a forecast-defaults payload to a safe, JSON-serialisable dict.

    Shape: {'mode': 'fill_empty'|'add', 'default': float|None,
            'per_material': {material_number: float}}.
    Invalid entries are dropped rather than raising a 500.
    """
    if not isinstance(raw, dict):
        return {}
    mode = raw.get('mode', 'fill_empty')
    if mode not in ('fill_empty', 'add'):
        mode = 'fill_empty'
    out = {'mode': mode}
    default = raw.get('default')
    if default not in (None, ''):
        try:
            out['default'] = float(default)
        except (TypeError, ValueError):
            pass
    per_material = {}
    for mat, val in (raw.get('per_material') or {}).items():
        try:
            per_material[str(mat)] = float(val)
        except (TypeError, ValueError):
            continue
    if per_material:
        out['per_material'] = per_material
    # A mode without any value is a no-op config; normalise to {} so an
    # "empty" save compares equal to the stored default and does not flag a
    # spurious structural change (which would force a full engine rebuild
    # and drop VP/PAP submitted in the same request).
    if 'default' not in out and not per_material:
        return {}
    return out


def create_config_blueprint(
    default_folders: Callable[[], dict],
    global_config: dict,
    save_global_config: Callable[[], None],
    apply_folder_paths: Callable[[Path, Path, Path], None],
    get_upload_dir: Callable[[], Path],
    get_active: Callable[[], tuple],
    parse_purchased_and_produced: Callable[[object], dict],
    valuation_params_from_config: Callable[[object], object],
    ensure_reset_baseline: Callable[[dict, object], None],
    recalc_pap_material: Callable[[object, str], None],
    finish_pap_recalc: Callable[[object], None],
    recalculate_value_results: Callable[[object, dict], None],
    build_clean_engine_for_session: Callable[[dict], object],
    install_clean_engine_baseline: Callable[..., None],
    replay_pending_edits: Callable[[dict, object], None],
    moq_warnings_payload: Callable[[object], dict],
    value_results_payload: Callable[[object], dict],
    all_sessions: dict = None,
) -> Blueprint:
    bp = Blueprint('config', __name__)

    @bp.route('/api/config/folders', methods=['GET'])
    def get_folder_config():
        defs = default_folders()
        saved = global_config.get('folders', {})
        return jsonify({
            'uploads': saved.get('uploads') or defs['uploads'],
            'exports': saved.get('exports') or defs['exports'],
            'sessions': saved.get('sessions') or defs['sessions'],
            'defaults': defs,
        })

    @bp.route('/api/config/folders', methods=['POST'])
    def save_folder_config():
        data = request.get_json(force=True) or {}
        defs = default_folders()

        uploads = (data.get('uploads') or '').strip() or defs['uploads']
        exports = (data.get('exports') or '').strip() or defs['exports']
        sessions_dir = (data.get('sessions') or '').strip() or defs['sessions']

        errors = []
        for label, path in [('uploads', uploads), ('exports', exports), ('sessions', sessions_dir)]:
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                errors.append(f'{label}: {exc}')
        if errors:
            return jsonify({'success': False, 'errors': errors}), 400

        global_config.setdefault('folders', {})
        global_config['folders']['uploads'] = uploads
        global_config['folders']['exports'] = exports
        global_config['folders']['sessions'] = sessions_dir
        save_global_config()

        apply_folder_paths(Path(uploads), Path(exports), Path(sessions_dir))
        return jsonify({'success': True})

    @bp.route('/api/config', methods=['GET'])
    def get_global_config():
        fd = global_config.get('file_defaults', {})
        # App master store presence: the store outranks the legacy
        # master_file everywhere (upload/calculate/rebuild), so the UI must
        # be able to reflect the source that will actually be used.
        from ui.master_store import get_current_master_record
        from ui.settings_registry import settings_meta
        store_record = get_current_master_record()
        return jsonify({
            'settings_meta': settings_meta(global_config),
            'master_filename': global_config.get('master_filename'),
            'master_uploaded_at': global_config.get('master_uploaded_at'),
            'master_file_exists': bool(
                global_config.get('master_file') and
                Path(global_config['master_file']).exists()
            ),
            'master_store_exists': store_record is not None,
            'master_store_version': (store_record or {}).get('version'),
            'site': global_config.get('site', ''),
            'forecast_months': global_config.get('forecast_months', ''),
            'unlimited_machines': global_config.get('unlimited_machines', ''),
            'purchased_and_produced': global_config.get('purchased_and_produced', ''),
            'valuation_params': global_config.get('valuation_params', {}),
            'forecast_defaults': global_config.get('forecast_defaults', {}),
            'file_defaults': {
                'site': fd.get('site', ''),
                'forecast_months': fd.get('forecast_months', 12),
                'unlimited_machines': fd.get('unlimited_machines', ''),
                'purchased_and_produced': fd.get('purchased_and_produced', ''),
                'valuation_params': fd.get('valuation_params', {}),
            },
        })

    @bp.route('/api/config/master-file', methods=['POST'])
    def upload_master_file():
        upload_dir = get_upload_dir()
        upload_dir.mkdir(exist_ok=True)

        if 'master_file' not in request.files or request.files['master_file'].filename == '':
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['master_file']
        if not file.filename.lower().endswith(('.xlsm', '.xlsx')):
            return jsonify({'error': 'Only .xlsm or .xlsx files are accepted'}), 400

        safe_name = secure_filename(file.filename)
        if not safe_name:
            return jsonify({'error': f'Invalid filename: "{file.filename}"'}), 400
        dest = upload_dir / safe_name
        file.save(str(dest))

        try:
            with contextlib.redirect_stdout(io.StringIO()):
                loader = DataLoader(excel_file=str(dest))
                loader.load_all()
        except Exception:
            return jsonify({'error': 'Could not read file. Check that it contains the required sheets.'}), 400

        global_config['master_file'] = str(dest)
        global_config['master_filename'] = file.filename
        global_config['master_uploaded_at'] = datetime.now().isoformat()

        site = getattr(loader.config, 'site', '') if loader.config else ''
        forecast_months = getattr(loader.config, 'forecast_months', 12) if loader.config else 12
        unlimited = ','.join(getattr(loader.config, 'unlimited_capacity_machine', []))
        purchased_and_produced = loader.purchased_and_produced or {}
        purchased_and_produced_str = ', '.join(f'{k}:{v}' for k, v in purchased_and_produced.items())
        vp = loader.valuation_params
        vp_dict = {}
        if vp:
            vp_dict = {
                '1': vp.direct_fte_cost_per_month,
                '2': vp.indirect_fte_cost_per_month,
                '3': vp.overhead_cost_per_month,
                '4': vp.sga_cost_per_month,
                '5': vp.depreciation_per_year,
                '6': vp.net_book_value,
                '7': vp.days_sales_outstanding,
                '8': vp.days_payable_outstanding,
            }
        global_config['file_defaults'] = {
            'site': site,
            'forecast_months': forecast_months,
            'unlimited_machines': unlimited,
            'purchased_and_produced': purchased_and_produced_str,
            'valuation_params': vp_dict,
        }
        save_global_config()

        return jsonify({
            'success': True,
            'master_filename': file.filename,
            'master_uploaded_at': global_config['master_uploaded_at'],
            'file_defaults': global_config['file_defaults'],
            'summary': {
                'materials': len(loader.materials),
                'machines': len(loader.machines),
            }
        })

    @bp.route('/api/config/settings', methods=['POST'])
    def save_config_settings():
        data = request.get_json() or {}
        sess, current_engine = get_active()
        value_recalculated = False
        planning_recalculated = False
        old_config = {
            'site': str(global_config.get('site', '') or ''),
            'forecast_months': int(global_config.get('forecast_months', 0) or 0),
            'unlimited_machines': str(global_config.get('unlimited_machines', '') or ''),
        }

        old_fc_defaults = json.dumps(global_config.get('forecast_defaults', {}), sort_keys=True)

        # ---- Valideer-dan-pas-toe -------------------------------------------
        # Eerst ALLE invoer parsen (nette 400 zonder enige mutatie); pas
        # daarna toepassen. Voorheen kon een geldige PAP-wijziging al
        # doorgerekend zijn voordat kapotte valuation-params een 400 gaven,
        # waarna de after-request-hook die halve staat ook nog persisteerde.
        from ui.settings_registry import apply_generic_settings, generic_settings
        try:
            parsed_scalars = {}
            if 'site' in data:
                parsed_scalars['site'] = str(data['site']).strip()
            if 'forecast_months' in data:
                parsed_scalars['forecast_months'] = int(float(data['forecast_months'] or 12))
            if 'unlimited_machines' in data:
                parsed_scalars['unlimited_machines'] = str(data['unlimited_machines']).strip()
        except (TypeError, ValueError, OverflowError) as exc:
            return jsonify({'error': f'Ongeldige configuratiewaarde: {exc}'}), 400
        pap_str = None
        if 'purchased_and_produced' in data:
            if not isinstance(data['purchased_and_produced'], str):
                return jsonify({'error': 'purchased_and_produced moet een tekstwaarde zijn.'}), 400
            pap_str = data['purchased_and_produced'].strip()
        vp_parsed = None
        if 'valuation_params' in data:
            try:
                vp_parsed = {
                    str(k): float(v) for k, v in data['valuation_params'].items()
                    if v is not None
                }
            except (TypeError, ValueError, AttributeError, OverflowError) as exc:
                return jsonify({'error': f'Ongeldige valuation-parameters: {exc}'}), 400

        # Prior-snapshot voor rollback bij een mislukte structurele rebuild:
        # zonder terugdraaien bleef de OUDE engine met NIEUWE parameters
        # achter (volgende gerichte herberekening prijst het oude plan stil
        # met afgekeurde parameters) en persisteerde de hook een mengstaat.
        _rollback_keys = (['site', 'forecast_months', 'unlimited_machines',
                           'forecast_defaults', 'purchased_and_produced',
                           'valuation_params']
                          + [g.key for g in generic_settings()])
        _prior_global = {k: global_config.get(k, _MISSING) for k in _rollback_keys}
        _prior_sess = {k: (sess.get(k, _MISSING) if sess is not None else _MISSING)
                       for k in ('forecast_defaults', 'purchased_and_produced',
                                 'valuation_params')}
        _engine_data = getattr(current_engine, 'data', None) if current_engine is not None else None
        _prior_engine_pap = dict(getattr(_engine_data, 'purchased_and_produced', {}) or {}) if _engine_data is not None else None
        _prior_engine_vp = getattr(_engine_data, 'valuation_params', None) if _engine_data is not None else None

        def _rollback():
            for key, value in _prior_global.items():
                if value is _MISSING:
                    global_config.pop(key, None)
                else:
                    global_config[key] = value
            if sess is not None:
                for key, value in _prior_sess.items():
                    if value is _MISSING:
                        sess.pop(key, None)
                    else:
                        sess[key] = value
            if _engine_data is not None:
                if _prior_engine_pap is not None:
                    _engine_data.purchased_and_produced = _prior_engine_pap
                _engine_data.valuation_params = _prior_engine_vp

        for key, value in parsed_scalars.items():
            global_config[key] = value
        if 'forecast_defaults' in data:
            global_config['forecast_defaults'] = _sanitize_forecast_defaults(data['forecast_defaults'])
            # Per-session state: the session dict is what rebuilds and
            # persistence read; global is only the UI/calculate mirror.
            if sess is not None:
                sess['forecast_defaults'] = dict(global_config['forecast_defaults'])

        # Registry-gedreven velden (handler='generic'): coercion, opslag en
        # effectbepaling komen uit ui/settings_registry.py — een nieuw veld
        # toevoegen raakt deze route niet meer.
        try:
            generic_effects = apply_generic_settings(data, global_config)
        except ValueError as exc:
            _rollback()
            return jsonify({'error': str(exc)}), 400

        structural_config_changed = (
            str(global_config.get('site', '') or '') != old_config['site']
            or int(global_config.get('forecast_months', 0) or 0) != old_config['forecast_months']
            or str(global_config.get('unlimited_machines', '') or '') != old_config['unlimited_machines']
            or json.dumps(global_config.get('forecast_defaults', {}), sort_keys=True) != old_fc_defaults
            or 'rebuild' in generic_effects
        )

        if pap_str is not None:
            global_config['purchased_and_produced'] = pap_str
            # Sessieveld is de bron van waarheid bij rebuild/warmup: zonder
            # deze write verdween een PAP-wijziging op een koude sessie stil
            # (de gepersisteerde oude waarde won van global).
            if sess is not None:
                sess['purchased_and_produced'] = global_config['purchased_and_produced']
            if current_engine is not None:
                old_pap = dict(getattr(current_engine.data, 'purchased_and_produced', {}) or {})
                new_pap = parse_purchased_and_produced(global_config['purchased_and_produced'])
                changed_mats = sorted({
                    mat for mat in set(old_pap) | set(new_pap)
                    if abs(float(old_pap.get(mat, -999999999)) - float(new_pap.get(mat, -999999999))) > 1e-9
                })
                # Ook bij een structurele wijziging op de OUDE engine zetten:
                # de gerichte (niet-structurele) herberekening leest de
                # engine-data direct; de rebuild zelf leest sessie-eerst
                # (het sessieveld hierboven is de bron van waarheid).
                current_engine.data.purchased_and_produced = new_pap
                if not structural_config_changed:
                    if changed_mats:
                        ensure_reset_baseline(sess, current_engine)
                        for mat in changed_mats:
                            recalc_pap_material(current_engine, mat)
                        finish_pap_recalc(current_engine)
                        planning_recalculated = True
                    else:
                        recalculate_value_results(current_engine, sess)
                    value_recalculated = True
        if vp_parsed is not None:
            global_config['valuation_params'] = vp_parsed
            if sess is not None:
                sess['valuation_params'] = dict(global_config['valuation_params'])
            if current_engine is not None and getattr(current_engine, 'data', None) is not None:
                # Idem: ook vóór een structurele rebuild op de oude engine
                # zetten, anders wint de oude engine-waarde in de
                # engine-first override-keten en raakt de nieuwe VP zoek.
                current_engine.data.valuation_params = valuation_params_from_config(
                    global_config['valuation_params']
                )
                if not structural_config_changed:
                    recalculate_value_results(current_engine, sess)
                    value_recalculated = True

        # Generieke velden met effect 'value' (registry): financiële
        # herberekening zonder structurele rebuild.
        if ('value' in generic_effects and current_engine is not None
                and not structural_config_changed and not value_recalculated):
            recalculate_value_results(current_engine, sess)
            value_recalculated = True

        if current_engine is not None and structural_config_changed:
            from ui.locks import engine_rebuild_lock
            with engine_rebuild_lock:
                try:
                    rebuilt = build_clean_engine_for_session(sess)
                except Exception as exc:
                    _rollback()
                    return jsonify({'error': f'Herbouw met de nieuwe configuratie mislukte; de wijzigingen zijn teruggedraaid. ({exc})'}), 400
                if rebuilt is None:
                    _rollback()
                    return jsonify({'error': 'Kon de actieve sessie niet herbouwen met de gewijzigde configuratie; de wijzigingen zijn teruggedraaid. Herbereken deze sessie eerst.'}), 400
                install_clean_engine_baseline(sess, rebuilt, clear_machine_overrides=False)
                with current_app.app_context():
                    replay_pending_edits(sess, rebuilt)
                sess['engine'] = rebuilt
            current_engine = rebuilt
            planning_recalculated = True
            value_recalculated = True

        save_global_config()
        payload = {'success': True}
        if current_engine is not None and planning_recalculated:
            payload['periods'] = list(getattr(current_engine.data, 'periods', []) or [])
            payload['results'] = {
                lt: [row.to_dict() for row in rows]
                for lt, rows in (getattr(current_engine, 'results', {}) or {}).items()
            }
            payload.update(moq_warnings_payload(current_engine))
        if current_engine is not None and value_recalculated:
            payload.update(value_results_payload(current_engine))
        return jsonify(payload)

    @bp.route('/api/config/reset_vp_params', methods=['POST'])
    def reset_vp_params_to_defaults():
        sess, current_engine = get_active()
        if sess is None:
            return jsonify({'error': 'No active session'}), 400
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        baseline_vp = (sess.get('reset_baseline') or {}).get('valuation_params')
        if not baseline_vp:
            return jsonify({'error': 'No baseline available - run calculations first'}), 400

        current_engine.data.valuation_params = valuation_params_from_config(baseline_vp)
        global_config['valuation_params'] = {str(k): float(v) for k, v in baseline_vp.items()}
        # Sessieveld mee-resetten: persistentie is sessieveld-eerst, dus een
        # achterblijvende pre-reset-edit zou na herstart stil terugkeren.
        sess['valuation_params'] = {str(k): float(v) for k, v in baseline_vp.items()}
        recalculate_value_results(current_engine, sess)
        save_global_config()

        payload = {'success': True, 'valuation_params': baseline_vp}
        payload.update(value_results_payload(current_engine))
        return jsonify(payload)

    @bp.route('/api/uom/suspects', methods=['GET'])
    def get_uom_suspects():
        from ui.serializers import uom_suspects_payload
        _sess, current_engine = get_active()
        return jsonify(uom_suspects_payload(current_engine))

    @bp.route('/api/uom/decisions', methods=['POST'])
    def save_uom_decisions():
        """Persist UoM decisions and rebuild the active session when the
        effective conversion factors changed.

        Decisions: [{'component', 'action': 'convert'|'dismiss'|'clear',
        'factor'?}]. Factors are installation-wide state (ui/uom_store.py);
        the rebuild is the same full structural rebuild as a site/config
        change, so baseline, replay and downstream values stay consistent.
        """
        from ui import uom_store
        data = request.get_json() or {}
        decisions = data.get('decisions') or []
        if not isinstance(decisions, list):
            return jsonify({'error': 'decisions must be a list'}), 400

        before = uom_store.get_confirmed_overrides()
        uom_store.record_decisions(decisions)
        after = uom_store.get_confirmed_overrides()
        factors_changed = before != after

        sess, current_engine = get_active()
        payload = {'success': True, 'rebuilt': False}
        # Installatiebrede factoren: ALLE andere warme sessies invalideren,
        # ook als de actieve sessie koud is (het beheer werkt engine-loos
        # vanuit de Config-tab) — anders rekenden warme sessies onbeperkt
        # door met de oude conversies.
        if factors_changed:
            # Onder de rebuild-lock: een lopende calculate/switch-build (die
            # de oude factoren al las) rondt eerst af en installeert; daarna
            # pas invalideren wij — anders vulde die build een zojuist
            # geleegde sessie weer met een engine op oude conversies.
            from ui.locks import engine_rebuild_lock
            with engine_rebuild_lock:
                for other in (all_sessions or {}).values():
                    if other is not sess and other.get('engine') is not None:
                        other['engine'] = None
        if factors_changed and current_engine is not None:
            from ui.locks import engine_rebuild_lock
            with engine_rebuild_lock:
                rebuilt = build_clean_engine_for_session(sess)
                if rebuilt is None:
                    return jsonify({'error': 'Kon de actieve sessie niet herbouwen met de nieuwe conversiefactoren. Voer eerst een berekening uit.'}), 400
                install_clean_engine_baseline(sess, rebuilt, clear_machine_overrides=False)
                with current_app.app_context():
                    replay_pending_edits(sess, rebuilt)
                sess['engine'] = rebuilt
            current_engine = rebuilt
            payload['rebuilt'] = True
            payload['periods'] = list(getattr(current_engine.data, 'periods', []) or [])
            payload['results'] = {
                lt: [row.to_dict() for row in rows]
                for lt, rows in (getattr(current_engine, 'results', {}) or {}).items()
            }
            payload.update(moq_warnings_payload(current_engine))
            payload.update(value_results_payload(current_engine))

        from ui.serializers import uom_suspects_payload
        payload['uom'] = uom_suspects_payload(current_engine)
        return jsonify(payload)

    return bp
