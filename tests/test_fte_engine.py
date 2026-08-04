"""FTE-motor (F2-CF): bemensingsnormen, indirecte activiteiten, combinaties,
doorzet-overrides en de reproductie van het Maastricht-klantmodel.

Synthetische stubs, net als test_capacity_engine — geen golden nodig.
"""

from types import SimpleNamespace

import pytest

from modules.capacity_engine import CapacityEngine
from modules.fte_engine import (
    CATEGORY_GROUP,
    CATEGORY_INDIRECT,
    CATEGORY_MACHINE,
    FteEngine,
)
from modules.models import (
    FTE_PARAM_DEFAULTS,
    IndirectActivity,
    LaborRate,
    LineType,
    Machine,
    MachineCombination,
    MachineGroup,
    Material,
    PlanningRow,
    ProductType,
    ShiftSystem,
    StaffingNorm,
    ThroughputOverride,
)

pytestmark = pytest.mark.no_fixture

PERIODS = ['2025-01', '2025-02', '2025-03']


def _mat(number, **kwargs):
    kwargs.setdefault('name', number)
    kwargs.setdefault('product_type', ProductType.BULK_PRODUCT)
    kwargs.setdefault('product_family', 'FAM')
    return Material(material_number=number, **kwargs)


def _machine(code, group='ZZ_MILL', oee=1.0):
    return Machine(machine_id=f'Z_{code}', machine_code=code, name=f'Machine {code}',
                   oee=oee, machine_group=group,
                   availability_by_period=dict.fromkeys(PERIODS, 1.0),
                   shift_system=ShiftSystem.THREE_SHIFT)


def _routing(work_center, base_qty=100.0, std_time=1.0):
    return SimpleNamespace(work_center=work_center, base_quantity=base_qty,
                           standard_time=std_time)


def _data(machines, materials, groups, routings, *, fte_hours_per_year=1492.0,
          **extra):
    base = SimpleNamespace(
        periods=list(PERIODS),
        machines=machines,
        machine_groups=groups,
        materials=materials,
        config=None,
        bom=[],
        shift_hours={'2-shift system': 4160 / 12, '3-shift system': 520.0,
                     '24/7 production': 730.0},
        default_shift_name='3-shift system',
        fte_hours_per_year=fte_hours_per_year,
        fte_params=dict(FTE_PARAM_DEFAULTS),
        staffing_norms={},
        labor_rates={},
        machine_combinations={},
        indirect_activities={},
        throughput_overrides={},
        benchmark_throughput={},
        get_all_routings=lambda m: routings.get(m, []),
    )
    for key, value in extra.items():
        setattr(base, key, value)
    return base


def _mill_setup(hours_per_period=100.0, **extra):
    """Eén molengroep, één machine, plan dat exact `hours_per_period` kost."""
    machines = {'MC1': _machine('MC1')}
    materials = {
        'ZZ_MILL': _mat('ZZ_MILL', name='Molens', mill_machine_group='1',
                        fte_requirements=1.0),
        'P1': _mat('P1'),
    }
    groups = {'ZZ_MILL': MachineGroup('ZZ_MILL', ['MC1'])}
    # AUX2 = base/std = 100/1 = 100 t/u → uren = ton / 100
    routings = {'P1': [_routing('MC1', base_qty=100.0, std_time=1.0)]}
    plan = {'P1': dict.fromkeys(PERIODS, hours_per_period * 100.0)}
    data = _data(machines, materials, groups, routings, **extra)
    return data, plan


def _demand_rows(data, demand):
    rows = []
    for material_number, values in (demand or {}).items():
        material = data.materials.get(material_number)
        rows.append(PlanningRow(
            material_number=material_number,
            material_name=getattr(material, 'name', '') or material_number,
            product_type=getattr(getattr(material, 'product_type', None), 'value', ''),
            product_family=getattr(material, 'product_family', '') or '',
            spc_product='', product_cluster='', product_name='',
            line_type=LineType.DEMAND_FORECAST.value,
            values=dict(values)))
    return rows


def _run(data, plan, *, active_combinations=None, demand=None):
    cap = CapacityEngine(data, plan, {
        LineType.DEMAND_FORECAST.value: demand or {},
    })
    results = cap.calculate()
    results[LineType.DEMAND_FORECAST.value] = _demand_rows(data, demand)
    return FteEngine(data, results,
                     active_combinations=active_combinations).calculate()


