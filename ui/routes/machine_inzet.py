"""Machine-inzet: omstellingen per machine per periode (fase 1 + 1b).

De planning is de bron — dit tabblad bezit geen productiegetallen. Het leest
de Line 07-materiaalregels (die dragen hun machine in ``aux_column``) en
beantwoordt per machine per periode: welke producten draaien er, in welke
volgorde, hoeveel omstellingen kost dat naar schatting, hoeveel uren gaan
daaraan op en wat kosten die uren.

De schatting is eerlijk over wat ze weet: het aantal omstellingen is (aantal
producten met uren) − 1, ondergrens 0. De VOLGORDE is een planningskeuze
per machine (sessie-wat-als): zonder keuze staan de producten op draaiuren
over de horizon (grootste run eerst). Volgorde-afhankelijke omsteltijden
(VAN|NAAR) zijn fase 3 — de volgorde verandert het aantal nu nog niet.

Kosten (fase 1b): omsteluren × tarief. Het tarief komt uit de omsteltijd-
masterdata (``cost_per_hour``) en valt terug op het machinetarief uit
``machine_costs`` — dezelfde bron als de waardeplanning — zodat elke machine
met een omsteltijd direct een kostprijs laat zien, met de herkomst erbij.

Fase 1 rekent bewust nergens in door: de omsteluren verlagen het
beschikbaarheidsvenster pas in fase 2 (rekenkern, met additiviteitsbewijs).
De sessie-overrides (aantal, volgorde) zijn daarom WEERGAVE-wat-als: ze
persisteren (sessiestore, scenario's, duplicaat; Reset zet ze uit) maar
reizen niet door config_overrides/snapshot/replay — er is geen motor die ze
consumeert. Zodra fase 2 ze laat meerekenen, verhuizen ze naar de volledige
zes-syncpuntenmal, net als fte_norm_overrides.
"""

from typing import Callable, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from modules.models import LineType
from ui.routes.fte import _SITE_MISMATCH, _site_mismatch

_NO_ENGINE = 'Nog geen berekening uitgevoerd.'

# Uren onder deze drempel tellen niet als 'product draait op deze machine':
# afrondingsruis uit de cascade mag geen omstelling suggereren.
_MIN_HOURS = 0.01


def _machine_usage(engine) -> dict:
    """Per machine per periode: producten, uren en venster, uit de resultaten.

    ``per_period[p].products`` blijft een gesorteerde set (determinisme-
    contract); de draaiuren per product staan apart in ``product_hours`` zodat
    de volgorde daar bovenop gelegd kan worden zonder de telling te raken.
    """
    periods = list(getattr(engine.data, 'periods', []) or [])
    machines = getattr(engine.data, 'machines', None) or {}
    materials = getattr(engine.data, 'materials', None) or {}

    # Line 07-materiaalregels per machine (aux_column = machinecode).
    products = {}        # machine -> period -> set(material)
    hours = {}           # machine -> period -> uren
    product_hours = {}   # machine -> material -> period -> uren
    for row in (engine.results or {}).get(LineType.CAPACITY_UTILIZATION.value, []):
        if getattr(row, 'product_type', None) in ('Machine', 'Machine Group'):
            continue
        machine_code = str(getattr(row, 'aux_column', '') or '')
        if not machine_code:
            continue
        material = str(row.material_number)
        for period in periods:
            value = float((row.values or {}).get(period, 0.0) or 0.0)
            if value <= _MIN_HOURS:
                continue
            products.setdefault(machine_code, {}).setdefault(period, set()).add(material)
            hours.setdefault(machine_code, {})[period] = \
                hours.get(machine_code, {}).get(period, 0.0) + value
            per_mat = product_hours.setdefault(machine_code, {}).setdefault(material, {})
            per_mat[period] = round(per_mat.get(period, 0.0) + value, 2)

    # Beschikbaarheidsvenster: Line 11 per groep; machines erven hun groep.
    window_by_group = {}
    for row in (engine.results or {}).get(LineType.SHIFT_AVAILABILITY.value, []):
        window_by_group[str(row.material_number)] = dict(row.values or {})

    out = {}
    for code in sorted(set(products) | set(machines)):
        machine = machines.get(code)
        group = str(getattr(machine, 'machine_group', '') or '')
        window = window_by_group.get(group, {})
        mats = product_hours.get(code, {})
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
            'product_hours': {m: dict(mats[m]) for m in sorted(mats)},
            'product_names': {
                m: str(getattr(materials.get(m), 'name', '') or '') for m in sorted(mats)},
        }
    return {'periods': periods, 'machines': out}


