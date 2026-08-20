"""Capacity & FTE workbench routes (F2-CF).

Read side (`GET /api/fte`) serves the workbench result the engine already
computed as part of the normal cascade — no recalculation on a page view.

Write side is deliberately narrow: the only thing this blueprint mutates is
which machine COMBINATIONS are active. Everything else the workbench shows is
either master data (edited through /api/master_data) or a planning cell
(edited through the existing edit cascade), so there is exactly one owner per
number.

The comparison endpoint runs the FTE engine repeatedly over the SAME planning
results with different combination sets. That is what makes the variants
comparable: only the staffing assumption differs.
"""

from typing import Callable

from flask import Blueprint, jsonify, request

from modules.fte_engine import FteEngine
from ui import master_store

_NO_ENGINE = 'Nog geen berekening uitgevoerd.'

_SITE_MISMATCH = ('De FTE-werkbank is uitgeschakeld voor deze sessie: het werkboek '
                  'is van site {workbook_site}, maar de masterdata van deze '
                  'installatie is van site {store_site}. Bemensingsnormen en '
                  'machines van {store_site} op een {workbook_site}-planning '
                  'loslaten zou stil verkeerde cijfers geven.')


def _site_mismatch(engine):
    """Werkbank alleen op de site van de eigen masterdata.

    Twee controles, allebei nodig. De overlay-vlag dekt sessies die met de
    sitepoort zijn herbouwd; de live vergelijking dekt sessies die uit een
    OUDER snapshot zijn hersteld — die zijn vóór de poort gebouwd, dragen de
    vlag niet, maar hun config.site komt van het werkboek en verraadt de
    menging alsnog. Zonder store (of zonder site) is er geen site-identiteit
    om tegen te toetsen en blijft de werkbank gewoon beschikbaar.
    """
    data = getattr(engine, 'data', None)
    if data is None:
        return None
    skipped = getattr(data, 'master_overlay_skipped', None)
    if skipped:
        return skipped
    record = master_store.get_current_master_record()
    if record is None:
        return None
    store_site = str((((record.get('master') or {}).get('config') or {}).get('site')) or '').strip()
    session_site = str(getattr(getattr(data, 'config', None), 'site', '') or '').strip()
    if store_site and session_site and store_site != session_site:
        return {'store_site': store_site, 'workbook_site': session_site}
    return None


def _master_version(engine):
    """Storeversie waaruit de GETOONDE normen komen — niet de huidige.

    De werkbank bewerkt bemensingsnormen via de gewone masterdata-PATCH, die
    een schrijfactie op een oudere versie met 409 weigert. Meldden we hier de
    huidige storeversie, dan zou juist het gevaarlijke geval erdoor glippen:
    een draaiende engine toont nog de oude norm ("edits apply at the NEXT
    calculation"), de gebruiker corrigeert wat hij ziet, en de tussentijdse
    wijziging van een collega verdwijnt zonder conflict.

    De engine draagt de versie waaruit hij gebouwd is; alleen als die er niet
    is (werkboeksessie zonder store) valt hij terug op None, en dan stuurt de
    frontend geen base_version mee.
    """
    version = getattr(getattr(engine, 'data', None), 'fte_master_version', None)
    if version is not None:
        return version
    source = getattr(engine, '_resolved_master_source', None)
    return getattr(source, 'version', None)


def _combination_catalog(engine) -> list:
    """Catalogus voor de UI, geïdentificeerd op de DICT-SLEUTEL.

    De motor zoekt combinaties op met hun sleutel (FteEngine.__init__ filtert
    `combos.items()`), dus de checkbox moet diezelfde sleutel terugsturen. Het
    veld combination_id gebruiken ging mis zodra sleutel en veld uiteenliepen:
    twee rijen kregen hetzelfde vinkje en de motor activeerde de verkeerde
    combinatie — met een 200 en zonder waarschuwing. Hydratie dwingt inmiddels
    af dat ze gelijk zijn; hier houden we het sluitend voor het geval dat een
    oudere store nog iets anders bevat.
    """
    combos = getattr(getattr(engine, 'data', None), 'machine_combinations', None) or {}
    return [{
        'combination_id': key,
        'name': combo.name or key,
        'machine_codes': list(combo.machine_codes),
        'operators': combo.operators,
        'throughput_factor': combo.throughput_factor,
        'throughput_factor_by_machine': dict(combo.throughput_factor_by_machine),
        'function_group': combo.function_group,
        'is_active': combo.is_active,
    } for key, combo in sorted(combos.items())]


