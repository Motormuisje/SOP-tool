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

Kosten (fase 1b): omsteluren × tarief, gerekend op de ONafgeronde uren en
pas bij de uitvoer afgerond (0,125 u × € 120 = € 15,00, niet 0,12 u × 120).
Het tarief komt uit de omsteltijd-masterdata (``cost_per_hour``) en valt
terug op het machinetarief uit ``machine_costs`` — dezelfde SAP-bron als de
waardeplanning (zonder de sessie-AUX-override van het waardetabblad) —
zodat elke machine met een omsteltijd direct een kostprijs laat zien, met
de herkomst erbij. Omsteltijden, tarieven én machinetarieven komen LIVE
uit de masterstore, zodat een zojuist opgeslagen waarde meteen zichtbaar
is zonder herberekening.

Het beschikbaarheidsvenster (``window``) is de Line 11-waarde van de
machinegroep — dezelfde conventie als de FTE-werkbank; ``window_pct`` is
dus het aandeel in het groepsvenster.

Fase 1 rekent bewust nergens in door: de omsteluren verlagen het
beschikbaarheidsvenster pas in fase 2 (rekenkern, met additiviteitsbewijs).
De sessie-overrides (aantal, volgorde) zijn daarom WEERGAVE-wat-als: ze
persisteren (sessiestore, scenario's, duplicaat) en worden — net als de
machine-overrides, actieve combinaties en normen-wat-als — gewist door
Reset én door een nieuwe berekening (``/api/calculate``); een
edit-herberekening (replay) en een configwijziging laten ze staan. Ze
reizen niet door config_overrides/snapshot/replay — er is geen motor die
ze consumeert. Zodra fase 2 ze laat meerekenen, verhuizen ze naar de
volledige zes-syncpuntenmal, net als fte_norm_overrides.

Volgordes worden tolerant opgeschoond: producten die niet meer op de
machine draaien vallen weg, nieuwe hangen er in standaardvolgorde achter,
en een POST met een verouderde entry (machine of product weg) wordt niet
geweigerd maar gesnoeid, met een waarschuwing in het antwoord — één
spookproduct mag nooit alle volgorde-acties blokkeren.
"""

import math
from typing import Callable, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from modules.models import LineType
from ui.routes.fte import _SITE_MISMATCH, _site_mismatch

_NO_ENGINE = 'Nog geen berekening uitgevoerd.'

# Uren onder deze drempel tellen niet als 'product draait op deze machine':
# afrondingsruis uit de cascade mag geen omstelling suggereren.
_MIN_HOURS = 0.01


def _num(value) -> Optional[float]:
    """Eindig getal of None: '' / None / tekst / nan / inf worden None."""
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
            per_mat[period] = per_mat.get(period, 0.0) + value

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
            # Eén afronding per product×periode (niet per accumulatiestap),
            # zodat de blokken op het bord optellen tot de balk.
            'product_hours': {m: {p: round(h, 2) for p, h in mats[m].items()}
                              for m in sorted(mats)},
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
    standaardvolgorde achter. Blijft er van de keuze niets over, dan is de
    volgorde de standaard en heet ze ook zo — een badge 'wat-als' op een
    keuze die op niets meer slaat zou liegen."""
    default = _default_sequence(product_hours)
    kept = [m for m in (saved or []) if m in product_hours]
    if not kept:
        return default, 'standaard'
    rest = [m for m in default if m not in kept]
    return kept + rest, 'wat-als'


def _prune_sequences(sequences: dict, usage: dict) -> Tuple[Dict[str, List[str]], List[str]]:
    """Opgeslagen volgordes snoeien tegen wat er nu draait.

    Verouderde entries (machine weg, product niet meer op de machine, lege
    lijst) vallen weg met een leesbare waarschuwing. Dit is dezelfde regel
    als ``_effective_sequence``, zodat GET en POST hetzelfde contract hebben
    en de client nooit spookproducten terugkrijgt die hij daarna zou echoën.
    """
    clean: Dict[str, List[str]] = {}
    warnings: List[str] = []
    machines = usage.get('machines') or {}
    for machine, seq in (sequences or {}).items():
        code = str(machine)
        info = machines.get(code)
        if info is None:
            warnings.append(f'Volgorde "{code}": machine draait niet (meer) in deze horizon — weggelaten.')
            continue
        known = set(info.get('product_hours') or {})
        kept, gone = [], []
        for m in list(seq or []):
            (kept if m in known else gone).append(str(m))
        if gone:
            warnings.append(f'Volgorde "{code}": {", ".join(gone)} draait niet (meer) op deze machine — weggelaten.')
        if kept:
            clean[code] = kept
    return clean, warnings


def _changeover_rates(engine, changeovers: dict,
                      machine_costs_live: Optional[Dict[str, float]] = None) -> Dict[str, dict]:
    """Tarief per machine: omsteltijd-masterdata wint, anders machinetarief.

    ``machine_costs_live`` (uit de masterstore) gaat vóór ``engine.data``:
    de PATCH-route herbouwt niets, dus een net gewijzigd machinetarief zou
    anders tot de volgende berekening met het oude bedrag rekenen."""
    machine_costs = getattr(engine.data, 'machine_costs', None) or {}
    rates = {}
    for code in set(changeovers) | set(getattr(engine.data, 'machines', None) or {}):
        item = changeovers.get(code) or {}
        own = _num(item.get('cost_per_hour'))
        if own is not None:
            rates[code] = {'rate': own, 'source': 'omsteltijden'}
            continue
        if machine_costs_live is not None and code in machine_costs_live:
            rate = _num(machine_costs_live.get(code)) or 0.0
        else:
            mc = machine_costs.get(code)
            rate = _num(getattr(mc, 'variable_cost_per_hour', None)) or 0.0 if mc else 0.0
        rates[code] = {'rate': rate, 'source': 'machinetarief' if rate > 0 else None}
    return rates


def build_machine_inzet(engine, sess: dict, changeovers: dict,
                        machine_costs_live: Optional[Dict[str, float]] = None) -> dict:
    """Het volledige tabbladpayload: gebruik + volgorde + telling + kosten.

    Alle rekenwerk staat hier (niet in de browser) zodat de getallen die de
    klant ziet in een unittest vast te pinnen zijn. Kosten en venster-aandeel
    komen uit de onafgeronde omsteluren; totalen sommeren de onafgeronde
    waarden en ronden eenmaal af (exact, tot op de cent).
    """
    usage = _machine_usage(engine)
    periods = usage['periods']
    overrides = dict((sess or {}).get('changeover_overrides') or {})
    sequences, _ = _prune_sequences((sess or {}).get('changeover_sequences') or {}, usage)
    rates = _changeover_rates(engine, changeovers, machine_costs_live)

    totals_by_period = {p: {'changeovers': 0, 'changeover_hours': 0.0, 'cost': 0.0}
                        for p in periods}
    grand = {'changeovers': 0, 'changeover_hours': 0.0, 'cost': 0.0, 'run_hours': 0.0}
    machines_out = {}
    for code, info in usage['machines'].items():
        changeover = changeovers.get(code)
        hours_per = _num(changeover.get('hours_per_changeover')) if changeover else None
        if changeover and hours_per is None:
            hours_per = 0.0
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
            raw_hours = count * hours_per if hours_per is not None else None
            raw_cost = raw_hours * rate['rate'] if raw_hours is not None else None
            pct = (round(raw_hours / cel['window'] * 100, 2)
                   if raw_hours is not None and cel['window'] > 0 else None)
            per_period[p] = {
                **cel,
                'estimate': estimate,
                'changeovers': count,
                'is_override': is_override,
                'changeover_hours': round(raw_hours, 2) + 0.0 if raw_hours is not None else None,
                'cost': round(raw_cost, 2) + 0.0 if raw_cost is not None else None,
                'window_pct': pct,
            }
            machine_total['changeovers'] += count
            machine_total['run_hours'] += cel['hours']
            totals_by_period[p]['changeovers'] += count
            if raw_hours is not None:
                machine_total['changeover_hours'] += raw_hours
                totals_by_period[p]['changeover_hours'] += raw_hours
            if raw_cost is not None:
                machine_total['cost'] += raw_cost
                totals_by_period[p]['cost'] += raw_cost
        grand['changeovers'] += machine_total['changeovers']
        grand['changeover_hours'] += machine_total['changeover_hours']
        grand['cost'] += machine_total['cost']
        grand['run_hours'] += machine_total['run_hours']
        for k in ('changeover_hours', 'cost', 'run_hours'):
            machine_total[k] = round(machine_total[k], 2) + 0.0
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
    # `+ 0.0` maakt van een negatieve nul (-0.0, uit afronding van een
    # minieme negatieve som) een gewone nul — JS zou anders '-0' tonen.
    for p in periods:
        for k in ('changeover_hours', 'cost'):
            totals_by_period[p][k] = round(totals_by_period[p][k], 2) + 0.0
    for k in ('changeover_hours', 'cost', 'run_hours'):
        grand[k] = round(grand[k], 2) + 0.0
    return {
        'periods': periods,
        'machines': machines_out,
        'totals': {'by_period': totals_by_period, 'horizon': grand},
        'changeover_times': changeovers,
        'overrides': overrides,
        'sequences': sequences,
    }


def _current_master() -> Optional[dict]:
    from ui import master_store
    record = master_store.get_current_master_record()
    return (record.get('master') or {}) if record is not None else None


def _changeovers_from_store(engine, master: Optional[dict] = None) -> dict:
    """Omsteltijden LIVE uit de store: de motor consumeert ze in fase 1 niet,
    dus de store is de eerlijke bron — engine.data zou een zojuist opgeslagen
    omsteltijd pas na een herberekening tonen. Storeless sessies vallen terug
    op wat de engine (via hydratie) meekreeg. Niet-numerieke waarden (een
    handbewerkte store) worden als 'niet ingevuld' gelezen, nooit als crash."""
    def _norm(hours, description, cost):
        return {
            'hours_per_changeover': _num(hours) or 0.0,
            'description': str(description or ''),
            'cost_per_hour': _num(cost),
        }

    if master is None:
        master = _current_master()
    if master is not None:
        raw = master.get('changeover_times') or {}
        return {str(code): _norm(item.get('hours_per_changeover'), item.get('description'),
                                 item.get('cost_per_hour'))
                for code, item in raw.items() if isinstance(item, dict)}
    return {str(code): _norm(item.hours_per_changeover, item.description,
                             getattr(item, 'cost_per_hour', None))
            for code, item in (getattr(engine.data, 'changeover_times', None) or {}).items()}


def _machine_costs_from_store(master: Optional[dict]) -> Optional[Dict[str, float]]:
    """Machinetarieven live uit de store (None = storeless: engine.data)."""
    if master is None:
        return None
    raw = master.get('machine_costs') or {}
    out = {}
    for code, item in raw.items():
        if isinstance(item, dict):
            rate = _num(item.get('variable_cost_per_hour'))
            if rate is not None:
                out[str(code)] = rate
    return out


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
        master = _current_master()
        payload = build_machine_inzet(engine, sess, _changeovers_from_store(engine, master),
                                      _machine_costs_from_store(master))
        return jsonify({'success': True, **payload})

    @bp.route('/api/machine_inzet/overrides', methods=['POST'])
    def set_overrides():
        """Weergave-wat-als op het AANTAL omstellingen per machine|periode.

        Volledige set per POST (leeg = alles terug naar de schatting), zelfde
        contract als de norm-overrides. Persisteert in de sessie; geen
        herberekening — fase 1 rekent nergens mee. Sleutels buiten de huidige
        horizon blijven bewust staan (een configwijziging laat de wat-als
        staan, zie engine_rebuild).
        """
        sess, _engine, err = _guard()
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
            if isinstance(count, bool):
                return jsonify({'error': f'Override "{key}": aantal moet een getal zijn.'}), 400
            parsed = _num(count)
            if parsed is None:
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
        Structurele fouten (geen object, geen lijst, geen tekst, dubbel
        product) geven 400; verouderde entries (machine of product draait
        niet meer) worden gesnoeid en gemeld in ``warnings`` — zo kan één
        spookproduct nooit alle andere volgorde-acties blokkeren.
        """
        sess, engine, err = _guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        raw = body.get('sequences')
        if not isinstance(raw, dict):
            return jsonify({'error': 'Verwacht een object "sequences".'}), 400
        for machine, seq in raw.items():
            code = str(machine)
            if not isinstance(seq, list) or not all(isinstance(m, str) for m in seq):
                return jsonify({'error': f'Volgorde "{code}": verwacht een lijst materiaalnummers.'}), 400
            if len(set(seq)) != len(seq):
                return jsonify({'error': f'Volgorde "{code}": een product staat er dubbel in.'}), 400
        sequences, warnings = _prune_sequences(raw, _machine_usage(engine))
        sess['changeover_sequences'] = sequences
        save_sessions_to_disk()
        return jsonify({'success': True, 'sequences': sequences, 'warnings': warnings})

    return bp
