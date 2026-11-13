"""Aannames voor klantdata die nog ontbreekt (Maastricht-uitgave).

De klant levert een aantal invoerwaarden pas later aan; de informatie-uitvraag
van 9 november 2026 zegt voor die gevallen uitdrukkelijk: "een eerste
indicatie volstaat, het is een instelling die jullie later zelf aanpassen".
Deze module vult zulke gaten met een AANNAME: een getal uit een vaste,
gedocumenteerde regel, dat in de masterdata staat als elk ander getal en daar
gewoon te wijzigen is.

Wat een aanname onderscheidt van klantdata, staat in het record zelf:

- ``origin = 'aanname'``, ``origin_rule`` (welke regel, welke versie) en
  ``origin_value`` (de gegenereerde waarde). Een record waarvan de waarde nog
  gelijk is aan ``origin_value`` is een ongewijzigde aanname; wijkt de waarde
  af, dan heeft iemand hem aangepast en blijft hij altijd staan.
- ``origin = 'bevestigd'``: de gebruiker heeft de aanname uitdrukkelijk als
  juist aangemerkt. Ook die blijft altijd staan.
- de toelichting begint met "Aanname", zodat het in het masterdata-grid en in
  het masterwerkboek zichtbaar is zonder kolom erbij.

Bewust NIET gegenereerd:

- bemensingsnormen en loontarieven: de motor heeft daar al een werkende
  terugval (de Line-12-coëfficiënt, het 'default'-tarief). Een kopie van die
  terugval als record zou haar bevriezen en een later aangeleverde
  klantwaarde maskeren.
- doorzet-overrides en MES/PEER-benchmarks: dat zijn metingen of
  gezaghebbende klantgetallen; een verzonnen meting misleidt.

Alleen de Maastricht-uitgave kent omsteltijden; de site-uitgaven bevatten
deze module niet.
"""

from __future__ import annotations

import copy
import math
from typing import Dict, List, Optional, Tuple

ORIGIN_ASSUMED = 'aanname'
ORIGIN_CONFIRMED = 'bevestigd'

# Regelset voor omsteltijden, op het SAP-machinecodeprefix (de naamgeving van
# de klant: PML maalinstallatie, PBA afvul-/zakmachine, PSS breker, PWP zeef,
# PPM menging/voorbereiding). Uren per omstelling; een orde van grootte, geen
# meting. Wie de regel wijzigt, verhoogt de versie: bestaande aannames houden
# hun eigen origin_value en worden dus nooit stil 'aangepast'.
CHANGEOVER_RULESET = 'omstel-v1'
CHANGEOVER_RULES: List[Tuple[str, float, str]] = [
    ('PML', 2.0, 'maalinstallatie'),
    ('PBA', 0.5, 'afvulmachine'),
    ('PSS', 1.0, 'breker'),
    ('PWP', 0.5, 'zeef'),
    ('PPM', 1.0, 'menging/voorbereiding'),
]
CHANGEOVER_FALLBACK = (1.0, 'overige installatie')


def changeover_rule_for(machine_code: str) -> Tuple[float, str]:
    code = str(machine_code or '').strip().upper()
    for prefix, hours, label in CHANGEOVER_RULES:
        if code.startswith(prefix):
            return hours, label
    return CHANGEOVER_FALLBACK


def _fmt_hours(hours: float) -> str:
    return f'{hours:g}'.replace('.', ',')


def _changeover_candidates(master: dict) -> List[str]:
    """Machines that run real production: listed in the master, not marked
    as unlimited capacity (a virtual installation has nothing to change over)."""
    unlimited = {str(m).strip().upper() for m in
                 ((master.get('config') or {}).get('unlimited_capacity_machine') or [])}
    codes = []
    for machine in master.get('machines') or []:
        code = str((machine or {}).get('machine_code') or '').strip()
        if code and code.upper() not in unlimited:
            codes.append(code)
    return sorted(set(codes))


def changeover_placeholders(master: dict) -> Dict[str, dict]:
    """Records for every production machine WITHOUT a changeover record.
    Deterministic, and never a record for a key that already exists."""
    existing = master.get('changeover_times') or {}
    out = {}
    for code in _changeover_candidates(master):
        if code in existing:
            continue
        hours, label = changeover_rule_for(code)
        out[code] = {
            'machine_code': code,
            'hours_per_changeover': hours,
            'cost_per_hour': None,
            'description': (f'Aanname ({label}, {_fmt_hours(hours)} u per omstelling, '
                            f'regel {CHANGEOVER_RULESET}). Vervang door de klantwaarde.'),
            'origin': ORIGIN_ASSUMED,
            'origin_rule': CHANGEOVER_RULESET,
            'origin_value': hours,
        }
    return out