def _line(result, key, category=None):
    for line in result.lines:
        if line.key == key and (category is None or line.category == category):
            return line
    raise AssertionError(f'regel "{key}" ({category}) ontbreekt')


# ── basis ───────────────────────────────────────────────────────────────────


class TestDirectFte:
    def test_group_fte_matches_line12_without_staffing_norms(self):
        """Zonder bemensingsnormen valt de werkbank terug op de L12-coëfficiënt
        en produceert exact hetzelfde getal — geen tabel vol nullen."""
        data, plan = _mill_setup(hours_per_period=100.0)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        l12 = next(r for r in results[LineType.FTE_REQUIREMENTS.value]
                   if r.material_number == 'ZZ_MILL')

        result = FteEngine(data, results).calculate()
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)

        assert group.operators_source == 'line12_coefficient'
        for period in PERIODS:
            assert group.fte[period] == pytest.approx(l12.values[period])

    def test_staffing_norm_overrides_the_coefficient(self):
        norms = {'ZZ_MILL': StaffingNorm(code='ZZ_MILL', operators_per_hour=2.0,
                                         scope='group', function_group='operators')}
        data, plan = _mill_setup(hours_per_period=100.0, staffing_norms=norms)
        result = _run(data, plan)
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)

        assert group.operators_source == 'staffing_norms'
        # 100 uur × 2 operators ÷ (1492/12) = 1,6086 FTE
        assert group.fte['2025-01'] == pytest.approx(100.0 * 2.0 / (1492 / 12))
        assert group.function_group == 'operators'

    def test_machine_rows_are_detail_and_excluded_from_the_total(self):
        data, plan = _mill_setup(hours_per_period=100.0)
        result = _run(data, plan)
        machine = _line(result, 'MC1', CATEGORY_MACHINE)
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)

        assert machine.counts_in_total is False
        assert result.total_fte['2025-01'] == pytest.approx(group.fte['2025-01'])

    def test_utilization_is_hours_over_shift_hours(self):
        data, plan = _mill_setup(hours_per_period=260.0)
        result = _run(data, plan)
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)

        assert group.available_hours['2025-01'] == pytest.approx(520.0)
        assert group.utilization('2025-01') == pytest.approx(0.5)


class TestClientModelReproduction:
    """Ground truth uit 'OEE model MTO APEX voorbeeld.xlsx' (Maastricht/NLX1):
    311.846 t → 4.008 molenuren → 2,69 FTE → 64% benutting."""

    def test_tonnage_hours_fte_and_occupancy(self):
        tons_per_year = 311846.0
        hours_per_year = 4008.0
        throughput = tons_per_year / hours_per_year  # t/u die dat oplevert

        machines = {'PML01': _machine('PML01', group='ZZ_MILL')}
        materials = {
            'ZZ_MILL': _mat('ZZ_MILL', name='Mills', mill_machine_group='1',
                            fte_requirements=1.0),
            'B30': _mat('B30'),
        }
        groups = {'ZZ_MILL': MachineGroup('ZZ_MILL', ['PML01'])}
        routings = {'B30': [_routing('PML01', base_qty=throughput, std_time=1.0)]}
        plan = {'B30': dict.fromkeys(PERIODS, tons_per_year / 12)}
        # 3-ploegen = 6.240 jaaruren = 520 per maand
        data = _data(machines, materials, groups, routings)

        result = _run(data, plan)
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)

        annual_hours = sum(group.hours[p] for p in PERIODS) * 4  # 3 van 12 maanden
        assert annual_hours == pytest.approx(hours_per_year, rel=1e-6)

        annual_fte = sum(group.fte[p] for p in PERIODS) * 4 / 12
        assert annual_fte == pytest.approx(2.69, abs=0.01)

        assert group.utilization('2025-01') == pytest.approx(0.64, abs=0.005)