def _default_sequence(product_hours: Dict[str, Dict[str, float]]) -> List[str]:
    """Standaardvolgorde: grootste run over de horizon eerst, dan op code —
    deterministisch, en de meest gangbare planningsreflex (lange runs vooraan,
    kleine partijen erachteraan)."""
    return sorted(product_hours,
                  key=lambda m: (-round(sum(product_hours[m].values()), 6), m))


def _effective_sequence(saved: Optional[List[str]],
                        product_hours: Dict[str, Dict[str, float]]) -> Tuple[List[str], str]:
    """Sessievolgorde toegepast op wat er NU draait: producten uit de wat-als
    die niet meer draaien vallen weg, nieuwe producten hangen er in
    standaardvolgorde achter. Zo overleeft een volgorde een herberekening
    zonder stil te liegen over producten die er niet meer zijn."""
    default = _default_sequence(product_hours)
    if not saved:
        return default, 'standaard'
    kept = [m for m in saved if m in product_hours]
    rest = [m for m in default if m not in kept]
    return kept + rest, 'wat-als'


def _changeover_rates(engine, changeovers: dict) -> Dict[str, dict]:
    """Tarief per machine: omsteltijd-masterdata wint, anders machinetarief."""
    machine_costs = getattr(engine.data, 'machine_costs', None) or {}
    rates = {}
    for code in set(changeovers) | set(getattr(engine.data, 'machines', None) or {}):
        item = changeovers.get(code) or {}
        own = item.get('cost_per_hour')
        if own is not None:
            rates[code] = {'rate': float(own), 'source': 'omsteltijden'}
            continue
        mc = machine_costs.get(code)
        rate = float(getattr(mc, 'variable_cost_per_hour', 0.0) or 0.0) if mc else 0.0
        rates[code] = {'rate': rate, 'source': 'machinetarief' if mc and rate > 0 else None}
    return rates


def build_machine_inzet(engine, sess: dict, changeovers: dict) -> dict:
    """Het volledige tabbladpayload: gebruik + volgorde + telling + kosten.

    Alle rekenwerk staat hier (niet in de browser) zodat de getallen die de
    klant ziet in een unittest vast te pinnen zijn.
    """
    usage = _machine_usage(engine)
    periods = usage['periods']
    overrides = dict((sess or {}).get('changeover_overrides') or {})
    sequences = dict((sess or {}).get('changeover_sequences') or {})
    rates = _changeover_rates(engine, changeovers)

    totals_by_period = {p: {'changeovers': 0, 'changeover_hours': 0.0, 'cost': 0.0}
                        for p in periods}
    grand = {'changeovers': 0, 'changeover_hours': 0.0, 'cost': 0.0, 'run_hours': 0.0}
    machines_out = {}
    for code, info in usage['machines'].items():
        changeover = changeovers.get(code)
        hours_per = (float(changeover.get('hours_per_changeover') or 0.0)
                     if changeover else None)
        rate = rates.get(code, {'rate': 0.0, 'source': None})
        sequence, seq_source = _effective_sequence(sequences.get(code), info['product_hours'])
        per_period = {}
        machine_total = {'changeovers': 0, 'changeover_hours': 0.0, 'cost': 0.0,
                         'run_hours': 0.0}
        for p in periods:
            cel = info['per_period'][p]
            estimate = max(0, len(cel['products']) - 1)
            key = f'{code}|{p}'
            is_override = key in overrides
            count = int(overrides[key]) if is_override else estimate
            ch_hours = round(count * hours_per, 2) if hours_per is not None else None
            cost = round(ch_hours * rate['rate'], 2) if ch_hours is not None else None
            pct = (round(ch_hours / cel['window'] * 100, 2)
                   if ch_hours is not None and cel['window'] > 0 else None)
            per_period[p] = {
                **cel,
                'estimate': estimate,
                'changeovers': count,
                'is_override': is_override,
                'changeover_hours': ch_hours,
                'cost': cost,
                'window_pct': pct,
            }
            machine_total['changeovers'] += count
            machine_total['run_hours'] += cel['hours']
            totals_by_period[p]['changeovers'] += count
            if ch_hours is not None:
                machine_total['changeover_hours'] += ch_hours
                totals_by_period[p]['changeover_hours'] += ch_hours
            if cost is not None:
                machine_total['cost'] += cost
                totals_by_period[p]['cost'] += cost
        for k in ('changeover_hours', 'cost', 'run_hours'):
            machine_total[k] = round(machine_total[k], 2)
        grand['changeovers'] += machine_total['changeovers']
        grand['changeover_hours'] += machine_total['changeover_hours']
        grand['cost'] += machine_total['cost']
        grand['run_hours'] += machine_total['run_hours']
        machines_out[code] = {
            'name': info['name'],
            'machine_group': info['machine_group'],
            'hours_per_changeover': hours_per,
            'rate': rate['rate'],
            'rate_source': rate['source'],
            'sequence': sequence,
            'sequence_source': seq_source,
            'product_hours': info['product_hours'],
            'product_names': info['product_names'],
            'per_period': per_period,
            'total': machine_total,
        }
    for p in periods:
        for k in ('changeover_hours', 'cost'):
            totals_by_period[p][k] = round(totals_by_period[p][k], 2)
    for k in ('changeover_hours', 'cost', 'run_hours'):
        grand[k] = round(grand[k], 2)
    return {
        'periods': periods,
        'machines': machines_out,
        'totals': {'by_period': totals_by_period, 'horizon': grand},
        'changeover_times': changeovers,
        'overrides': overrides,
        'sequences': sequences,
    }


