"""Assumptions for client data that is still missing (Maastricht edition).

The client delivers some inputs later; the information request of
9 November 2026 says so explicitly for these cases: "a first indication is
enough; it is a setting you adjust yourselves later". This module fills such
gaps with an ASSUMPTION: a number from a fixed, documented rule, stored in the
master data like any other number and editable there.

What tells an assumption apart from client data is in the record itself:

- ``origin = 'aanname'``, ``origin_rule`` (which rule, which version) and
  ``origin_value`` (the generated value). A record whose value still equals
  ``origin_value`` is an unchanged assumption; once the value differs,
  somebody adjusted it and it is never removed automatically.
- ``origin = 'bevestigd'``: a user explicitly marked the assumption as
  correct. Also never removed automatically.
- the description starts with "Aanname", so it shows in the master-data grid
  and the master workbook without an extra column.

Deliberately NOT generated:

- staffing norms and labour rates: the engine already has a working fallback
  there (the Line 12 coefficient, the 'default' rate). Copying that fallback
  into records would freeze it and hide a client value delivered later.
- throughput overrides and MES/PEER benchmarks: measurements or authoritative
  client figures; an invented measurement misleads.

Only the Maastricht edition has changeover times; the site editions do not
contain this module. The origin values ('aanname', 'bevestigd') and the
generated descriptions are Dutch: they are shown in the UI.
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional, Tuple

from modules.numeric import finite_float as _as_float

ORIGIN_ASSUMED = 'aanname'
ORIGIN_CONFIRMED = 'bevestigd'

# Changeover rule set, by SAP machine-code prefix (the client's naming: PML
# mill, PBA bagging, PSS crusher, PWP sieve, PPM mixing/preparation). Hours per
# changeover; an order of magnitude, not a measurement. Changing the rule means
# a new version: existing assumptions keep their own origin_value and so never
# silently turn into 'aangepast'.
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


def origin_state(record: dict) -> str:
    """'' (client/user), 'aanname' (unchanged), 'aangepast' (an assumption
    whose value was changed) or 'bevestigd'.

    The state follows the CURRENT value, not the edit history: changing an
    assumption and setting it back exactly gives an unchanged assumption again
    (which can therefore be removed again). A record with an unreadable value
    (blank, NaN, infinite) counts as adjusted: removing or confirming must
    never rest on a value that cannot be compared."""
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
        # An own rate was added: somebody deliberately completed this record.
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
