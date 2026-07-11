"""Pure helpers that scope read-endpoint aggregates to a material group.

Scoping is a VIEW concern: these functions only filter/re-sum existing engine
rows — no engine state is touched and no numeric formula is re-implemented.
When no group is active the read endpoints never call into this module, so
their unscoped payloads stay byte-identical (golden parity).

Honesty rules (see docs/implementatieplan-sibelco.md):
- Only per-material sums are scoped. Fixed company costs (overhead, SG&A,
  D&A, indirect FTE, NBV) and everything derived from them (COGS, marges,
  EBIT(DA), kapitaal, kasstroom, ROCE) are OMITTED, not approximated.
- The scoped P&L view carries a BIJDRAGEMARGE (groepsomzet − grondstofkost −
  machinekost) explicitly labeled "excl. vaste kosten".
- Machine capacity is a machine property: scoped utilization is the group's
  SHARE of the existing utilization (ratio of hours), never a re-derivation.
"""

from typing import Dict, Iterable, List, Optional, Tuple

from modules.models import LineType

# Consolidation metrics deliberately omitted from the scoped financial block.
SCOPED_OMITTED_METRICS = (
    'COST OF GOODS', 'GROSS MARGIN', 'EBITDA', 'EBIT', 'ROCE',
    'DIRECT FTE COST', 'INDIRECT FTE COST', 'OVERHEAD COST', 'SG&A COST',
    'D&A COST', 'FIXED ASSETS NET BOOK VALUE', 'CAPITAL INVESTMENT',
    'OPERATIONAL CASHFLOW',
)


def resolve_active_group(sess) -> Optional[dict]:
    """The session's active group dict, or None (also when the id is stale)."""
    if not sess:
        return None
    gid = sess.get('active_material_group')
    if not gid:
        return None
    return (sess.get('material_groups') or {}).get(gid)


def group_material_set(group: dict, data) -> Tuple[set, int]:
    """(set of the group's material numbers, count unknown to the workbook)."""
    materials = {str(m) for m in (group.get('materials') or [])}
    known = set(getattr(data, 'materials', {}) or {})
    missing = sum(1 for m in materials if m not in known) if known else 0
    return materials, missing


def scoped_marker(group: dict, data) -> dict:
    materials, missing = group_material_set(group, data)
    return {
        'group_id': group.get('id'),
        'name': group.get('name', ''),
        'materials': len(materials),
        'missing': missing,
        'fte_scopable': False,
        'omitted': list(SCOPED_OMITTED_METRICS),
    }


def scope_trend(rows: Iterable, materials: set, periods: List[str]) -> Dict[str, float]:
    """Sum row values per period over the group's rows — same accumulate-and-
    round(1) semantics as the unscoped trends in ui/routes/read.py."""
    trend: Dict[str, float] = {}
    for row in rows:
        if str(row.material_number) not in materials:
            continue
        for period in periods:
            trend[period] = round(trend.get(period, 0.0) + row.values.get(period, 0.0), 1)
    return trend


def material_l07_hours_by_machine(l07_rows: Iterable, materials: Optional[set],
                                  periods: List[str]) -> Dict[str, Dict[str, float]]:
    """Raw (pre-OEE) machine hours per machine from MATERIAL-level L07 rows.

    Material rows carry aux_column = work center and values = raw hours;
    machine/group aggregation rows (product_type 'Machine'/'Machine Group')
    are skipped. ``materials=None`` sums every material (the full total —
    equals the engine's machine_hours_used thanks to the packaged-material
    dedup keeping rows and totals in sync).
    """
    hours: Dict[str, Dict[str, float]] = {}
    for row in l07_rows:
        if row.product_type in ('Machine', 'Machine Group'):
            continue
        wc = row.aux_column
        if not wc:
            continue
        if materials is not None and str(row.material_number) not in materials:
            continue
        bucket = hours.setdefault(wc, {p: 0.0 for p in periods})
        for period in periods:
            bucket[period] += row.values.get(period, 0.0)
    return hours


def scale_utilization(full_util: Dict[str, float],
                      group_hours: Dict[str, float],
                      full_hours: Dict[str, float]) -> Dict[str, float]:
    """Group share of the plotted utilization: full_util × (group/full hours).

    Utilization is linear in hours (uren / capaciteit), so the ratio is exact
    and guarantees share ≤ full utilization; 0 when the machine has no hours.
    """
    out = {}
    for period, util in full_util.items():
        total = full_hours.get(period, 0.0)
        share = (group_hours.get(period, 0.0) / total) if abs(total) > 1e-12 else 0.0
        out[period] = round(util * share, 1)
    return out