class TestIndirectActivities:
    def test_fixed_crew_per_shift(self):
        activities = {'CTRL': IndirectActivity(
            activity_id='CTRL', name='Controlekamer', driver='fixed',
            fte_per_shift=1.0, shifts=3.0)}
        data, plan = _mill_setup(indirect_activities=activities)
        result = _run(data, plan)

        line = _line(result, 'CTRL', CATEGORY_INDIRECT)
        assert line.fte['2025-01'] == pytest.approx(3.0)
        assert result.total_indirect_fte['2025-01'] == pytest.approx(3.0)

    def test_trucks_from_tonnage(self):
        """1.000 t ÷ 25 t/truck = 40 trucks × 0,75 u = 30 uur."""
        activities = {'TRUCK': IndirectActivity(
            activity_id='TRUCK', driver='per_truck', hours_per_unit=0.75,
            tons_per_truck=25.0, volume_source='P1')}
        data, plan = _mill_setup(indirect_activities=activities)
        demand = {'P1': dict.fromkeys(PERIODS, 1000.0)}
        result = _run(data, plan, demand=demand)

        line = _line(result, 'TRUCK', CATEGORY_INDIRECT)
        assert line.hours['2025-01'] == pytest.approx(30.0)
        assert line.fte['2025-01'] == pytest.approx(30.0 / (1492 / 12))

    def test_maintenance_per_machine(self):
        activities = {'MAINT': IndirectActivity(
            activity_id='MAINT', driver='per_machine', machines_per_fte=9.0,
            machine_count=18.0)}
        data, plan = _mill_setup(indirect_activities=activities)
        result = _run(data, plan)

        assert _line(result, 'MAINT', CATEGORY_INDIRECT).fte['2025-01'] == pytest.approx(2.0)

    def test_inactive_activity_is_skipped(self):
        activities = {'X': IndirectActivity(activity_id='X', driver='fixed',
                                            fte_per_period=5.0, is_active=False)}
        data, plan = _mill_setup(indirect_activities=activities)
        result = _run(data, plan)

        assert all(line.key != 'X' for line in result.lines)

    def test_unknown_driver_warns_instead_of_guessing(self):
        activities = {'X': IndirectActivity(activity_id='X', driver='per_moon')}
        data, plan = _mill_setup(indirect_activities=activities)
        result = _run(data, plan)

        assert any('per_moon' in w for w in result.warnings)
        assert all(line.key != 'X' for line in result.lines)


class TestThroughputOverrides:
    def test_lower_throughput_costs_more_hours(self):
        """Basisdoorzet 100 t/u, override 50 t/u → dubbele uren."""
        overrides = {'MC1|P1': ThroughputOverride(
            machine_code='MC1', material_number='P1',
            throughput_t_per_hour=50.0, source='MES')}
        data, plan = _mill_setup(hours_per_period=100.0, throughput_overrides=overrides)
        result = _run(data, plan)

        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(200.0)
        assert _line(result, 'ZZ_MILL', CATEGORY_GROUP).hours['2025-01'] == pytest.approx(200.0)

    def test_zero_override_is_refused_not_applied(self):
        overrides = {'MC1|P1': ThroughputOverride(
            machine_code='MC1', material_number='P1', throughput_t_per_hour=0.0)}
        data, plan = _mill_setup(hours_per_period=100.0, throughput_overrides=overrides)
        result = _run(data, plan)

        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(100.0)
        assert any('genegeerd' in w for w in result.warnings)