def _changeovers_from_store(engine) -> dict:
    """Omsteltijden LIVE uit de store: de motor consumeert ze in fase 1 niet,
    dus de store is de eerlijke bron — engine.data zou een zojuist opgeslagen
    omsteltijd pas na een herberekening tonen. Storeless sessies vallen terug
    op wat de engine (via hydratie) meekreeg."""
    from ui import master_store

    def _norm(hours, description, cost):
        return {
            'hours_per_changeover': float(hours or 0.0),
            'description': str(description or ''),
            'cost_per_hour': None if cost is None or cost == '' else float(cost),
        }

    record = master_store.get_current_master_record()
    if record is not None:
        raw = (record.get('master') or {}).get('changeover_times') or {}
        return {str(code): _norm(item.get('hours_per_changeover'), item.get('description'),
                                 item.get('cost_per_hour'))
                for code, item in raw.items()}
    return {str(code): _norm(item.hours_per_changeover, item.description,
                             getattr(item, 'cost_per_hour', None))
            for code, item in (getattr(engine.data, 'changeover_times', None) or {}).items()}


def create_machine_inzet_blueprint(
    get_active: Callable[[], tuple],
    save_sessions_to_disk: Callable[[], None],
) -> Blueprint:
    bp = Blueprint('machine_inzet', __name__)

    def _guard():
        sess, engine = get_active()
        if engine is None or getattr(engine, 'data', None) is None:
            return None, None, (jsonify({'error': _NO_ENGINE}), 400)
        mismatch = _site_mismatch(engine)
        if mismatch:
            return None, None, (jsonify({'error': _SITE_MISMATCH.format(**mismatch),
                                         **mismatch}), 409)
        return sess, engine, None

    @bp.route('/api/machine_inzet', methods=['GET'])
    def get_machine_inzet():
        sess, engine, err = _guard()
        if err:
            return err
        payload = build_machine_inzet(engine, sess, _changeovers_from_store(engine))
        return jsonify({'success': True, **payload})

    @bp.route('/api/machine_inzet/overrides', methods=['POST'])
    def set_overrides():
        """Weergave-wat-als op het AANTAL omstellingen per machine|periode.

        Volledige set per POST (leeg = alles terug naar de schatting), zelfde
        contract als de norm-overrides. Persisteert in de sessie; geen
        herberekening — fase 1 rekent nergens mee.
        """
        sess, engine, err = _guard()
        if err:
            return err
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

    @bp.route('/api/machine_inzet/sequences', methods=['POST'])
    def set_sequences():
        """Weergave-wat-als op de PRODUCTVOLGORDE per machine.

        Volledige set per POST: {MACHINE: [materiaal, ...]}. Een machine
        weglaten (of een lege lijst) = terug naar de standaardvolgorde.
        Onbekende materialen in een lijst worden geweigerd — een volgorde
        met een spookproduct zou stil wegvallen bij het toepassen.
        """
        sess, engine, err = _guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        raw = body.get('sequences')
        if not isinstance(raw, dict):
            return jsonify({'error': 'Verwacht een object "sequences".'}), 400
        usage = _machine_usage(engine)
        sequences = {}
        for machine, seq in raw.items():
            code = str(machine)
            if code not in usage['machines']:
                return jsonify({'error': f'Volgorde "{code}": onbekende machine.'}), 400
            if not isinstance(seq, list) or not all(isinstance(m, str) for m in seq):
                return jsonify({'error': f'Volgorde "{code}": verwacht een lijst materiaalnummers.'}), 400
            if len(set(seq)) != len(seq):
                return jsonify({'error': f'Volgorde "{code}": een product staat er dubbel in.'}), 400
            known = set(usage['machines'][code]['product_hours'])
            unknown = [m for m in seq if m not in known]
            if unknown:
                return jsonify({'error': f'Volgorde "{code}": {", ".join(unknown)} draait niet op deze machine.'}), 400
            if seq:
                sequences[code] = list(seq)
        sess['changeover_sequences'] = sequences
        save_sessions_to_disk()
        return jsonify({'success': True, 'sequences': sequences})

    return bp