def _as_float(value) -> Optional[float]:
    """A finite float, else None. NaN compares unequal to everything, so a
    NaN value would otherwise slip through the equality checks below."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def origin_state(record: dict) -> str:
    """'' (klant/gebruiker), 'aanname' (ongewijzigd), 'aangepast' (een aanname
    waarvan de waarde gewijzigd is) of 'bevestigd'.

    De toestand volgt uit de HUIDIGE waarde, niet uit de bewerkgeschiedenis:
    wie een aanname wijzigt en daarna precies terugzet, heeft weer een
    ongewijzigde aanname (die dus ook weer te verwijderen is). Een record met
    een ongeldige waarde (leeg, NaN, oneindig) telt als aangepast: verwijderen
    of bevestigen mag nooit op een waarde berusten die niet te vergelijken is."""
    origin = str((record or {}).get('origin') or '')
    if origin == ORIGIN_CONFIRMED:
        return ORIGIN_CONFIRMED
    if origin != ORIGIN_ASSUMED:
        return ''
    current = _as_float((record or {}).get('hours_per_changeover'))
    generated = _as_float((record or {}).get('origin_value'))
    if current is None or generated is None or abs(current - generated) > 1e-9:
        return 'aangepast'
    if (record or {}).get('cost_per_hour') not in (None, ''):
        # Een eigen tarief toegevoegd: iemand heeft deze regel bewust aangevuld.
        return 'aangepast'
    return ORIGIN_ASSUMED


def placeholder_status(master: dict) -> dict:
    existing = master.get('changeover_times') or {}
    states = {key: origin_state(rec) for key, rec in existing.items() if isinstance(rec, dict)}
    missing = changeover_placeholders(master)
    return {
        'dataset': 'changeover_times',
        'ruleset': CHANGEOVER_RULESET,
        'rules': [{'prefix': p, 'hours': h, 'label': label} for p, h, label in CHANGEOVER_RULES]
                 + [{'prefix': '*', 'hours': CHANGEOVER_FALLBACK[0], 'label': CHANGEOVER_FALLBACK[1]}],
        'would_add': sorted(missing),
        'would_add_detail': {k: v['hours_per_changeover'] for k, v in sorted(missing.items())},
        'assumed': sorted(k for k, s in states.items() if s == ORIGIN_ASSUMED),
        'adjusted': sorted(k for k, s in states.items() if s == 'aangepast'),
        'confirmed': sorted(k for k, s in states.items() if s == ORIGIN_CONFIRMED),
        'client': sorted(k for k, s in states.items() if s == ''),
    }


def apply_placeholders(master: dict) -> Tuple[dict, List[str]]:
    """A copy of the master with the missing changeover records added."""
    candidate = copy.deepcopy(master)
    added = changeover_placeholders(candidate)
    dataset = dict(candidate.get('changeover_times') or {})
    dataset.update(added)
    candidate['changeover_times'] = dataset
    return candidate, sorted(added)


def remove_placeholders(master: dict) -> Tuple[dict, List[str]]:
    """A copy of the master without the assumptions whose hours still equal
    the generated value and that have no own rate. Adjusted, confirmed and
    client records stay."""
    candidate = copy.deepcopy(master)
    dataset = dict(candidate.get('changeover_times') or {})
    removed = sorted(k for k, rec in dataset.items()
                     if isinstance(rec, dict) and origin_state(rec) == ORIGIN_ASSUMED)
    for key in removed:
        del dataset[key]
    candidate['changeover_times'] = dataset
    return candidate, removed


def confirm_placeholders(master: dict, keys: Optional[List[str]] = None) -> Tuple[dict, List[str]]:
    """A copy of the master with the given (default: all) unchanged
    assumptions marked as confirmed by the user."""
    candidate = copy.deepcopy(master)
    dataset = dict(candidate.get('changeover_times') or {})
    wanted = None if keys is None else {str(k) for k in keys}
    confirmed = []
    for key, rec in dataset.items():
        if not isinstance(rec, dict) or origin_state(rec) != ORIGIN_ASSUMED:
            continue
        if wanted is not None and key not in wanted:
            continue
        updated = dict(rec)
        updated['origin'] = ORIGIN_CONFIRMED
        updated['description'] = (f"Aanname (regel {rec.get('origin_rule') or CHANGEOVER_RULESET}, "
                                  f"oorspronkelijk {_fmt_hours(float(rec.get('origin_value')))} u), "
                                  f"door een gebruiker als juist bevestigd.")
        dataset[key] = updated
        confirmed.append(key)
    candidate['changeover_times'] = dataset
    return candidate, sorted(confirmed)
