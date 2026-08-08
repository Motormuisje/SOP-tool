"""
S&OP Planning Engine - FTE engine (F2-CF, capacity & FTE workbench).

Additive by design. This engine reads the FINISHED planning results and the
F2-CF master data and produces its own result set; it emits no PlanningRow
into ``PlanningEngine.results`` and changes no existing line. Line 12 keeps
reproducing the VBA exactly — the golden test stays byte-identical.

What it adds on top of Line 12:

- staffing norms per group/machine instead of the single ``fte_requirements``
  coefficient in the material master (Line 12's coefficient stays the
  fallback, so a site without norms still gets the numbers it had);
- indirect labour with an explicit driver (control room, truck handling,
  maintenance) instead of the two hard-coded VBA cases;
- machine combinations: machines sharing one operator pool, with a throughput
  effect;
- master-data throughput overrides per machine × product, and MES/PEER
  benchmarks beside the norm;
- labour cost per function group, and occupancy against available shift hours.

Reading from the planning ROWS (not from CapacityEngine's internals) is
deliberate: the web UI edits and overrides live in those rows, so the
workbench follows every cell edit without a second override mechanism.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from modules.models import (
    FTE_PARAM_DEFAULTS,
    IndirectActivity,
    LineType,
    MachineCombination,
    StaffingNorm,
)

# Categories of an FteLine. Only 'group' and 'indirect' add up to the site
# total; 'machine' rows are the detail behind a group and would double-count
# (a mill group aggregates its machines with MAX, not SUM).
CATEGORY_MACHINE = 'machine'
CATEGORY_GROUP = 'group'
CATEGORY_INDIRECT = 'indirect'

# The control-room material, treated specially by CapacityEngine (no 1.0
# fallback on its FTE coefficient) and therefore here too.
CONTROL_ROOM_MATERIAL = 'ZZZZZ_CONTROLROOM'

DRIVER_FIXED = 'fixed'
DRIVER_PER_TON = 'per_ton'
DRIVER_PER_TRUCK = 'per_truck'
DRIVER_PER_MACHINE = 'per_machine'


def _zeros(periods: Iterable[str]) -> Dict[str, float]:
    return dict.fromkeys(periods, 0.0)


def _label(*candidates) -> str:
    """First usable label. Empty material-master name cells arrive from pandas
    as the STRING 'nan', which would otherwise end up on screen as a row
    called "nan" — worse than showing the bare code."""
    for candidate in candidates:
        text = str(candidate or '').strip()
        if text and text.lower() != 'nan':
            return text
    return ''


@dataclass
class FteLine:
    """One row of the workbench: a machine, a group, or an indirect activity."""
    key: str
    label: str
    category: str
    machine_group: str = ''
    function_group: str = ''
    operators_per_hour: float = 0.0
    operators_source: str = ''       # 'staffing_norms' | 'line12_coefficient' | 'combination'
    combination_id: str = ''
    hours: Dict[str, float] = field(default_factory=dict)
    # De machineBELASTING achter deze regel. Gelijk aan `hours`, behalve bij
    # een groep waarvan een combinatie machines overneemt: `hours` daalt dan
    # (die bemensing zit in de combinatieregel) maar de machines draaien even
    # hard door. De bezetting hoort naar dit getal te kijken, anders zakt de
    # KPI zodra je operators combineert.
    load_hours: Dict[str, float] = field(default_factory=dict)
    available_hours: Dict[str, float] = field(default_factory=dict)
    fte: Dict[str, float] = field(default_factory=dict)
    cost: Dict[str, float] = field(default_factory=dict)
    # Effective throughput shown beside the norm; empty when no product-level
    # information is available for this row.
    throughput_norm: Optional[float] = None
    throughput_mes: Optional[float] = None
    throughput_peer: Optional[float] = None
    throughput_source: str = ''
    counts_in_total: bool = True
    # Draagt deze regel een ploegvenster bij aan de bezettings-KPI? Een
    # combinatieregel niet: haar machines brengen hun venster al via hun
    # groep in.
    counts_window: bool = True

    def utilization(self, period: str) -> float:
        available = self.available_hours.get(period, 0.0)
        if available <= 0:
            return 0.0
        load = self.load_hours or self.hours
        return load.get(period, 0.0) / available

    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'label': self.label,
            'category': self.category,
            'machine_group': self.machine_group,
            'function_group': self.function_group,
            'operators_per_hour': self.operators_per_hour,
            'operators_source': self.operators_source,
            'combination_id': self.combination_id,
            'hours': self.hours,
            'load_hours': self.load_hours or self.hours,
            'available_hours': self.available_hours,
            'fte': self.fte,
            'cost': self.cost,
            'utilization': {p: self.utilization(p) for p in self.hours},
            'throughput_norm': self.throughput_norm,
            'throughput_mes': self.throughput_mes,
            'throughput_peer': self.throughput_peer,
            'throughput_source': self.throughput_source,
            'counts_in_total': self.counts_in_total,
            'counts_window': self.counts_window,
        }


@dataclass
class ValueImpact:
    """What the workbench's staffing does to the value chain.

    The 20 VBA consolidation rows are golden-tested and stay untouched. This
    is the SAME arithmetic applied once more with one substitution: the
    workbench's labour cost replaces the direct-FTE cost that consolidation
    row 4 carries. Everything downstream (COGS → margin → EBITDA → EBIT →
    cashflow → ROCE) moves by exactly that delta, so the comparison is
    like-for-like instead of a second, differently-built P&L.
    """
    baseline_labor_cost: Dict[str, float] = field(default_factory=dict)
    workbench_labor_cost: Dict[str, float] = field(default_factory=dict)
    delta: Dict[str, float] = field(default_factory=dict)
    cost_of_goods: Dict[str, float] = field(default_factory=dict)
    gross_margin: Dict[str, float] = field(default_factory=dict)
    ebitda: Dict[str, float] = field(default_factory=dict)
    ebit: Dict[str, float] = field(default_factory=dict)
    operational_cashflow: Dict[str, float] = field(default_factory=dict)
    roce: Dict[str, float] = field(default_factory=dict)
    baseline: Dict[str, Dict[str, float]] = field(default_factory=dict)
    available: bool = False

    def to_dict(self) -> dict:
        return {
            'available': self.available,
            'baseline_labor_cost': self.baseline_labor_cost,
            'workbench_labor_cost': self.workbench_labor_cost,
            'delta': self.delta,
            'cost_of_goods': self.cost_of_goods,
            'gross_margin': self.gross_margin,
            'ebitda': self.ebitda,
            'ebit': self.ebit,
            'operational_cashflow': self.operational_cashflow,
            'roce': self.roce,
            'baseline': self.baseline,
        }


# Consolidation rows the value impact re-derives from.
_CONSOL_DIRECT_FTE = 'ZZZZZZ_DIRECT FTE COST'
_CONSOL_COGS = 'ZZZZZZ_COST OF GOODS'
_CONSOL_GROSS_MARGIN = 'ZZZZZZ_GROSS MARGIN'
_CONSOL_EBITDA = 'ZZZZZZ_EBITDA'
_CONSOL_EBIT = 'ZZZZZZ_EBIT'
_CONSOL_OCF = 'ZZZZZZ_OPERATIONAL CASHFLOW'
_CONSOL_CAPITAL = 'ZZZZZZ_CAPITAL INVESTMENT'


@dataclass
class FteResult:
    periods: List[str] = field(default_factory=list)
    lines: List[FteLine] = field(default_factory=list)
    total_fte: Dict[str, float] = field(default_factory=dict)
    total_direct_fte: Dict[str, float] = field(default_factory=dict)
    total_indirect_fte: Dict[str, float] = field(default_factory=dict)
    total_cost: Dict[str, float] = field(default_factory=dict)
    total_hours: Dict[str, float] = field(default_factory=dict)
    total_available_hours: Dict[str, float] = field(default_factory=dict)
    # Uren van UITSLUITEND de regels die een beschikbaarheidsvenster hebben.
    # De bezettings-KPI deelt hierdoor teller door noemer over dezelfde
    # regels; met total_hours in de teller telden indirecte activiteiten,
    # trucks en de controlekamer mee terwijl ze geen venster hebben — en
    # rapporteerde de werkbank 119% bezetting op machines die op 19% liepen.
    total_capacity_hours: Dict[str, float] = field(default_factory=dict)
    total_volume: Dict[str, float] = field(default_factory=dict)
    fte_hours_per_year: float = 0.0
    utilization_rate: float = 1.0
    derived_fte_hours_per_year: float = 0.0
    active_combinations: List[str] = field(default_factory=list)
    value_impact: ValueImpact = field(default_factory=ValueImpact)
    warnings: List[str] = field(default_factory=list)

    def utilization(self, period: str) -> float:
        available = self.total_available_hours.get(period, 0.0)
        return (self.total_capacity_hours.get(period, 0.0) / available
                if available > 0 else 0.0)

    def staffed_fte(self, period: str) -> float:
        """Required FTE grossed up to the planned occupancy (the 85%)."""
        rate = self.utilization_rate or 1.0
        return self.total_fte.get(period, 0.0) / rate if rate > 0 else 0.0

    def tons_per_fte(self, period: str) -> float:
        fte = self.total_fte.get(period, 0.0)
        return self.total_volume.get(period, 0.0) / fte if fte > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            'periods': self.periods,
            'lines': [line.to_dict() for line in self.lines],
            'totals': {
                'fte': self.total_fte,
                'direct_fte': self.total_direct_fte,
                'indirect_fte': self.total_indirect_fte,
                'cost': self.total_cost,
                'hours': self.total_hours,
                'available_hours': self.total_available_hours,
                'capacity_hours': self.total_capacity_hours,
                'volume': self.total_volume,
                'utilization': {p: self.utilization(p) for p in self.periods},
                'staffed_fte': {p: self.staffed_fte(p) for p in self.periods},
                'tons_per_fte': {p: self.tons_per_fte(p) for p in self.periods},
            },
            'fte_hours_per_year': self.fte_hours_per_year,
            'utilization_rate': self.utilization_rate,
            'derived_fte_hours_per_year': self.derived_fte_hours_per_year,
            'active_combinations': self.active_combinations,
            'value_impact': self.value_impact.to_dict(),
            'warnings': self.warnings,
        }


class FteEngine:
    """Capacity → FTE → labour cost, on top of finished planning results."""

    def __init__(self, data, planning_results: Dict[str, List],
                 active_combinations: Optional[Iterable[str]] = None,
                 value_results: Optional[Dict[str, List]] = None,
                 staffing_norm_overrides: Optional[Dict[str, dict]] = None):
        self.data = data
        self.results = planning_results or {}
        self.value_results = value_results or {}
        self.periods: List[str] = list(getattr(data, 'periods', []) or [])
        self.warnings: List[str] = []

        self.fte_hours_per_year = float(getattr(data, 'fte_hours_per_year', 0.0) or 0.0)
        self.fte_monthly_hours = self.fte_hours_per_year / 12 if self.fte_hours_per_year else 0.0
        params = dict(FTE_PARAM_DEFAULTS)
        params.update(getattr(data, 'fte_params', None) or {})
        self.params = params
        self.utilization_rate = float(params.get('utilization_rate') or 1.0) or 1.0

        self.staffing_norms: Dict[str, StaffingNorm] = getattr(data, 'staffing_norms', None) or {}
        # Sessie-wat-als op de bemensingsnormen: rekent DIRECT mee zonder de
        # masterdata te raken. Een override ligt als kopie over de norm heen
        # (functiegroep/omschrijving van een bestaande norm blijven staan) en
        # de regel draagt bron 'wat-als', zodat altijd zichtbaar is dat dit
        # een experiment is en geen vastgelegde norm.
        self._overridden_norms: Set[str] = set()
        overrides = staffing_norm_overrides or {}
        if overrides:
            merged = dict(self.staffing_norms)
            for code, spec in overrides.items():
                if not isinstance(spec, dict):
                    continue
                try:
                    operators = float(spec.get('operators_per_hour'))
                except (TypeError, ValueError):
                    self.warnings.append(
                        f'Wat-als-norm voor "{code}" heeft geen geldig getal en is genegeerd.')
                    continue
                if operators < 0:
                    self.warnings.append(
                        f'Wat-als-norm voor "{code}" is negatief en is genegeerd.')
                    continue
                base = merged.get(str(code))
                scope = str(spec.get('scope') or (base.scope if base is not None else 'group'))
                merged[str(code)] = StaffingNorm(
                    code=str(code), operators_per_hour=operators, scope=scope,
                    function_group=(base.function_group if base is not None else ''),
                    description=(base.description if base is not None else ''))
                self._overridden_norms.add(str(code))
            self.staffing_norms = merged
        self.labor_rates = getattr(data, 'labor_rates', None) or {}
        self.indirect_activities: Dict[str, IndirectActivity] = \
            getattr(data, 'indirect_activities', None) or {}
        self.throughput_overrides = getattr(data, 'throughput_overrides', None) or {}
        self.benchmarks = getattr(data, 'benchmark_throughput', None) or {}
        self._mill_cache: Optional[Set[str]] = None
        self._compound_cache: Optional[Dict[str, List[str]]] = None
        combos: Dict[str, MachineCombination] = getattr(data, 'machine_combinations', None) or {}
        requested = set(active_combinations or [])
        self.active_combinations: Dict[str, MachineCombination] = {
            cid: combo for cid, combo in combos.items()
            if cid in requested and combo.is_active}
        for cid in sorted(requested - set(self.active_combinations)):
            self.warnings.append(
                f'Combinatie "{cid}" is niet (meer) beschikbaar in de masterdata '
                f'en is genegeerd.')
        self._drop_overlapping_combinations()

    def _drop_overlapping_combinations(self) -> None:
        """Eén machine kan maar door één operatorpool bemenst worden.

        Staan er twee combinaties aan die dezelfde machine claimen, dan pakte
        _combination_of willekeurig de eerste voor de doorzetfactor terwijl
        BEIDE combinaties hun operators in rekening brachten — de machine werd
        dubbel bemenst en de factor van de andere combinatie verdween. Dat is
        geen geldige wat-als, dus we zetten de latere uit en zeggen het.
        """
        claimed: Dict[str, str] = {}
        for cid in sorted(self.active_combinations):
            combo = self.active_combinations[cid]
            clash = [(mc, claimed[mc]) for mc in combo.machine_codes if mc in claimed]
            if clash:
                machines = ', '.join(mc for mc, _ in clash)
                owner = clash[0][1]
                self.warnings.append(
                    f'Combinatie "{cid}" is uitgezet: {machines} zit al in '
                    f'combinatie "{owner}". Eén machine kan maar in één actieve '
                    f'combinatie zitten.')
                del self.active_combinations[cid]
                continue
            for mc in combo.machine_codes:
                claimed[mc] = cid

    # ── inputs from the planning rows ───────────────────────────────────────

    def _rows(self, line_type: str) -> List:
        return self.results.get(line_type, []) or []

    def _machine_rows(self) -> Dict[str, object]:
        """Machine-level Line 07 rows, keyed by machine code.

        Line 07 also carries compound 'grouped production line' rows with
        product_type 'Machine' (PML01-PML02-PML03) — an AVERAGE over member
        machines, not a machine. Keying on the known machine codes leaves them
        out; their members are already present individually.
        """
        machines = getattr(self.data, 'machines', None) or {}
        out = {}
        for row in self._rows(LineType.CAPACITY_UTILIZATION.value):
            if row.product_type == 'Machine' and row.material_name in machines:
                out[row.material_name] = row
        return out

    def _group_rows(self) -> Dict[str, object]:
        out = {}
        for row in self._rows(LineType.CAPACITY_UTILIZATION.value):
            if row.product_type == 'Machine Group':
                out[row.material_number] = row
        return out

    def _shift_hours_by_group(self) -> Dict[str, Dict[str, float]]:
        out = {}
        for row in self._rows(LineType.SHIFT_AVAILABILITY.value):
            out[row.material_number] = dict(row.values)
        return out

    def _material_rows_by_machine(self) -> Dict[str, List]:
        """Line 07 material rows grouped by work center.

        These carry AUX2 = base throughput (units per hour), which is what a
        master-data throughput override replaces.
        """
        out: Dict[str, List] = {}
        for row in self._rows(LineType.CAPACITY_UTILIZATION.value):
            if row.product_type in ('Machine', 'Machine Group') or not row.aux_column:
                continue
            out.setdefault(row.aux_column, []).append(row)
        return out

    # ── throughput overrides ────────────────────────────────────────────────

    def _throughput_delta(self, machine_code: str, material_rows: List) -> Dict[str, float]:
        """Extra (or saved) machine hours caused by throughput overrides.

        Hours scale inversely with throughput: half the tonnes per hour is
        twice the hours. Expressed as a DELTA on the machine row so that a
        user override on that row (a cell edit in the UI) keeps winning for
        everything the master data does not override.
        """
        machine = (getattr(self.data, 'machines', None) or {}).get(machine_code)
        oee = float(getattr(machine, 'oee', 0.0) or 0.0)
        delta = _zeros(self.periods)
        for row in material_rows:
            override = self.throughput_overrides.get(f'{machine_code}|{row.material_number}')
            if override is None:
                continue
            new_tp = float(override.throughput_t_per_hour or 0.0)
            if new_tp <= 0:
                self.warnings.append(
                    f'Doorzet-override {machine_code}/{row.material_number} is 0 of '
                    f'negatief en is genegeerd.')
                continue
            try:
                base_tp = float(row.aux_2_column)
            except (TypeError, ValueError):
                base_tp = 0.0
            if base_tp <= 0:
                self.warnings.append(
                    f'Doorzet-override {machine_code}/{row.material_number}: de '
                    f'basisdoorzet ontbreekt in de planning, override genegeerd.')
                continue
            factor = base_tp / new_tp - 1.0
            for period in self.periods:
                extra = row.values.get(period, 0.0) * factor
                delta[period] += extra / oee if oee > 0 else extra
        return delta

    # ── staffing norms ──────────────────────────────────────────────────────

    def _norm_for(self, code: str, scope: str):
        norm = self.staffing_norms.get(code)
        if norm is not None and norm.scope == scope:
            return norm
        return None

    def _group_operators(self, group_id: str) -> tuple:
        """(operators per running hour, provenance) for a machine group.

        Falls back to the material master's ``fte_requirements`` — the Line 12
        coefficient — so a site that has not entered staffing norms yet sees
        exactly the FTE it saw before, instead of a table full of zeros.

        The 1.0 fallback mirrors CapacityEngine._calculate_fte_requirements and
        _calculate_truck_fte, which use it for groups and trucks. The control
        room is the one place where VBA does NOT fall back
        (_calculate_control_room_fte: "fte_requirements == 0 means this site's
        control room needs no FTE"), so neither do we — otherwise a site that
        needs no control-room crew would see 4,18 FTE and the labour cost that
        comes with it appear out of nowhere, and Line 12 parity would break.
        """
        norm = self._norm_for(group_id, CATEGORY_GROUP)
        if norm is not None:
            source = 'wat-als' if group_id in self._overridden_norms else 'staffing_norms'
            return float(norm.operators_per_hour), source
        material = (getattr(self.data, 'materials', None) or {}).get(group_id)
        coefficient = float(getattr(material, 'fte_requirements', 0.0) or 0.0)
        if coefficient > 0:
            return coefficient, 'line12_coefficient'
        if group_id == CONTROL_ROOM_MATERIAL:
            return 0.0, 'line12_coefficient'
        return 1.0, 'default'

    def _machine_operators(self, machine_code: str, group_id: str) -> tuple:
        norm = self._norm_for(machine_code, CATEGORY_MACHINE)
        if norm is not None:
            source = 'wat-als' if machine_code in self._overridden_norms else 'staffing_norms'
            return float(norm.operators_per_hour), source
        return self._group_operators(group_id)

    # ── combinations ────────────────────────────────────────────────────────

    def _combination_of(self, machine_code: str) -> Optional[MachineCombination]:
        for combo in self.active_combinations.values():
            if machine_code in combo.machine_codes:
                return combo
        return None

    # ── volume drivers ──────────────────────────────────────────────────────

    def _volume(self, line_type: str, source: str) -> Dict[str, float]:
        """Tonnes per period for a driver, optionally filtered.

        ``source`` matches a material number first, then a product family; an
        empty source is the site total of that line.
        """
        totals = _zeros(self.periods)
        wanted = (source or '').strip()
        rows = self._rows(line_type)
        if wanted:
            matched = [r for r in rows if r.material_number == wanted]
            if not matched:
                matched = [r for r in rows if (r.product_family or '') == wanted]
            if not matched:
                self.warnings.append(
                    f'Volumebron "{wanted}" komt niet voor in "{line_type}"; '
                    f'de betreffende activiteit rekent met 0 ton.')
            rows = matched
        for row in rows:
            for period in self.periods:
                totals[period] += row.values.get(period, 0.0)
        return totals

    def _indirect_line(self, activity: IndirectActivity) -> Optional[FteLine]:
        hours = _zeros(self.periods)
        driver = (activity.driver or '').strip() or DRIVER_FIXED

        if driver == DRIVER_FIXED:
            per_period = float(activity.fte_per_period or 0.0)
            if per_period <= 0:
                per_period = float(activity.fte_per_shift or 0.0) * float(activity.shifts or 0.0)
            fte = dict.fromkeys(self.periods, per_period)
            hours = dict.fromkeys(self.periods, per_period * self.fte_monthly_hours)
        elif driver in (DRIVER_PER_TON, DRIVER_PER_TRUCK):
            line = activity.volume_line or LineType.DEMAND_FORECAST.value
            volume = self._volume(line, activity.volume_source)
            for period in self.periods:
                tons = volume.get(period, 0.0)
                if driver == DRIVER_PER_TRUCK:
                    per_truck = float(activity.tons_per_truck or 0.0)
                    if per_truck <= 0:
                        self.warnings.append(
                            f'Activiteit "{activity.activity_id}": ton per truck is 0, '
                            f'geen truckuren berekend.')
                        break
                    units = tons / per_truck
                else:
                    units = tons
                hours[period] = units * float(activity.hours_per_unit or 0.0)
            fte = {p: (hours[p] / self.fte_monthly_hours if self.fte_monthly_hours > 0 else 0.0)
                   for p in self.periods}
        elif driver == DRIVER_PER_MACHINE:
            per_fte = float(activity.machines_per_fte or 0.0)
            if per_fte <= 0:
                self.warnings.append(
                    f'Activiteit "{activity.activity_id}": machines per FTE is 0, '
                    f'geen onderhouds-FTE berekend.')
                return None
            count = float(activity.machine_count or 0.0)
            if count <= 0:
                count = float(len(getattr(self.data, 'machines', None) or {}))
            value = count / per_fte
            fte = dict.fromkeys(self.periods, value)
            hours = dict.fromkeys(self.periods, value * self.fte_monthly_hours)
        else:
            self.warnings.append(
                f'Activiteit "{activity.activity_id}" heeft een onbekende driver '
                f'"{activity.driver}" en is overgeslagen.')
            return None

        return FteLine(
            key=activity.activity_id,
            label=activity.name or activity.activity_id,
            category=CATEGORY_INDIRECT,
            function_group=activity.function_group,
            hours=hours,
            fte=fte,
            cost=self._cost(fte, activity.function_group),
        )

    # ── cost ────────────────────────────────────────────────────────────────

    def _rate(self, function_group: str) -> float:
        rate = self.labor_rates.get((function_group or '').strip())
        if rate is None:
            rate = self.labor_rates.get('default')
        return float(getattr(rate, 'cost_per_fte_per_year', 0.0) or 0.0)

    def _cost(self, fte: Dict[str, float], function_group: str) -> Dict[str, float]:
        monthly_rate = self._rate(function_group) / 12
        return {p: value * monthly_rate for p, value in fte.items()}

    # ── main ────────────────────────────────────────────────────────────────

    def calculate(self) -> FteResult:
        result = FteResult(
            periods=list(self.periods),
            fte_hours_per_year=self.fte_hours_per_year,
            utilization_rate=self.utilization_rate,
            active_combinations=sorted(self.active_combinations),
        )
        from modules.models import derive_effective_fte_hours
        result.derived_fte_hours_per_year = derive_effective_fte_hours(self.params)

        machine_rows = self._machine_rows()
        shift_hours = self._shift_hours_by_group()
        machines = getattr(self.data, 'machines', None) or {}
        effective_hours = self._effective_machine_hours(machine_rows)

        result.lines.extend(self._machine_lines(effective_hours, machines, shift_hours))
        result.lines.extend(self._group_lines(machine_rows, effective_hours, machines,
                                              shift_hours))
        result.lines.extend(self._combination_lines(effective_hours, machines, shift_hours))
        result.lines.extend(self._indirect_lines())

        self._fill_totals(result)
        result.value_impact = self._value_impact(result)
        result.warnings = list(dict.fromkeys(self.warnings))
        return result

    # ── value chain (Fase B) ────────────────────────────────────────────────

    def _consolidation(self) -> Dict[str, Dict[str, float]]:
        rows = self.value_results.get(LineType.CONSOLIDATION.value, []) or []
        return {row.material_number: dict(row.values) for row in rows}

    def _value_impact(self, result: FteResult) -> ValueImpact:
        """Re-run the consolidation arithmetic with the workbench's labour cost.

        Returns an unavailable impact when there is no consolidation (no
        valuation parameters) — better an empty panel than invented margins.
        """
        consolidation = self._consolidation()
        impact = ValueImpact()
        if _CONSOL_DIRECT_FTE not in consolidation or _CONSOL_COGS not in consolidation:
            return impact

        baseline = consolidation[_CONSOL_DIRECT_FTE]
        workbench = result.total_cost
        if not any(abs(v) > 0 for v in workbench.values()):
            # No labour rates configured: the workbench has no opinion on cost,
            # so showing a 'saving' equal to the whole baseline would be a lie.
            impact.baseline = {k: consolidation[k] for k in consolidation}
            impact.baseline_labor_cost = dict(baseline)
            return impact

        delta = {p: workbench.get(p, 0.0) - baseline.get(p, 0.0) for p in self.periods}
        capital = consolidation.get(_CONSOL_CAPITAL, {})

        def shifted(name, sign):
            source = consolidation.get(name, {})
            return {p: source.get(p, 0.0) + sign * delta[p] for p in self.periods}

        impact.available = True
        impact.baseline = {k: consolidation[k] for k in consolidation}
        impact.baseline_labor_cost = dict(baseline)
        impact.workbench_labor_cost = dict(workbench)
        impact.delta = delta
        impact.cost_of_goods = shifted(_CONSOL_COGS, 1)
        impact.gross_margin = shifted(_CONSOL_GROSS_MARGIN, -1)
        impact.ebitda = shifted(_CONSOL_EBITDA, -1)
        impact.ebit = shifted(_CONSOL_EBIT, -1)
        impact.operational_cashflow = shifted(_CONSOL_OCF, -1)
        impact.roce = {
            p: (impact.ebit[p] * 12 / capital[p]) if capital.get(p) else 0.0
            for p in self.periods}
        return impact

    def _effective_machine_hours(self, machine_rows) -> Dict[str, Dict[str, float]]:
        """Planning-row hours + throughput overrides + combination effect."""
        material_rows = self._material_rows_by_machine()
        effective: Dict[str, Dict[str, float]] = {}
        for machine_code, row in machine_rows.items():
            delta = self._throughput_delta(machine_code, material_rows.get(machine_code, []))
            combo = self._combination_of(machine_code)
            factor = combo.factor_for(machine_code) if combo else 1.0
            if factor <= 0:
                self.warnings.append(
                    f'Combinatie "{combo.combination_id}": doorzetfactor voor '
                    f'{machine_code} is 0 of negatief; factor 1 gebruikt.')
                factor = 1.0
            effective[machine_code] = {
                p: (row.values.get(p, 0.0) + delta.get(p, 0.0)) / factor
                for p in self.periods}
        return effective

    def _fte_from_hours(self, hours: Dict[str, float], operators: float) -> Dict[str, float]:
        if self.fte_monthly_hours <= 0:
            return _zeros(self.periods)
        return {p: hours.get(p, 0.0) * operators / self.fte_monthly_hours
                for p in self.periods}

    def _machine_lines(self, effective_hours, machines, shift_hours) -> List[FteLine]:
        """Per-machine detail. Informational only: the group rows carry the
        total, because a mill group is the MAX of its machines, not the sum."""
        lines = []
        for machine_code in sorted(effective_hours):
            machine = machines.get(machine_code)
            group_id = getattr(machine, 'machine_group', '') or ''
            combo = self._combination_of(machine_code)
            operators, source = self._machine_operators(machine_code, group_id)
            hours = effective_hours[machine_code]
            fte = self._fte_from_hours(hours, operators)
            function_group = self._function_group(machine_code, group_id)
            mes, peer, provenance = self._machine_benchmark(machine_code)
            lines.append(FteLine(
                key=machine_code,
                label=_label(getattr(machine, 'name', ''), machine_code),
                category=CATEGORY_MACHINE,
                machine_group=group_id,
                function_group=function_group,
                operators_per_hour=operators,
                operators_source=source,
                combination_id=combo.combination_id if combo else '',
                hours=hours,
                available_hours=dict(shift_hours.get(group_id, {})) if group_id else {},
                fte=fte,
                cost=self._cost(fte, function_group),
                throughput_mes=mes,
                throughput_peer=peer,
                throughput_source=provenance,
                counts_in_total=False,
            ))
        return lines

    def _group_lines(self, machine_rows, effective_hours, machines,
                     shift_hours) -> List[FteLine]:
        """The authoritative direct FTE.

        Group hours come from the Line 07 group row, which already carries the
        MAX (mills) / SUM (packaging) aggregation and any user override on it.
        Override and combination effects are added as the delta measured on the
        member machines, so the group's aggregation semantics survive.
        """
        materials = getattr(self.data, 'materials', None) or {}
        lines = []
        for group_id, row in sorted(self._group_rows().items()):
            adjustment = self._group_adjustment(group_id, machines, machine_rows,
                                                effective_hours)
            hours = {p: row.values.get(p, 0.0) + adjustment[p] for p in self.periods}
            # Zelfde som, maar ZONDER de machines die een combinatie overneemt:
            # dat is de belasting van de machines zelf.
            load_adjustment = self._group_adjustment(group_id, machines, machine_rows,
                                                     effective_hours,
                                                     exclude_combined=False)
            load = {p: row.values.get(p, 0.0) + load_adjustment[p] for p in self.periods}
            operators, source = self._group_operators(group_id)
            fte = self._fte_from_hours(hours, operators)
            function_group = self._function_group('', group_id)
            lines.append(FteLine(
                key=group_id,
                # Groepsmaterialen dragen vaak geen naam; de bemensingsnorm
                # heeft er wel een omschrijving bij, en die zegt de gebruiker
                # meer dan 'ZZ_GROUP04'.
                label=_label(getattr(materials.get(group_id), 'name', ''),
                             getattr(self.staffing_norms.get(group_id), 'description', ''),
                             group_id),
                category=CATEGORY_GROUP,
                machine_group=group_id,
                function_group=function_group,
                operators_per_hour=operators,
                operators_source=source,
                hours=hours,
                load_hours=load,
                available_hours=dict(shift_hours.get(group_id, {})),
                fte=fte,
                cost=self._cost(fte, function_group),
            ))
        return lines

    def _combination_lines(self, effective_hours, machines, shift_hours) -> List[FteLine]:
        """A combination replaces its members' individual operator demand by
        one shared pool. The members run together, so the pool is needed for
        the LONGEST member — summing would staff the same person twice."""
        lines = []
        for combo in sorted(self.active_combinations.values(), key=lambda c: c.combination_id):
            hours = {p: max((effective_hours.get(mc, {}).get(p, 0.0)
                             for mc in combo.machine_codes), default=0.0)
                     for p in self.periods}
            fte = self._fte_from_hours(hours, float(combo.operators or 0.0))
            # Het ploegvenster van deze machines wordt al door hun GROEPEN
            # ingebracht; hier nog eens meetellen maakte de noemer van de
            # bezettings-KPI groter dan het aantal beschikbare uren dat er
            # werkelijk is. Per regel tonen we het wel (de breedste groep waar
            # de combinatie overheen loopt), maar counts_window houdt het uit
            # het totaal.
            member_groups = {(getattr(machines.get(mc), 'machine_group', '') or '')
                             for mc in combo.machine_codes}
            available = {p: max((shift_hours.get(g, {}).get(p, 0.0)
                                 for g in member_groups if g), default=0.0)
                         for p in self.periods}
            lines.append(FteLine(
                key=combo.combination_id,
                label=combo.name or combo.combination_id,
                category=CATEGORY_GROUP,
                function_group=combo.function_group,
                operators_per_hour=float(combo.operators or 0.0),
                operators_source='combination',
                combination_id=combo.combination_id,
                hours=hours,
                load_hours=_zeros(self.periods),
                available_hours=available,
                counts_window=False,
                fte=fte,
                cost=self._cost(fte, combo.function_group),
            ))
        return lines

    def _indirect_lines(self) -> List[FteLine]:
        lines = []
        for activity_id in sorted(self.indirect_activities):
            activity = self.indirect_activities[activity_id]
            if not activity.is_active:
                continue
            line = self._indirect_line(activity)
            if line is not None:
                lines.append(line)
        return lines

    def _combined_machines(self) -> Set[str]:
        """Machines whose operators come from an active combination."""
        return {mc for combo in self.active_combinations.values()
                for mc in combo.machine_codes}

    def _group_adjustment(self, group_id, machines, machine_rows,
                          effective_hours, exclude_combined: bool = True) -> Dict[str, float]:
        """How much the group's hours move relative to its Line 07 row.

        Two effects, one number:

        1. Throughput overrides and combination throughput factors change what
           each member needs (``effective_hours`` vs the Line 07 machine row).
        2. A member that is staffed by an ACTIVE COMBINATION leaves this group:
           the combination already charges for it, so counting it here too
           would staff the same machine twice. That is not hypothetical —
           without this exclusion, switching on a labour-SAVING combination
           made total FTE go UP.

        Both are expressed against the group's own aggregation — MAX for a mill
        group (the busiest machine sets the group), SUM otherwise — so the
        result stays a delta on the Line 07 row and any user override of that
        row keeps winning.
        """
        base, effective, combined_keys = self._group_aggregation_members(
            group_id, machines, machine_rows, effective_hours)
        if not base:
            return _zeros(self.periods)
        keys = list(base)
        remaining = ([key for key in keys if key not in combined_keys]
                     if exclude_combined else list(keys))
        unchanged = all(
            abs(effective[key].get(p, 0.0) - base[key].get(p, 0.0)) <= 1e-12
            for key in keys for p in self.periods)
        if unchanged and len(remaining) == len(keys):
            return _zeros(self.periods)

        is_mill = group_id in self._mill_groups()

        def aggregate(source, selected, period):
            values = [source[key].get(period, 0.0) for key in selected]
            if not values:
                return 0.0
            return max(values) if is_mill else sum(values)

        adjustment = _zeros(self.periods)
        for period in self.periods:
            adjustment[period] = (aggregate(effective, remaining, period)
                                  - aggregate(base, keys, period))
        return adjustment

    def _group_aggregation_members(self, group_id, machines, machine_rows,
                                   effective_hours):
        """De aggregatie-eenheden van een groep, exact zoals CapacityEngine ze
        opbouwt in ``group_machine_hours``.

        Dat is NIET simpelweg "de machines van de groep": machines van een
        gegroepeerde productielijn worden daar vervangen door één pseudo-lid
        met het GEMIDDELDE van de componenten. Wie ze los meetelt — of ze,
        zoals een eerdere poging, gewoon weglaat — meet de delta tegen een
        andere basis dan de Line 07-rij zelf. Weglaten was aantoonbaar erger:
        een groep die alleen uit compound-machines bestaat hield dan haar
        volledige uren terwijl de combinatie er nog eens bovenop kwam.

        Retourneert (basis, effectief, sleutels die een combinatie bemenst).
        """
        combined_machines = self._combined_machines()
        base: Dict[str, Dict[str, float]] = {}
        effective: Dict[str, Dict[str, float]] = {}
        combined_keys: Set[str] = set()
        handled: Set[str] = set()

        for line, components in self._compound_lines().items():
            known = [code for code in components if code in machines]
            handled.update(known)
            if not known:
                continue
            owner = getattr(machines[known[0]], 'machine_group', '') or ''
            if owner != group_id:
                continue
            key = f'__compound_{line}'

            def _average(source, period, components=components):
                # CapacityEngine deelt door het AANTAL COMPONENTEN, ook als een
                # component onbekend is (die telt als 0). Exact overnemen.
                total = sum((source.get(code) or {}).get(period, 0.0)
                            for code in components)
                return total / len(components) if components else 0.0

            base[key] = {p: _average({c: machine_rows[c].values for c in known
                                      if c in machine_rows}, p)
                         for p in self.periods}
            effective[key] = {p: _average(effective_hours, p) for p in self.periods}
            inside = [code for code in known if code in combined_machines]
            if inside and len(inside) == len(known):
                combined_keys.add(key)
            elif inside:
                self.warnings.append(
                    f'Groep {group_id}: {", ".join(sorted(inside))} zit in een '
                    f'combinatie maar de gegroepeerde productielijn "{line}" '
                    f'draait als geheel; de combinatie is niet uit het '
                    f'groepstotaal gehaald.')

        for code, machine in machines.items():
            if (getattr(machine, 'machine_group', '') or '') != group_id:
                continue
            if code in handled or code not in effective_hours or code not in machine_rows:
                continue
            base[code] = dict(machine_rows[code].values)
            effective[code] = effective_hours[code]
            if code in combined_machines:
                combined_keys.add(code)
        return base, effective, combined_keys

    def _compound_lines(self) -> Dict[str, List[str]]:
        """{lijnnaam: [machinecodes]} van elke gegroepeerde productielijn.

        Zelfde afleiding als CapacityEngine: materialen met
        grouped_production_line == '1' en een production_line als
        'PML01-PML02-PML03'.
        """
        if self._compound_cache is None:
            lines: Dict[str, List[str]] = {}
            for material in (getattr(self.data, 'materials', None) or {}).values():
                if str(getattr(material, 'grouped_production_line', '') or '').strip() != '1':
                    continue
                name = str(getattr(material, 'production_line', '') or '').strip()
                if '-' not in name or name in lines:
                    continue
                lines[name] = [part.strip() for part in name.split('-') if part.strip()]
            self._compound_cache = lines
        return self._compound_cache

    def _mill_groups(self) -> Set[str]:
        if self._mill_cache is None:
            mills = set()
            for number, material in (getattr(self.data, 'materials', None) or {}).items():
                if not number.startswith('ZZ') or number.startswith('ZZZZ'):
                    continue
                if str(getattr(material, 'mill_machine_group', '') or '').strip() == '1':
                    mills.add(number)
            self._mill_cache = mills
        return self._mill_cache

    def _function_group(self, machine_code: str, group_id: str) -> str:
        norm = self._norm_for(machine_code, CATEGORY_MACHINE) if machine_code else None
        if norm is None and group_id:
            norm = self._norm_for(group_id, CATEGORY_GROUP)
        return getattr(norm, 'function_group', '') or ''

    def _machine_benchmark(self, machine_code: str):
        """(MES, PEER, herkomst) for a machine row.

        Prefers the INSTALLATION-level benchmark (the entry without a material
        number) — the source itself provides that total. Otherwise the single
        product entry, if there is exactly one. Never an average across
        products: that would invent a number nobody measured.
        """
        entries = [b for b in self.benchmarks.values() if b.machine_code == machine_code]
        override_sources = {o.source for o in self.throughput_overrides.values()
                            if o.machine_code == machine_code and o.source}
        source = min(override_sources) if len(override_sources) == 1 else ''
        machine_level = [b for b in entries if not b.material_number]
        entry = machine_level[0] if machine_level else (entries[0] if len(entries) == 1 else None)
        if entry is None:
            return None, None, source
        return ((entry.mes_t_per_hour or None), (entry.peer_t_per_hour or None),
                source or ('MES/PEER' if (entry.mes_oee or entry.peer_t_per_hour) else ''))

    def _fill_totals(self, result: FteResult) -> None:
        for bucket in ('total_fte', 'total_direct_fte', 'total_indirect_fte',
                       'total_cost', 'total_hours', 'total_available_hours',
                       'total_capacity_hours'):
            setattr(result, bucket, _zeros(self.periods))
        # No group-level skipping here: _group_adjustment already removes the
        # machines an active combination staffs, member by member. Skipping a
        # whole group instead only worked when a combination covered ALL of it;
        # a combination spanning part of a group (or two groups) then counted
        # its machines twice and made a labour-saving combination raise FTE.
        for line in result.lines:
            if not line.counts_in_total:
                continue
            for period in self.periods:
                result.total_fte[period] += line.fte.get(period, 0.0)
                result.total_cost[period] += line.cost.get(period, 0.0)
                result.total_hours[period] += line.hours.get(period, 0.0)
                available = (line.available_hours.get(period, 0.0)
                             if line.counts_window else 0.0)
                result.total_available_hours[period] += available
                if available > 0:
                    result.total_capacity_hours[period] += (
                        (line.load_hours or line.hours).get(period, 0.0))
                if line.category == CATEGORY_INDIRECT:
                    result.total_indirect_fte[period] += line.fte.get(period, 0.0)
                else:
                    result.total_direct_fte[period] += line.fte.get(period, 0.0)
        result.total_volume = self._volume(LineType.DEMAND_FORECAST.value, '')