def _summary(result) -> dict:
    """The KPI line of one variant: FTE, occupancy, cost, margin, t/FTE."""
    periods = result.periods
    impact = result.value_impact

    def _avg(values):
        return sum(values.get(p, 0.0) for p in periods) / len(periods) if periods else 0.0

    def _sum(values):
        return sum(values.get(p, 0.0) for p in periods)

    return {
        'fte_avg': _avg(result.total_fte),
        'direct_fte_avg': _avg(result.total_direct_fte),
        'indirect_fte_avg': _avg(result.total_indirect_fte),
        'staffed_fte_avg': (sum(result.staffed_fte(p) for p in periods) / len(periods)
                            if periods else 0.0),
        'hours_total': _sum(result.total_hours),
        'available_hours_total': _sum(result.total_available_hours),
        # Bezetting alleen over regels MET een venster (zie
        # FteResult.total_capacity_hours): anders duwen indirecte activiteiten
        # en de controlekamer het percentage boven de 100.
        'capacity_hours_total': _sum(result.total_capacity_hours),
        'utilization': (_sum(result.total_capacity_hours) / _sum(result.total_available_hours)
                        if _sum(result.total_available_hours) > 0 else 0.0),
        'labor_cost_total': _sum(result.total_cost),
        'volume_total': _sum(result.total_volume),
        'tons_per_fte': (_sum(result.total_volume) / _avg(result.total_fte)
                         if _avg(result.total_fte) > 0 else 0.0),
        'gross_margin_total': _sum(impact.gross_margin) if impact.available else None,
        'ebitda_total': _sum(impact.ebitda) if impact.available else None,
        'value_impact_available': impact.available,
    }


