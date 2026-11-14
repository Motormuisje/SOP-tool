"""Scenariovergelijking: kerncijfers per scenario, naast elkaar.

Leest alleen wat de motor al heeft berekend en in een scenario-snapshot staat
(``results`` en ``value_results`` als lijsten van rij-dicts). Er wordt niets
herberekend en er is geen nieuwe bedrijfslogica:

- **Financieel**: het horizongetal van elke consolidatieregel staat in
  ``aux_2_column`` en is precies wat de VBA daar zet (SOM voor stromen als
  omzet en EBIT, GEMIDDELDE voor saldi als voorraadwaarde en werkkapitaal,
  voor de voorraadwaarde inclusief de beginvoorraad; ROCE = totale EBIT /
  gemiddeld geïnvesteerd vermogen). Dit module telt die regels niet zelf op.
- **Volume**: sommen over materiaalregels (ton), eindvoorraad = laatste periode.
- **Uitzonderingen**: materiaal-maanden met voorraad onder het minimumdoel
  (Line 04 < Line 05, alleen materialen mét een doelregel) en met negatieve
  voorraad. Een uitzonderingstelling, geen servicegraad.
- **Capaciteit**: Line 10 (benuttingsgraad per machine, 1,0 = 100 %).
  Overbelast = boven 100 %. Machines met onbeperkte capaciteit (Config
  MachineUnlimitedCapacity, door de motor altijd op 1,0 gezet) tellen niet
  mee in de top; welke dat zijn staat in het scenario zelf.
- **FTE**: Line 12 (de VBA-FTE), per maand opgeteld en dan gemiddeld.

Deltas worden alleen berekend als de horizon gelijk is aan die van de basis;
anders zou een horizongetal (ROCE, een som) twee verschillende periodes
vergelijken.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

LT_DEMAND_FORECAST = '01. Demand forecast'
LT_TOTAL_DEMAND = '03. Total demand'
LT_INVENTORY = '04. Inventory'
LT_MIN_TARGET = '05. Minimum target stock'
LT_PRODUCTION = '06. Production plan'
LT_PURCHASE_RECEIPT = '06. Purchase receipt'
LT_UTILIZATION = '10. Utilization rate'
LT_FTE = '12. FTE requirements'
LT_CONSOLIDATION = '13. Consolidation'

# (sleutel, consolidatieregel, label, eenheid, richting). Richting: +1 hoger is
# beter, -1 lager is beter, 0 neutraal (hoger is niet vanzelf beter of slechter).
FINANCIAL_KPIS = [
    ('turnover', 'ZZZZZZ_TURNOVER', 'Omzet', 'EUR', 0),
    ('cost_of_goods', 'ZZZZZZ_COST OF GOODS', 'Kostprijs omzet', 'EUR', 0),
    ('gross_margin', 'ZZZZZZ_GROSS MARGIN', 'Brutomarge', 'EUR', 1),
    ('ebitda', 'ZZZZZZ_EBITDA', 'EBITDA', 'EUR', 1),
    ('ebit', 'ZZZZZZ_EBIT', 'EBIT', 'EUR', 1),
    ('operational_cashflow', 'ZZZZZZ_OPERATIONAL CASHFLOW', 'Operationele kasstroom', 'EUR', 1),
    ('inventory_value', 'ZZZZZZ_INVENTORY VALUE', 'Voorraadwaarde (gem. incl. begin)', 'EUR', 0),
    ('working_capital', 'ZZZZZZ_WORKING CAPITAL REQUIREMENTS', 'Werkkapitaal (gem.)', 'EUR', 0),
    ('roce', 'ZZZZZZ_ROCE', 'ROCE', 'ratio', 1),
]

# Wat de vergelijking standaard toont; de rest staat achter 'meer cijfers'.
HEADLINE_KPIS = ['ebit', 'operational_cashflow', 'inventory_value', 'ending_inventory',
                 'stock_negative', 'overloaded_machine_months']

OTHER_KPIS = [
    ('total_demand', 'Totale vraag', 't', 0),
    ('production', 'Productie', 't', 0),
    ('purchase_receipts', 'Inkoopontvangsten', 't', 0),
    ('ending_inventory', 'Eindvoorraad', 't', 0),
    ('below_target', 'Maanden onder minimumdoel', 'materiaal-maanden', -1),
    ('stock_negative', 'Maanden met negatieve voorraad', 'materiaal-maanden', -1),
    ('overloaded_machine_months', 'Overbelaste machine-maanden (>100 %)', 'machine-maanden', -1),
    ('peak_utilization', 'Hoogste benutting', 'ratio', 0),
    ('fte_avg', 'FTE (Line 12, gem. per maand)', 'FTE', 0),
]

KPI_META = {key: {'label': label, 'unit': unit, 'direction': direction}
            for key, _row, label, unit, direction in FINANCIAL_KPIS}
KPI_META.update({key: {'label': label, 'unit': unit, 'direction': direction}
                 for key, label, unit, direction in OTHER_KPIS})
KPI_ORDER = HEADLINE_KPIS + [k for k in KPI_META if k not in HEADLINE_KPIS]


def _num(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rows(snapshot: dict, line_type: str) -> List[dict]:
    return [r for r in (snapshot.get(line_type) or []) if isinstance(r, dict)]


def snapshot_periods(results: dict) -> List[str]:
    """The horizon of a snapshot: the period keys of its demand rows."""
    for line_type in (LT_DEMAND_FORECAST, LT_TOTAL_DEMAND, LT_INVENTORY):
        for row in _rows(results, line_type):
            values = row.get('values') or {}
            if values:
                return sorted(values)
    return []


def _sum_rows(rows: Iterable[dict], periods: List[str]) -> float:
    total = 0.0
    for row in rows:
        values = row.get('values') or {}
        for p in periods:
            total += _num(values.get(p)) or 0.0
    return total


def _consolidation(value_results: dict) -> Dict[str, dict]:
    return {str(r.get('material_number')): r for r in _rows(value_results, LT_CONSOLIDATION)}


def compute_kpis(results: dict, value_results: dict, unlimited_machines=()) -> dict:
    """Kerncijfers, per-periodereeksen en uitzonderingslijsten van één snapshot.
    ``unlimited_machines``: machinecodes met onbeperkte capaciteit."""
    unlimited_codes = {str(m).strip().upper() for m in (unlimited_machines or ())}
    periods = snapshot_periods(results)
    consol = _consolidation(value_results or {})
    kpis: Dict[str, Optional[float]] = {}
    series: Dict[str, Dict[str, float]] = {}

    for key, row_name, _label, _unit, _direction in FINANCIAL_KPIS:
        row = consol.get(row_name)
        if row is None:
            kpis[key] = None
            continue
        horizon = _num(row.get('aux_2_column'))
        # De motor laat aux_2 leeg als het horizongetal 0 is (zie ROCE).
        kpis[key] = horizon if horizon is not None else 0.0
        series[key] = {p: _num((row.get('values') or {}).get(p)) or 0.0 for p in periods}

    kpis['total_demand'] = _sum_rows(_rows(results, LT_TOTAL_DEMAND), periods)
    kpis['production'] = _sum_rows(_rows(results, LT_PRODUCTION), periods)
    kpis['purchase_receipts'] = _sum_rows(_rows(results, LT_PURCHASE_RECEIPT), periods)
    kpis['ending_inventory'] = _sum_rows(_rows(results, LT_INVENTORY), periods[-1:]) if periods else 0.0

    targets = {}
    for row in _rows(results, LT_MIN_TARGET):
        targets[str(row.get('material_number'))] = row.get('values') or {}
    below, negative, eligible = [], [], 0
    for row in _rows(results, LT_INVENTORY):
        material = str(row.get('material_number'))
        values = row.get('values') or {}
        target = targets.get(material)
        for p in periods:
            stock = _num(values.get(p))
            if stock is None:
                continue
            if stock < 0:
                negative.append({'material': material, 'name': row.get('material_name') or '',
                                 'period': p, 'stock': stock})
            if target is not None:
                eligible += 1
                minimum = _num(target.get(p))
                if minimum is not None and stock < minimum - 1e-9:
                    below.append({'material': material, 'name': row.get('material_name') or '',
                                  'period': p, 'stock': stock, 'target': minimum,
                                  'shortfall': minimum - stock})
    kpis['below_target'] = float(len(below))
    kpis['stock_negative'] = float(len(negative))

    overloaded, peaks = [], []
    for row in _rows(results, LT_UTILIZATION):
        values = {p: _num((row.get('values') or {}).get(p)) for p in periods}
        present = [v for v in values.values() if v is not None]
        if not present:
            continue
        machine = str(row.get('material_name') or row.get('material_number'))
        unlimited = machine.strip().upper() in unlimited_codes
        for p, v in values.items():
            if v is not None and v > 1.0 + 1e-9 and not unlimited:
                overloaded.append({'machine': machine, 'group': row.get('product_family') or '',
                                   'period': p, 'utilization': v})
        if not unlimited:
            peak_period = max((p for p in values if values[p] is not None), key=lambda p: values[p])
            peaks.append({'machine': machine, 'group': row.get('product_family') or '',
                          'period': peak_period, 'utilization': values[peak_period]})
    peaks.sort(key=lambda item: (-item['utilization'], item['machine']))
    kpis['overloaded_machine_months'] = float(len(overloaded))
    kpis['peak_utilization'] = peaks[0]['utilization'] if peaks else None

    fte_rows = _rows(results, LT_FTE)
    monthly_fte = {p: sum(_num((r.get('values') or {}).get(p)) or 0.0 for r in fte_rows) for p in periods}
    kpis['fte_avg'] = (sum(monthly_fte.values()) / len(periods)) if periods else None
    series['fte'] = monthly_fte

    below.sort(key=lambda item: (-item['shortfall'], item['material'], item['period']))
    negative.sort(key=lambda item: (item['stock'], item['material'], item['period']))
    overloaded.sort(key=lambda item: (-item['utilization'], item['machine'], item['period']))
    return {
        'periods': periods,
        'kpis': kpis,
        'series': series,
        'eligible_target_months': eligible,
        'exceptions': {
            'below_target': below[:50],
            'stock_negative': negative[:50],
            'overloaded': overloaded[:50],
            'top_machines': peaks[:5],
        },
    }


def _input_summary(scenario: dict) -> dict:
    return {
        'edit_count': len(scenario.get('pending_edits') or {}),
        'machine_overrides': len(scenario.get('machine_overrides') or {}),
        'valuation_params': {str(k): _num(v) for k, v in (scenario.get('valuation_params') or {}).items()},
        'purchased_and_produced': str(scenario.get('purchased_and_produced') or ''),
    }


def input_changes(scenario: dict, base: dict) -> List[str]:
    """Welke opgeslagen invoer van dit scenario afwijkt van die van de basis."""
    mine, theirs = _input_summary(scenario), _input_summary(base)
    changes = []
    if (scenario.get('pending_edits') or {}) != (base.get('pending_edits') or {}):
        changes.append(f"planbewerkingen ({mine['edit_count']} t.o.v. {theirs['edit_count']})")
    if (scenario.get('machine_overrides') or {}) != (base.get('machine_overrides') or {}):
        changes.append(f"machine-instellingen ({mine['machine_overrides']} t.o.v. {theirs['machine_overrides']})")
    if mine['valuation_params'] != theirs['valuation_params']:
        changes.append('waarderingsparameters')
    if mine['purchased_and_produced'] != theirs['purchased_and_produced']:
        changes.append('verdeling eigen productie / inkoop')
    return changes


def compare(columns: List[dict]) -> dict:
    """``columns``: scenario-dicts (results, value_results, naam, ...). De
    eerste is de basis. Deltas alleen bij dezelfde horizon als de basis."""
    computed = []
    for column in columns:
        data = compute_kpis(column.get('results') or {}, column.get('value_results') or {},
                            column.get('unlimited_machines') or ())
        computed.append((column, data))
    base_column, base = computed[0]
    out = []
    for index, (column, data) in enumerate(computed):
        comparable = data['periods'] == base['periods'] and bool(data['periods'])
        deltas = {}
        if index > 0 and comparable:
            for key, value in data['kpis'].items():
                ref = base['kpis'].get(key)
                deltas[key] = (value - ref) if value is not None and ref is not None else None
        out.append({
            'id': column.get('id'),
            'name': column.get('name'),
            'timestamp': column.get('timestamp'),
            'is_current': bool(column.get('is_current')),
            'master_version': column.get('master_version'),
            'compatibility': 'gelijk' if comparable else 'andere horizon',
            # Bekend = het scenario legde vast uit welke masterdataversie het is
            # berekend. Verschilt die van de basis, dan meldt de UI dat.
            'master_version_known': column.get('master_version') is not None,
            'master_version_differs': (index > 0 and column.get('master_version') is not None
                                       and base_column.get('master_version') is not None
                                       and column.get('master_version') != base_column.get('master_version')),
            'unlimited_assumed': bool(column.get('unlimited_assumed')),
            'input_changes': input_changes(column, base_column) if index > 0 else [],
            **data,
            'deltas': deltas,
        })
    return {'columns': out, 'kpi_meta': KPI_META, 'kpi_order': KPI_ORDER, 'headline': HEADLINE_KPIS}