class TestCombinations:
    def _two_machine_setup(self, **extra):
        machines = {'MC1': _machine('MC1', group='ZZ_PACK'),
                    'MC2': _machine('MC2', group='ZZ_PACK')}
        materials = {
            'ZZ_PACK': _mat('ZZ_PACK', name='Pack', packaging_machine_group='1',
                            fte_requirements=1.0),
            'P1': _mat('P1'), 'P2': _mat('P2'),
        }
        groups = {'ZZ_PACK': MachineGroup('ZZ_PACK', ['MC1', 'MC2'])}
        routings = {'P1': [_routing('MC1')], 'P2': [_routing('MC2')]}
        plan = {'P1': dict.fromkeys(PERIODS, 10000.0),   # 100 uur
                'P2': dict.fromkeys(PERIODS, 5000.0)}    # 50 uur
        return _data(machines, materials, groups, routings, **extra), plan

    def test_shared_operator_staffs_the_longest_member_once(self):
        combos = {'C1': MachineCombination(
            combination_id='C1', name='Duo', machine_codes=['MC1', 'MC2'],
            operators=1.0, throughput_factor=1.0)}
        data, plan = self._two_machine_setup(machine_combinations=combos)

        without = _run(data, plan)
        with_combo = _run(data, plan, active_combinations=['C1'])

        # Zonder combinatie: pack-groep telt SUM = 150 uur × 1 operator.
        assert without.total_fte['2025-01'] == pytest.approx(150.0 / (1492 / 12))
        # Met combinatie: één operator over de langste machine (100 uur).
        assert with_combo.total_fte['2025-01'] == pytest.approx(100.0 / (1492 / 12))

    def test_throughput_factor_raises_hours(self):
        combos = {'C1': MachineCombination(
            combination_id='C1', machine_codes=['MC1', 'MC2'], operators=1.0,
            throughput_factor=0.5)}
        data, plan = self._two_machine_setup(machine_combinations=combos)
        result = _run(data, plan, active_combinations=['C1'])

        # Halve doorzet → dubbele uren: 100 → 200, 50 → 100.
        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(200.0)
        assert _line(result, 'C1', CATEGORY_GROUP).hours['2025-01'] == pytest.approx(200.0)

    def test_per_machine_factor_wins_over_the_combination_factor(self):
        combos = {'C1': MachineCombination(
            combination_id='C1', machine_codes=['MC1', 'MC2'], operators=1.0,
            throughput_factor=0.5, throughput_factor_by_machine={'MC2': 1.0})}
        data, plan = self._two_machine_setup(machine_combinations=combos)
        result = _run(data, plan, active_combinations=['C1'])

        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(200.0)
        assert _line(result, 'MC2', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(50.0)

    def test_unknown_combination_warns(self):
        data, plan = self._two_machine_setup()
        result = _run(data, plan, active_combinations=['NOPE'])

        assert any('NOPE' in w for w in result.warnings)
        assert result.active_combinations == []


class TestCostAndKpis:
    def test_labor_cost_uses_the_function_group_rate(self):
        norms = {'ZZ_MILL': StaffingNorm(code='ZZ_MILL', operators_per_hour=1.0,
                                         scope='group', function_group='operators')}
        rates = {'operators': LaborRate(function_group='operators',
                                        cost_per_fte_per_year=60000.0),
                 'default': LaborRate(function_group='default',
                                      cost_per_fte_per_year=99000.0)}
        data, plan = _mill_setup(hours_per_period=100.0, staffing_norms=norms,
                                 labor_rates=rates)
        result = _run(data, plan)
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)

        assert group.cost['2025-01'] == pytest.approx(group.fte['2025-01'] * 5000.0)

    def test_default_rate_is_the_fallback(self):
        rates = {'default': LaborRate(function_group='default',
                                      cost_per_fte_per_year=12000.0)}
        data, plan = _mill_setup(hours_per_period=100.0, labor_rates=rates)
        result = _run(data, plan)
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)

        assert group.cost['2025-01'] == pytest.approx(group.fte['2025-01'] * 1000.0)

    def test_staffed_fte_grosses_up_to_the_occupancy_target(self):
        data, plan = _mill_setup(hours_per_period=100.0)
        result = _run(data, plan)

        assert result.utilization_rate == pytest.approx(0.85)
        assert result.staffed_fte('2025-01') == pytest.approx(
            result.total_fte['2025-01'] / 0.85)

    def test_tons_per_fte(self):
        data, plan = _mill_setup(hours_per_period=100.0)
        demand = {'P1': dict.fromkeys(PERIODS, 10000.0)}
        result = _run(data, plan, demand=demand)

        assert result.total_volume['2025-01'] == pytest.approx(10000.0)
        assert result.tons_per_fte('2025-01') == pytest.approx(
            10000.0 / result.total_fte['2025-01'])

    def test_derived_hours_are_reported_but_never_substituted(self):
        """De afleiding rapporteert 1492,48; het INGESTELDE eindgetal (1492)
        blijft rekenen. Wie de afleiding aanpast verandert daarmee geen enkel
        FTE-getal — dat is precies de bedoeling."""
        params = dict(FTE_PARAM_DEFAULTS)
        params.update({'gross_hours_per_year': 2080.0, 'leave_hours_per_year': 224.0,
                       'adv_hours_per_year': 112.0, 'holiday_hours_per_year': 48.0,
                       'illness_pct': 0.10, 'training_pct': 0.02})
        data, plan = _mill_setup(hours_per_period=100.0, fte_params=params)
        result = _run(data, plan)

        assert result.fte_hours_per_year == 1492.0            # leidend
        assert result.derived_fte_hours_per_year == pytest.approx(1492.48, abs=0.01)
        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)
        assert group.fte['2025-01'] == pytest.approx(100.0 / (1492 / 12))