def scope_inventory_quality(per_material: List[dict], materials: set
                            ) -> Tuple[List[dict], List[dict], float]:
    """(scoped per_material, scoped top-10, scoped total overstock) — same
    ordering/rounding rules as InventoryQualityEngine.calculate()."""
    scoped = [m for m in per_material if str(m.get('material_number')) in materials]
    top_10 = sorted(scoped, key=lambda m: m.get('starting_overstock', 0.0),
                    reverse=True)[:10]
    total = round(sum(m.get('total_overstock', 0.0) for m in scoped), 2)
    return scoped, top_10, total


def _sum_value_rows(rows: Iterable, materials: set, periods: List[str]
                    ) -> Dict[str, float]:
    totals = {p: 0.0 for p in periods}
    for row in rows:
        if str(row.material_number) not in materials:
            continue
        for period in periods:
            totals[period] += row.values.get(period, 0.0)
    return totals


def scoped_financials(engine, materials: set, periods: List[str]) -> Dict[str, Dict]:
    """The honest scoped P&L block (see module docstring).

    All ingredients are existing per-material value rows; machine cost uses
    the value-L07 rate (aux_column, incl. any aux override) applied to the
    group's raw hours / OEE — the same formula shape the full machine cost
    row was built with.
    """
    value_results = getattr(engine, 'value_results', {}) or {}
    turnover = _sum_value_rows(
        value_results.get(LineType.DEMAND_FORECAST.value, []), materials, periods)
    raw_material = _sum_value_rows(
        value_results.get(LineType.TOTAL_DEMAND.value, []), materials, periods)
    purchase_cost = _sum_value_rows(
        value_results.get(LineType.PURCHASE_RECEIPT.value, []), materials, periods)

    # Machine cost: group raw hours per machine (material-level planning L07)
    # × the machine's value rate. Machines without a cost row contribute 0 —
    # identical to the unscoped machine-cost consolidation.
    l07_planning = (getattr(engine, 'results', {}) or {}).get(
        LineType.CAPACITY_UTILIZATION.value, [])
    group_hours = material_l07_hours_by_machine(l07_planning, materials, periods)
    machine_cost = {p: 0.0 for p in periods}
    machines = getattr(getattr(engine, 'data', None), 'machines', {}) or {}
    for value_row in value_results.get(LineType.CAPACITY_UTILIZATION.value, []):
        mc_code = value_row.material_name
        machine = machines.get(mc_code)
        if machine is None or mc_code not in group_hours:
            continue
        try:
            rate = float(value_row.aux_column)
        except (TypeError, ValueError):
            continue
        oee = machine.oee if machine.oee > 0 else 1.0
        for period in periods:
            hours = group_hours[mc_code].get(period, 0.0)
            machine_cost[period] += (hours / oee) * rate

    inventory_rows = [
        r for r in value_results.get(LineType.INVENTORY.value, [])
        if str(r.material_number) in materials
    ]
    inventory = {p: sum(r.values.get(p, 0.0) for r in inventory_rows) for p in periods}
    inventory_starting = sum(r.starting_stock for r in inventory_rows)

    vp = getattr(getattr(engine, 'data', None), 'valuation_params', None)
    dso = getattr(vp, 'days_sales_outstanding', 0.0) or 0.0
    dpo = getattr(vp, 'days_payable_outstanding', 0.0) or 0.0

    receivables = {p: turnover[p] * dso / 30.0 for p in periods}
    payables = {p: purchase_cost[p] * dpo / 30.0 for p in periods}
    working_capital = {p: receivables[p] + inventory[p] - payables[p] for p in periods}
    bijdragemarge = {p: turnover[p] - raw_material[p] - machine_cost[p] for p in periods}

    def _rounded(series: Dict[str, float]) -> Dict[str, float]:
        return {p: round(v, 0) for p, v in series.items()}

    financials = {
        'TURNOVER': _rounded(turnover),
        'RAW MATERIAL COST': _rounded(raw_material),
        'MACHINE COST': _rounded(machine_cost),
        'BIJDRAGEMARGE': _rounded(bijdragemarge),
        'INVENTORY VALUE': _rounded(inventory),
        'RECEIVABLES': _rounded(receivables),
        'PAYABLES': _rounded(payables),
        'WORKING CAPITAL REQUIREMENTS': _rounded(working_capital),
    }
    financials['INVENTORY VALUE']['Starting stock'] = round(inventory_starting, 0)
    return financials
