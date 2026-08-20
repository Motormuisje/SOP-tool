"""Machine-inzet: omstellingen per machine per periode (fase 1).

De planning is de bron — dit tabblad bezit geen productiegetallen. Het leest
de Line 07-materiaalregels (die dragen hun machine in ``aux_column``) en
beantwoordt per machine per periode: hoeveel producten draaien er, hoeveel
omstellingen kost dat naar schatting, en hoeveel uren gaan daaraan op.

De schatting is eerlijk over wat ze weet: zonder volgorde-informatie is het
aantal omstellingen (aantal producten met uren) − 1, ondergrens 0. De echte
telling vergt de productievolgorde — dat is fase 3 (volgorde-wat-als).

Fase 1 rekent bewust nergens in door: de omsteluren verlagen het
beschikbaarheidsvenster pas in fase 2 (rekenkern, met additiviteitsbewijs).
De sessie-overrides op het aantal omstellingen zijn daarom WEERGAVE-wat-als:
ze persisteren (sessiestore, scenario's, duplicaat; Reset zet ze uit) maar
reizen niet door config_overrides/snapshot/replay — er is geen motor die ze
consumeert. Zodra fase 2 ze laat meerekenen, verhuizen ze naar de volledige
zes-syncpuntenmal, net als fte_norm_overrides.
"""

from typing import Callable

from flask import Blueprint, jsonify, request

from modules.models import LineType
from ui.routes.fte import _SITE_MISMATCH, _site_mismatch

_NO_ENGINE = 'Nog geen berekening uitgevoerd.'

# Uren onder deze drempel tellen niet als 'product draait op deze machine':
# afrondingsruis uit de cascade mag geen omstelling suggereren.
_MIN_HOURS = 0.01


def _machine_usage(engine) -> dict:
    """Per machine per periode: producten, uren en venster, uit de resultaten."""
    periods = list(getattr(engine.data, 'periods', []) or [])
    machines = getattr(engine.data, 'machines', None) or {}

    # Line 07-materiaalregels per machine (aux_column = machinecode).
    products = {}   # machine -> period -> set(material)
    hours = {}      # machine -> period -> uren
    for row in (engine.results or {}).get(LineType.CAPACITY_UTILIZATION.value, []):
        if getattr(row, 'product_type', None) in ('Machine', 'Machine Group'):
            continue
        machine_code = str(getattr(row, 'aux_column', '') or '')
        if not machine_code:
            continue
        for period in periods:
            value = float((row.values or {}).get(period, 0.0) or 0.0)
            if value <= _MIN_HOURS:
                continue
            products.setdefault(machine_code, {}).setdefault(period, set()).add(
                str(row.material_number))
            hours.setdefault(machine_code, {})[period] = \
                hours.get(machine_code, {}).get(period, 0.0) + value

    # Beschikbaarheidsvenster: Line 11 per groep; machines erven hun groep.
    window_by_group = {}
    for row in (engine.results or {}).get(LineType.SHIFT_AVAILABILITY.value, []):
        window_by_group[str(row.material_number)] = dict(row.values or {})

    out = {}
    for code in sorted(set(products) | set(machines)):
        machine = machines.get(code)
        group = str(getattr(machine, 'machine_group', '') or '')
        window = window_by_group.get(group, {})
        out[code] = {
            'name': str(getattr(machine, 'name', '') or ''),
            'machine_group': group,
            'per_period': {
                p: {
                    'products': sorted(products.get(code, {}).get(p, set())),
                    'hours': round(hours.get(code, {}).get(p, 0.0), 2),
                    'window': round(float(window.get(p, 0.0) or 0.0), 2),
                } for p in periods
            },
        }
    return {'periods': periods, 'machines': out}


def create_machine_inzet_blueprint(
    get_active: Callable[[], tuple],
    save_sessions_to_disk: Callable[[], None],
) -> Blueprint:
    bp = Blueprint('machine_inzet', __name__)

    @bp.route('/api/machine_inzet', methods=['GET'])
    def get_machine_inzet():
        sess, engine = get_active()
        if engine is None or getattr(engine, 'data', None) is None:
            return jsonify({'error': _NO_ENGINE}), 400
        mismatch = _site_mismatch(engine)
        if mismatch:
            return jsonify({'error': _SITE_MISMATCH.format(**mismatch), **mismatch}), 409
        usage = _machine_usage(engine)
        # Omsteltijden LIVE uit de store: de motor consumeert ze in fase 1
        # niet, dus de store is de eerlijke bron — engine.data zou een zojuist
        # opgeslagen omsteltijd pas na een herberekening tonen. Storeless
        # sessies vallen terug op wat de engine (via hydratie) meekreeg.
        from ui import master_store
        record = master_store.get_current_master_record()
        if record is not None:
            raw = (record.get('master') or {}).get('changeover_times') or {}
            changeovers = {
                str(code): {
                    'hours_per_changeover': float(item.get('hours_per_changeover') or 0.0),
                    'description': str(item.get('description') or ''),
                } for code, item in raw.items()
            }
        else:
            changeovers = {
                str(code): {
                    'hours_per_changeover': float(item.hours_per_changeover or 0.0),
                    'description': str(item.description or ''),
                }
                for code, item in (getattr(engine.data, 'changeover_times', None) or {}).items()
            }
        return jsonify({
            'success': True,
            **usage,
            'changeover_times': changeovers,
            'overrides': dict((sess or {}).get('changeover_overrides') or {}),
        })

    @bp.route('/api/machine_inzet/overrides', methods=['POST'])
    def set_overrides():
        """Weergave-wat-als op het AANTAL omstellingen per machine|periode.

        Volledige set per POST (leeg = alles terug naar de schatting), zelfde
        contract als de norm-overrides. Persisteert in de sessie; geen
        herberekening — fase 1 rekent nergens mee.
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
        for key, count in raw.items():
            if '|' not in str(key):
                return jsonify({'error': f'Override "{key}": sleutel moet MACHINE|PERIODE zijn.'}), 400
            try:
                parsed = float(count)
            except (TypeError, ValueError):
                return jsonify({'error': f'Override "{key}": aantal moet een getal zijn.'}), 400
            if parsed < 0 or parsed != int(parsed):
                return jsonify({'error': f'Override "{key}": aantal omstellingen is een geheel getal ≥ 0.'}), 400
            overrides[str(key)] = int(parsed)
        sess['changeover_overrides'] = dict(overrides)
        save_sessions_to_disk()
        return jsonify({'success': True, 'overrides': dict(overrides)})

    return bp