class TestValueImpact:
    """Fase B: de werkbank vervangt de directe-FTE-kost in de bestaande
    consolidatie; alles stroomafwaarts schuift met exact dat verschil mee.
    De 20 VBA-regels zelf blijven ongemoeid."""

    def _consolidation(self, direct_fte=10000.0):
        def _row(number, value):
            return PlanningRow(
                material_number=number, material_name='', product_type='',
                product_family='', spc_product='', product_cluster='',
                product_name='', line_type=LineType.CONSOLIDATION.value,
                values=dict.fromkeys(PERIODS, value))

        return {LineType.CONSOLIDATION.value: [
            _row('ZZZZZZ_DIRECT FTE COST', direct_fte),
            _row('ZZZZZZ_COST OF GOODS', 100000.0),
            _row('ZZZZZZ_GROSS MARGIN', 40000.0),
            _row('ZZZZZZ_EBITDA', 30000.0),
            _row('ZZZZZZ_EBIT', 25000.0),
            _row('ZZZZZZ_OPERATIONAL CASHFLOW', 28000.0),
            _row('ZZZZZZ_CAPITAL INVESTMENT', 1200000.0),
        ]}

    def _result(self, direct_fte=10000.0, rate=60000.0):
        norms = {'ZZ_MILL': StaffingNorm(code='ZZ_MILL', operators_per_hour=1.0,
                                         scope='group', function_group='operators')}
        rates = {'operators': LaborRate(function_group='operators',
                                        cost_per_fte_per_year=rate)}
        data, plan = _mill_setup(hours_per_period=100.0, staffing_norms=norms,
                                 labor_rates=rates)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []
        return FteEngine(data, results,
                         value_results=self._consolidation(direct_fte)).calculate()

    def test_margin_moves_by_exactly_the_labour_delta(self):
        result = self._result()
        impact = result.value_impact
        assert impact.available

        delta = impact.workbench_labor_cost['2025-01'] - 10000.0
        assert impact.delta['2025-01'] == pytest.approx(delta)
        assert impact.cost_of_goods['2025-01'] == pytest.approx(100000.0 + delta)
        assert impact.gross_margin['2025-01'] == pytest.approx(40000.0 - delta)
        assert impact.ebitda['2025-01'] == pytest.approx(30000.0 - delta)
        assert impact.ebit['2025-01'] == pytest.approx(25000.0 - delta)
        assert impact.operational_cashflow['2025-01'] == pytest.approx(28000.0 - delta)
        assert impact.roce['2025-01'] == pytest.approx(
            impact.ebit['2025-01'] * 12 / 1200000.0)

    def test_baseline_is_reported_unchanged(self):
        impact = self._result().value_impact
        assert impact.baseline['ZZZZZZ_GROSS MARGIN']['2025-01'] == 40000.0
        assert impact.baseline_labor_cost['2025-01'] == 10000.0

    def test_no_labour_rates_means_no_claimed_saving(self):
        data, plan = _mill_setup(hours_per_period=100.0)  # geen labor_rates
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []
        impact = FteEngine(data, results,
                           value_results=self._consolidation()).calculate().value_impact

        assert impact.available is False
        assert impact.gross_margin == {}

    def test_without_consolidation_the_panel_stays_empty(self):
        data, plan = _mill_setup(hours_per_period=100.0)
        result = _run(data, plan)
        assert result.value_impact.available is False


class TestSerialization:
    def test_to_dict_is_json_safe(self):
        import json

        data, plan = _mill_setup(hours_per_period=100.0)
        payload = _run(data, plan).to_dict()
        json.dumps(payload)  # mag niet raisen

        assert payload['totals']['fte']['2025-01'] > 0
        assert {line['category'] for line in payload['lines']} <= {
            CATEGORY_MACHINE, CATEGORY_GROUP, CATEGORY_INDIRECT}
