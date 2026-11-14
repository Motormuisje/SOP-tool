"""Scenario comparison: key figures per scenario, side by side.

Reads what the engine already calculated and a scenario snapshot stores
(``results`` and ``value_results`` as lists of row dicts). Nothing is
recalculated, but the module does apply its own aggregation rules, listed
here so they can be checked:

- **Financial**: the horizon figure of each consolidation row is its
  ``aux_2_column``, which the engine sets as the VBA does (SUM for flows such
  as turnover and EBIT, AVERAGE for balances such as inventory value and
  working capital, the inventory value including the starting stock; ROCE =
  total EBIT / average capital investment). A blank aux_2 is the engine's
  way of writing 0; a value that cannot be read is reported as unknown.
- **Volume**: sums over the material rows (tonnes); ending inventory is the
  last period. A missing period counts as 0 (the engine's default); a value
  that cannot be read makes the figure unknown.
- **Exceptions**: material-months with inventory below the minimum target
  (Line 04 < Line 05, only materials that have a target row) and with
  negative inventory. A count of exceptions, not a service level.
- **Capacity**: Line 10 (utilization per machine, 1.0 = 100 %). Overloaded =
  above 100 %. Machines with unlimited capacity (Config
  MachineUnlimitedCapacity, always 1.0 in the engine) are left out of the
  ranking. Planned hours on a machine with zero available capacity are
  counted separately: the engine reports utilization 0 there.
- **FTE**: Line 12 (the VBA FTE), summed per month, averaged over the horizon.

The horizon is the one a scenario recorded when it was saved; it is inferred
from the rows only for scenarios saved before that was recorded. Deltas are
computed only when a column has the same horizon as the base.

Labels are Dutch: they are UI copy.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from modules.models import LineType
from modules.numeric import finite_float as _num

LT_DEMAND_FORECAST = LineType.DEMAND_FORECAST.value
LT_TOTAL_DEMAND = LineType.TOTAL_DEMAND.value
LT_INVENTORY = LineType.INVENTORY.value
LT_MIN_TARGET = LineType.MIN_TARGET_STOCK.value
LT_PRODUCTION = LineType.PRODUCTION_PLAN.value
LT_PURCHASE_RECEIPT = LineType.PURCHASE_RECEIPT.value
LT_CAPACITY_UTILIZATION = LineType.CAPACITY_UTILIZATION.value
LT_AVAILABLE_CAPACITY = LineType.AVAILABLE_CAPACITY.value
LT_UTILIZATION = LineType.UTILIZATION_RATE.value
LT_FTE = LineType.FTE_REQUIREMENTS.value
LT_CONSOLIDATION = LineType.CONSOLIDATION.value

# (key, consolidation row, label, unit, direction). Direction: +1 higher is
# better, -1 lower is better, 0 neutral (higher is not better or worse as such).
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

# What the comparison shows by default; the rest is behind 'meer cijfers'.
HEADLINE_KPIS = ['ebit', 'operational_cashflow', 'inventory_value', 'ending_inventory',
                 'stock_negative', 'overloaded_machine_months', 'no_capacity_months']

OTHER_KPIS = [
    ('total_demand', 'Totale vraag', 't', 0),
    ('production', 'Productie', 't', 0),
    ('purchase_receipts', 'Inkoopontvangsten', 't', 0),
    ('ending_inventory', 'Eindvoorraad', 't', 0),
    ('below_target', 'Maanden onder minimumdoel', 'materiaal-maanden', -1),
    ('stock_negative', 'Maanden met negatieve voorraad', 'materiaal-maanden', -1),
    ('overloaded_machine_months', 'Overbelaste machine-maanden (>100 %)', 'machine-maanden', -1),
    ('no_capacity_months', 'Geplande uren zonder capaciteit', 'machine-maanden', -1),
    ('peak_utilization', 'Hoogste benutting', 'ratio', 0),
    ('fte_avg', 'FTE (Line 12, gem. per maand)', 'FTE', 0),
]

KPI_META = {key: {'label': label, 'unit': unit, 'direction': direction}
            for key, _row, label, unit, direction in FINANCIAL_KPIS}
KPI_META.update({key: {'label': label, 'unit': unit, 'direction': direction}
                 for key, label, unit, direction in OTHER_KPIS})
KPI_ORDER = HEADLINE_KPIS + [k for k in KPI_META if k not in HEADLINE_KPIS]


class _Unreadable(Exception):
    """A value that is present but not a finite number."""


def _value(raw) -> float:
    """A cell value: missing is 0 (the engine's default), unreadable raises."""
    if raw is None or raw == '':
        return 0.0
    number = _num(raw)
    if number is None:
        raise _Unreadable(raw)
    return number


def _rows(snapshot: dict, line_type: str) -> List[dict]:
    return [r for r in (snapshot.get(line_type) or []) if isinstance(r, dict)]


def snapshot_periods(results: dict) -> List[str]:
    """The horizon of a snapshot that did not record one: the union of the
    period keys of its demand rows (a sparse first row must not shorten it)."""
    for line_type in (LT_DEMAND_FORECAST, LT_TOTAL_DEMAND, LT_INVENTORY):
        keys = set()
        for row in _rows(results, line_type):
            keys.update(str(p) for p in (row.get('values') or {}))
        if keys:
            return sorted(keys)
    return []


def _valid_periods(periods) -> Optional[List[str]]:
    if isinstance(periods, list) and periods and all(isinstance(p, str) and p for p in periods):
        return list(periods)
    return None


def _sum_rows(rows: Iterable[dict], periods: List[str]) -> Optional[float]:
    try:
        return sum(_value((row.get('values') or {}).get(p)) for row in rows for p in periods)
    except _Unreadable:
        return None


def _consolidation(value_results: dict) -> Dict[str, dict]:
    return {str(r.get('material_number')): r for r in _rows(value_results, LT_CONSOLIDATION)}


def compute_kpis(results: dict, value_results: dict, unlimited_machines=(), periods=None) -> dict:
    """Key figures, the EBIT series and exception lists of one snapshot.
    ``unlimited_machines``: machine codes with unlimited capacity.
    ``periods``: the recorded horizon; inferred from the rows when absent."""
    unlimited_codes = {str(m).strip().upper() for m in (unlimited_machines or ())}
    periods = _valid_periods(periods) or snapshot_periods(results)
    consol = _consolidation(value_results or {})
    kpis: Dict[str, Optional[float]] = {}
    series: Dict[str, Dict[str, Optional[float]]] = {}

    for key, row_name, _label, _unit, _direction in FINANCIAL_KPIS:
        row = consol.get(row_name)
        if row is None:
            kpis[key] = None
            continue
        try:
            kpis[key] = _value(row.get('aux_2_column'))
        except _Unreadable:
            kpis[key] = None
        if key == 'ebit':  # the only series the comparison charts
            series[key] = {p: _num((row.get('values') or {}).get(p)) for p in periods}

    kpis['total_demand'] = _sum_rows(_rows(results, LT_TOTAL_DEMAND), periods)
    kpis['production'] = _sum_rows(_rows(results, LT_PRODUCTION), periods)
    kpis['purchase_receipts'] = _sum_rows(_rows(results, LT_PURCHASE_RECEIPT), periods)
    kpis['ending_inventory'] = _sum_rows(_rows(results, LT_INVENTORY), periods[-1:]) if periods else None

    targets = {str(row.get('material_number')): row.get('values') or {}
               for row in _rows(results, LT_MIN_TARGET)}
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
        present = {p: v for p, v in values.items() if v is not None}
        machine = str(row.get('material_name') or row.get('material_number'))
        if not present or machine.strip().upper() in unlimited_codes:
            continue
        for p, v in present.items():
            if v > 1.0 + 1e-9:
                overloaded.append({'machine': machine, 'group': row.get('product_family') or '',
                                   'period': p, 'utilization': v})
        peak_period = max(present, key=present.get)
        peaks.append({'machine': machine, 'group': row.get('product_family') or '',
                      'period': peak_period, 'utilization': present[peak_period]})
    peaks.sort(key=lambda item: (-item['utilization'], item['machine']))
    kpis['overloaded_machine_months'] = float(len(overloaded))
    kpis['peak_utilization'] = peaks[0]['utilization'] if peaks else None

    # Planned hours on a machine with no available capacity (Line 09 = 0). The
    # engine sets utilization to 0 there (no division by zero), so such a month
    # looks quiet in Line 10; this count makes it visible.
    machine_hours = {str(r.get('material_number')): r.get('values') or {}
                     for r in _rows(results, LT_CAPACITY_UTILIZATION)
                     if r.get('product_type') == 'Machine'}
    no_capacity = []
    for row in _rows(results, LT_AVAILABLE_CAPACITY):
        machine_id = str(row.get('material_number'))
        machine = str(row.get('material_name') or machine_id)
        if machine.strip().upper() in unlimited_codes:
            continue
        hours = machine_hours.get(machine_id) or {}
        for p in periods:
            available = _num((row.get('values') or {}).get(p))
            planned = _num(hours.get(p)) or 0.0
            if available is not None and available <= 0 and planned > 1e-9:
                no_capacity.append({'machine': machine, 'group': row.get('product_family') or '',
                                    'period': p, 'hours': planned})
    no_capacity.sort(key=lambda item: (-item['hours'], item['machine'], item['period']))
    kpis['no_capacity_months'] = float(len(no_capacity))

    fte_rows = _rows(results, LT_FTE)
    try:
        monthly_fte = [sum(_value((r.get('values') or {}).get(p)) for r in fte_rows) for p in periods]
        kpis['fte_avg'] = sum(monthly_fte) / len(periods) if periods else None
    except _Unreadable:
        kpis['fte_avg'] = None

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
            'no_capacity': no_capacity[:50],
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
    """Which saved inputs of this scenario differ from those of the base
    (Dutch: shown in the UI)."""
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
    """``columns``: scenario dicts (results, value_results, name, ...). The
    first is the base. Deltas only for columns with the base's horizon."""
    computed = []
    for column in columns:
        data = compute_kpis(column.get('results') or {}, column.get('value_results') or {},
                            column.get('unlimited_machines') or (), column.get('periods'))
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
            # Known = the scenario recorded the master-data version it was
            # calculated on. The UI says so when it differs from the base.
            'master_version_known': column.get('master_version') is not None,
            'master_version_differs': (index > 0 and column.get('master_version') is not None
                                       and base_column.get('master_version') is not None
                                       and column.get('master_version') != base_column.get('master_version')),
            'unlimited_assumed': bool(column.get('unlimited_assumed')),
            'horizon_recorded': _valid_periods(column.get('periods')) is not None,
            'input_changes': input_changes(column, base_column) if index > 0 else [],
            **data,
            'deltas': deltas,
        })
    return {'columns': out, 'kpi_meta': KPI_META, 'kpi_order': KPI_ORDER, 'headline': HEADLINE_KPIS}