def create_fte_blueprint(
    get_active: Callable[[], tuple],
    save_sessions_to_disk: Callable[[], None],
) -> Blueprint:
    bp = Blueprint('fte', __name__)

    def _result(engine):
        """The current workbench result, computed on demand if never built."""
        result = getattr(engine, 'fte_results', None)
        if result is None and hasattr(engine, 'recalculate_fte'):
            engine.recalculate_fte()
            result = engine.fte_results
        return result

    @bp.route('/api/fte', methods=['GET'])
    def get_fte():
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': _NO_ENGINE}), 400
        mismatch = _site_mismatch(engine)
        if mismatch:
            return jsonify({'error': _SITE_MISMATCH.format(**mismatch), **mismatch}), 409
        result = _result(engine)
        if result is None:
            return jsonify({'error': 'De FTE-werkbank is niet beschikbaar voor deze sessie.'}), 400
        return jsonify({
            'success': True,
            'fte': result.to_dict(),
            'combinations': _combination_catalog(engine),
            'active_combinations': list((sess or {}).get('active_combinations') or []),
            'norm_overrides': dict((sess or {}).get('fte_norm_overrides') or {}),
            'master_version': _master_version(engine),
        })

    @bp.route('/api/fte/norm_overrides', methods=['POST'])
    def set_norm_overrides():
        """Wat-als op de bemensingsnormen: rekent DIRECT mee, raakt de
        masterdata niet.

        Sessiestate naast active_combinations: dezelfde zes sync-/rebuild-
        punten, dezelfde reset- en scenario-semantiek. De werkbank stuurt de
        VOLLEDIGE set overrides (leeg = alles terugzetten); de regels dragen
        bron 'wat-als' zodat een experiment nooit voor een vastgelegde norm
        kan doorgaan. Vastleggen gebeurt daarna expliciet via de masterdata-
        PATCH (opslaan) of via een scenario.
        """
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': _NO_ENGINE}), 400
        mismatch = _site_mismatch(engine)
        if mismatch:
            return jsonify({'error': _SITE_MISMATCH.format(**mismatch), **mismatch}), 409
        body = request.get_json(silent=True) or {}
        raw = body.get('overrides')
        if not isinstance(raw, dict):
            return jsonify({'error': 'Verwacht een object "overrides".'}), 400
        overrides = {}
        for code, spec in raw.items():
            if not isinstance(spec, dict):
                return jsonify({'error': f'Override "{code}" is geen object.'}), 400
            try:
                operators = float(spec.get('operators_per_hour'))
            except (TypeError, ValueError):
                return jsonify({'error': f'Override "{code}": operators per uur moet een getal zijn.'}), 400
            if operators < 0:
                return jsonify({'error': f'Override "{code}": operators per uur kan niet negatief zijn.'}), 400
            scope = str(spec.get('scope') or 'group')
            if scope not in ('group', 'machine'):
                return jsonify({'error': f'Override "{code}": onbekend bereik "{scope}".'}), 400
            entry = {'operators_per_hour': operators, 'scope': scope}
            # 'was' is weergave-metadata (oud -> nieuw in het paneel, en het
            # terugzetten-door-oude-waarde-typen na een paginaherlaad). De
            # motor negeert het; ongeldig = gewoon weglaten, geen 400.
            try:
                if spec.get('was') is not None:
                    entry['was'] = float(spec.get('was'))
            except (TypeError, ValueError):
                pass
            overrides[str(code)] = entry

        engine.recalculate_fte(norm_overrides=overrides)
        sess['fte_norm_overrides'] = dict(overrides)
        save_sessions_to_disk()
        return jsonify({
            'success': True,
            'fte': engine.fte_results.to_dict(),
            'norm_overrides': dict(overrides),
            'active_combinations': list((sess or {}).get('active_combinations') or []),
            'warnings': engine.fte_results.warnings,
            'master_version': _master_version(engine),
        })

    @bp.route('/api/fte/combinations', methods=['POST'])
    def set_combinations():
        """Turn machine combinations on/off for this session and recalculate.

        Session state, not master data: which combinations are ON is a
        what-if, the combinations themselves are master data.
        """
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': _NO_ENGINE}), 400
        mismatch = _site_mismatch(engine)
        if mismatch:
            return jsonify({'error': _SITE_MISMATCH.format(**mismatch), **mismatch}), 409
        body = request.get_json(silent=True) or {}
        requested = body.get('active_combinations')
        if not isinstance(requested, list):
            return jsonify({'error': 'Verwacht een lijst "active_combinations".'}), 400
        known = {c['combination_id'] for c in _combination_catalog(engine)}
        unknown = [str(c) for c in requested if str(c) not in known]
        if unknown:
            return jsonify({'error': 'Onbekende combinatie(s): ' + ', '.join(unknown)}), 400

        engine.recalculate_fte([str(c) for c in requested])
        # De motor kan een combinatie weigeren (twee combinaties die dezelfde
        # machine claimen). Antwoorden met de GEVRAAGDE lijst liet het vinkje
        # aan staan voor iets wat niet meerekent, en zette dat ook zo in de
        # sessie — dan zeggen vinkje, sessie en motor drie verschillende
        # dingen. Neem daarom over wat de motor daadwerkelijk heeft toegepast.
        applied = list(engine.fte_results.active_combinations)
        sess['active_combinations'] = applied
        save_sessions_to_disk()
        return jsonify({
            'success': True,
            'fte': engine.fte_results.to_dict(),
            'active_combinations': applied,
            'warnings': engine.fte_results.warnings,
            'master_version': _master_version(engine),
        })

    @bp.route('/api/fte/refresh', methods=['POST'])
    def refresh_master():
        """Re-read the F2-CF master datasets into the live engine.

        The workbench edits its norms through the normal master-data PATCH
        (one owner per number), but a running engine holds the datasets it was
        built with. Without this the workbench would keep showing yesterday's
        staffing until the next full recalculation. This is a read-through of
        the store, not new session state: a rebuild re-hydrates from the same
        source, so nothing can drift.
        """
        from modules.master_data import hydrate_fte_datasets

        sess, engine = get_active()
        if engine is None or getattr(engine, 'data', None) is None:
            return jsonify({'error': _NO_ENGINE}), 400
        mismatch = _site_mismatch(engine)
        if mismatch:
            return jsonify({'error': _SITE_MISMATCH.format(**mismatch), **mismatch}), 409
        record = master_store.get_current_master_record()
        if record is None:
            return jsonify({'error': 'Geen masterdata in de app.'}), 400
        hydrate_fte_datasets(engine.data, record.get('master') or {},
                             store_version=record.get('version'))
        engine.recalculate_fte()
        return jsonify({
            'success': True,
            'fte': engine.fte_results.to_dict(),
            'combinations': _combination_catalog(engine),
            'active_combinations': list((sess or {}).get('active_combinations') or []),
            'master_version': record.get('version'),
        })

    @bp.route('/api/fte/compare', methods=['POST'])
    def compare():
        """Run several combination sets over the same planning results.

        Body: {"variants": [{"label": "...", "active_combinations": [...]}, ...]}
        The session's own set is prepended as the baseline when absent, so the
        comparison always has something to be measured against.
        """
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': _NO_ENGINE}), 400
        mismatch = _site_mismatch(engine)
        if mismatch:
            return jsonify({'error': _SITE_MISMATCH.format(**mismatch), **mismatch}), 409
        body = request.get_json(silent=True) or {}
        variants = body.get('variants')
        if not isinstance(variants, list) or not variants:
            return jsonify({'error': 'Verwacht een niet-lege lijst "variants".'}), 400
        known = {c['combination_id'] for c in _combination_catalog(engine)}

        current = sorted((sess or {}).get('active_combinations') or [])
        prepared = []
        for index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                return jsonify({'error': f'Variant {index + 1} is geen object.'}), 400
            combos = variant.get('active_combinations') or []
            if not isinstance(combos, list):
                return jsonify({'error': f'Variant {index + 1}: "active_combinations" moet een lijst zijn.'}), 400
            unknown = [str(c) for c in combos if str(c) not in known]
            if unknown:
                return jsonify({'error': f'Variant {index + 1}: onbekende combinatie(s) '
                                         + ', '.join(unknown)}), 400
            prepared.append({
                'label': str(variant.get('label') or f'Variant {index + 1}'),
                'active_combinations': [str(c) for c in combos],
            })
        if not any(sorted(v['active_combinations']) == current for v in prepared):
            prepared.insert(0, {'label': 'Huidige instelling',
                                'active_combinations': list(current)})

        rows = []
        for variant in prepared:
            # De wat-als-normen van de sessie gelden voor ALLE varianten:
            # alleen de combinatieset verschilt, anders vergelijkt de tabel
            # appels met peren.
            result = FteEngine(engine.data, engine.results,
                               active_combinations=variant['active_combinations'],
                               value_results=engine.value_results,
                               staffing_norm_overrides=getattr(engine, 'fte_norm_overrides', None)).calculate()
            rows.append({
                'label': variant['label'],
                'active_combinations': variant['active_combinations'],
                'summary': _summary(result),
                'warnings': result.warnings,
            })
        baseline = rows[0]['summary']
        for row in rows[1:]:
            row['delta'] = {
                key: (row['summary'][key] - baseline[key])
                for key, value in baseline.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                and isinstance(row['summary'].get(key), (int, float))
            }
        return jsonify({'success': True, 'variants': rows,
                        'periods': engine.fte_results.periods
                        if getattr(engine, 'fte_results', None) else []})

    return bp
