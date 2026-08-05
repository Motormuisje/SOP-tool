"""FTE-motor: de defensieve paden.

Dit zijn de takken die alleen afgaan op onvolledige of tegenstrijdige
klantdata — precies waar een stil verkeerd getal ontstaat. Ze hadden geen
dekking, terwijl ze het vaakst geraakt worden zodra een site zijn masterdata
nog aan het vullen is.
"""

from types import SimpleNamespace

import pytest

from modules.capacity_engine import CapacityEngine
from modules.fte_engine import (
    CATEGORY_GROUP,
    CATEGORY_INDIRECT,
    CATEGORY_MACHINE,
    FteEngine,
    _label,
)
from modules.models import (
    BenchmarkThroughput,
    IndirectActivity,
    LineType,
    MachineCombination,
    MachineGroup,
    StaffingNorm,
    ThroughputOverride,
)
from tests.test_fte_engine import (
    PERIODS,
    _data,
    _demand_rows,
    _line,
    _machine,
    _mat,
    _mill_setup,
    _routing,
    _run,
)

pytestmark = pytest.mark.no_fixture


class TestLabels:
    def test_nan_and_empties_fall_through_to_the_code(self):
        assert _label('nan', '', None, 'ZZ_GROUP01') == 'ZZ_GROUP01'
        assert _label('NaN', 'Echte naam') == 'Echte naam'
        assert _label(None, '', 'nan') == ''
        assert _label('  Pendelmolens  ') == 'Pendelmolens'


class TestOperatorFallbacks:
    def test_machine_scope_norm_beats_the_group(self):
        norms = {'MC1': StaffingNorm(code='MC1', operators_per_hour=3.0, scope='machine'),
                 'ZZ_MILL': StaffingNorm(code='ZZ_MILL', operators_per_hour=1.0,
                                         scope='group')}
        data, plan = _mill_setup(hours_per_period=100.0, staffing_norms=norms)
        result = _run(data, plan)

        machine = _line(result, 'MC1', CATEGORY_MACHINE)
        assert machine.operators_per_hour == 3.0
        assert machine.operators_source == 'staffing_norms'
        # De groep houdt zijn eigen norm.
        assert _line(result, 'ZZ_MILL', CATEGORY_GROUP).operators_per_hour == 1.0

    def test_a_group_without_any_norm_defaults_to_one_operator(self):
        """Zonder norm én zonder L12-coëfficiënt is 1,0 de VBA-terugval — maar
        de herkomst moet 'default' zeggen, niet 'staffing_norms'."""
        data, plan = _mill_setup(hours_per_period=100.0)
        data.materials['ZZ_MILL'].fte_requirements = 0.0
        result = _run(data, plan)

        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)
        assert group.operators_per_hour == 1.0
        assert group.operators_source == 'default'

    def test_a_norm_with_the_wrong_scope_is_not_used(self):
        """Een norm met scope 'machine' op een groepscode mag niet als
        groepsnorm gelden — dat zou stil de verkeerde bemensing pakken."""
        norms = {'ZZ_MILL': StaffingNorm(code='ZZ_MILL', operators_per_hour=9.0,
                                         scope='machine')}
        data, plan = _mill_setup(hours_per_period=100.0, staffing_norms=norms)
        result = _run(data, plan)

        group = _line(result, 'ZZ_MILL', CATEGORY_GROUP)
        assert group.operators_per_hour == 1.0
        assert group.operators_source == 'line12_coefficient'


class TestThroughputOverrideEdges:
    def test_a_row_without_a_base_throughput_is_refused(self):
        """AUX2 van de Line 07-materiaalrij draagt de basisdoorzet. Ontbreekt
        die, dan is de factor niet te berekenen en mag er niets gebeuren."""
        overrides = {'MC1|P1': ThroughputOverride(
            machine_code='MC1', material_number='P1', throughput_t_per_hour=50.0)}
        data, plan = _mill_setup(hours_per_period=100.0, throughput_overrides=overrides)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        for row in results[LineType.CAPACITY_UTILIZATION.value]:
            if row.material_number == 'P1':
                row.aux_2_column = 'onbekend'
        results[LineType.DEMAND_FORECAST.value] = []

        result = FteEngine(data, results).calculate()

        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(100.0)
        assert any('basisdoorzet ontbreekt' in w for w in result.warnings)

    def test_an_override_on_an_unknown_machine_does_nothing(self):
        overrides = {'NOPE|P1': ThroughputOverride(
            machine_code='NOPE', material_number='P1', throughput_t_per_hour=1.0)}
        data, plan = _mill_setup(hours_per_period=100.0, throughput_overrides=overrides)
        result = _run(data, plan)

        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(100.0)


class TestCombinationEdges:
    def _setup(self, factor):
        combos = {'C': MachineCombination(combination_id='C', machine_codes=['MC1'],
                                          operators=1.0, throughput_factor=factor)}
        return _mill_setup(hours_per_period=100.0, machine_combinations=combos)

    def test_a_zero_factor_is_refused_and_reported(self):
        """Factor 0 zou door nul delen; factor 1 gebruiken en het zeggen is
        beter dan een oneindig aantal uren."""
        data, plan = self._setup(0.0)
        result = _run(data, plan, active_combinations=['C'])

        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(100.0)
        assert any('factor 1 gebruikt' in w for w in result.warnings)

    def test_a_negative_factor_is_refused_too(self):
        data, plan = self._setup(-2.0)
        result = _run(data, plan, active_combinations=['C'])

        assert _line(result, 'MC1', CATEGORY_MACHINE).hours['2025-01'] == pytest.approx(100.0)
        assert any('negatief' in w for w in result.warnings)

    def test_an_inactive_combination_cannot_be_switched_on(self):
        combos = {'C': MachineCombination(combination_id='C', machine_codes=['MC1'],
                                          operators=1.0, is_active=False)}
        data, plan = _mill_setup(hours_per_period=100.0, machine_combinations=combos)
        result = _run(data, plan, active_combinations=['C'])

        assert result.active_combinations == []
        assert any('niet (meer) beschikbaar' in w for w in result.warnings)


class TestVolumeSources:
    def _demand_setup(self, **extra):
        data, plan = _mill_setup(hours_per_period=100.0, **extra)
        data.materials['P2'] = _mat('P2', product_family='ANDERS')
        return data, plan

    def test_a_family_name_is_accepted_as_volume_source(self):
        """volume_source matcht eerst op materiaalnummer, dan op productfamilie."""
        activities = {'T': IndirectActivity(activity_id='T', driver='per_ton',
                                            hours_per_unit=0.01, volume_source='FAM')}
        data, plan = self._demand_setup(indirect_activities=activities)
        demand = {'P1': dict.fromkeys(PERIODS, 1000.0),
                  'P2': dict.fromkeys(PERIODS, 5000.0)}
        result = _run(data, plan, demand=demand)

        # Alleen P1 zit in familie FAM; P2 zit in ANDERS.
        assert _line(result, 'T', CATEGORY_INDIRECT).hours['2025-01'] == pytest.approx(10.0)

    def test_an_unknown_volume_source_warns_and_yields_nothing(self):
        activities = {'T': IndirectActivity(activity_id='T', driver='per_ton',
                                            hours_per_unit=1.0,
                                            volume_source='BESTAAT-NIET')}
        data, plan = self._demand_setup(indirect_activities=activities)
        result = _run(data, plan, demand={'P1': dict.fromkeys(PERIODS, 1000.0)})

        assert _line(result, 'T', CATEGORY_INDIRECT).hours['2025-01'] == pytest.approx(0.0)
        assert any('BESTAAT-NIET' in w for w in result.warnings)

    def test_an_explicit_volume_line_is_honoured(self):
        """Standaard is de vraagregel; een activiteit mag op het productieplan
        rekenen als de klant dat zegt."""
        activities = {'T': IndirectActivity(activity_id='T', driver='per_ton',
                                            hours_per_unit=0.001,
                                            volume_line=LineType.PRODUCTION_PLAN.value)}
        data, plan = self._demand_setup(indirect_activities=activities)
        result = _run(data, plan, demand={'P1': dict.fromkeys(PERIODS, 999999.0)})

        # De vraagregel is enorm, maar deze activiteit kijkt naar het (lege)
        # productieplan in de resultaten — dus 0, niet 999.
        assert _line(result, 'T', CATEGORY_INDIRECT).hours['2025-01'] == pytest.approx(0.0)


class TestIndirectDriverEdges:
    def test_per_truck_without_tons_per_truck_yields_nothing(self):
        activities = {'T': IndirectActivity(activity_id='T', driver='per_truck',
                                            hours_per_unit=1.5, tons_per_truck=0.0)}
        data, plan = _mill_setup(hours_per_period=100.0, indirect_activities=activities)
        result = _run(data, plan, demand={'P1': dict.fromkeys(PERIODS, 1000.0)})

        assert _line(result, 'T', CATEGORY_INDIRECT).hours['2025-01'] == pytest.approx(0.0)
        assert any('ton per truck is 0' in w for w in result.warnings)

    def test_per_machine_without_machines_per_fte_is_dropped(self):
        activities = {'M': IndirectActivity(activity_id='M', driver='per_machine',
                                            machines_per_fte=0.0)}
        data, plan = _mill_setup(hours_per_period=100.0, indirect_activities=activities)
        result = _run(data, plan)

        assert all(line.key != 'M' for line in result.lines)
        assert any('machines per FTE is 0' in w for w in result.warnings)

    def test_per_machine_counts_the_real_machines_when_no_count_is_given(self):
        activities = {'M': IndirectActivity(activity_id='M', driver='per_machine',
                                            machines_per_fte=1.0, machine_count=0.0)}
        data, plan = _mill_setup(hours_per_period=100.0, indirect_activities=activities)
        result = _run(data, plan)

        # De opstelling heeft één machine.
        assert _line(result, 'M', CATEGORY_INDIRECT).fte['2025-01'] == pytest.approx(1.0)

    def test_fixed_via_shifts_multiplies_out(self):
        activities = {'C': IndirectActivity(activity_id='C', driver='fixed',
                                            fte_per_shift=2.0, shifts=3.0)}
        data, plan = _mill_setup(hours_per_period=100.0, indirect_activities=activities)
        result = _run(data, plan)

        assert _line(result, 'C', CATEGORY_INDIRECT).fte['2025-01'] == pytest.approx(6.0)


class TestDegenerateConfiguration:
    def test_zero_fte_hours_gives_zero_fte_instead_of_dividing(self):
        data, plan = _mill_setup(hours_per_period=100.0)
        data.fte_hours_per_year = 0.0
        result = _run(data, plan)

        assert result.total_fte['2025-01'] == 0.0
        assert _line(result, 'ZZ_MILL', CATEGORY_GROUP).hours['2025-01'] > 0

    def test_zero_utilization_rate_does_not_divide_by_zero(self):
        from modules.models import FTE_PARAM_DEFAULTS

        params = dict(FTE_PARAM_DEFAULTS)
        params['utilization_rate'] = 0.0
        data, plan = _mill_setup(hours_per_period=100.0, fte_params=params)
        result = _run(data, plan)

        # utilization_rate 0 wordt als 1 behandeld: liever de ruwe FTE tonen
        # dan een deling door nul of een oneindige bezetting.
        assert result.utilization_rate == 1.0
        assert result.staffed_fte('2025-01') == pytest.approx(result.total_fte['2025-01'])

    def test_no_periods_produces_an_empty_but_valid_result(self):
        data, plan = _mill_setup(hours_per_period=100.0)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []
        data.periods = []

        result = FteEngine(data, results).calculate()

        assert result.periods == []
        assert result.utilization('2025-01') == 0.0
        assert result.tons_per_fte('2025-01') == 0.0
        result.to_dict()   # mag niet raisen

    def test_a_machine_without_a_group_still_gets_a_detail_row(self):
        machines = {'LOS': _machine('LOS', group=None)}
        materials = {'P1': _mat('P1')}
        groups = {}
        routings = {'P1': [_routing('LOS')]}
        plan = {'P1': dict.fromkeys(PERIODS, 10000.0)}
        data = _data(machines, materials, groups, routings)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []

        result = FteEngine(data, results).calculate()
        line = _line(result, 'LOS', CATEGORY_MACHINE)

        assert line.machine_group == ''
        assert line.available_hours == {}
        assert line.counts_in_total is False


class TestBenchmarkSelection:
    def _with(self, benchmarks):
        return _mill_setup(hours_per_period=100.0, benchmark_throughput=benchmarks)

    def test_the_installation_level_entry_wins_over_product_rows(self):
        benchmarks = {
            'MC1|': BenchmarkThroughput(machine_code='MC1', peer_t_per_hour=9.0),
            'MC1|P1': BenchmarkThroughput(machine_code='MC1', material_number='P1',
                                          peer_t_per_hour=5.0),
            'MC1|P2': BenchmarkThroughput(machine_code='MC1', material_number='P2',
                                          peer_t_per_hour=1.0),
        }
        data, plan = self._with(benchmarks)
        result = _run(data, plan)

        assert _line(result, 'MC1', CATEGORY_MACHINE).throughput_peer == pytest.approx(9.0)

    def test_several_product_rows_without_an_installation_total_show_nothing(self):
        """Middelen over producten zou een getal verzinnen dat niemand heeft
        gemeten."""
        benchmarks = {
            'MC1|P1': BenchmarkThroughput(machine_code='MC1', material_number='P1',
                                          peer_t_per_hour=5.0),
            'MC1|P2': BenchmarkThroughput(machine_code='MC1', material_number='P2',
                                          peer_t_per_hour=1.0),
        }
        data, plan = self._with(benchmarks)
        result = _run(data, plan)

        assert _line(result, 'MC1', CATEGORY_MACHINE).throughput_peer is None

    def test_a_single_product_row_is_used(self):
        benchmarks = {'MC1|P1': BenchmarkThroughput(
            machine_code='MC1', material_number='P1', mes_t_per_hour=4.0, mes_oee=0.8)}
        data, plan = self._with(benchmarks)
        result = _run(data, plan)
        line = _line(result, 'MC1', CATEGORY_MACHINE)

        assert line.throughput_mes == pytest.approx(4.0)
        assert line.throughput_source == 'MES/PEER'


class TestCompoundProductionLines:
    """CapacityEngine vervangt de machines van een gegroepeerde productielijn
    in de groepsaggregatie door één GEMIDDELDE compound-rij. De werkbank moet
    dezelfde basis gebruiken, anders klopt de delta niet."""

    def _setup(self, **extra):
        machines = {'PML01': _machine('PML01', group='ZZ_G1'),
                    'PML02': _machine('PML02', group='ZZ_G1'),
                    'MC9': _machine('MC9', group='ZZ_G1')}
        materials = {
            'ZZ_G1': _mat('ZZ_G1', mill_machine_group='1', fte_requirements=1.0),
            'COMP': _mat('COMP', grouped_production_line='1',
                         production_line='PML01-PML02'),
            'P1': _mat('P1'), 'P2': _mat('P2'), 'P9': _mat('P9'),
        }
        groups = {'ZZ_G1': MachineGroup('ZZ_G1', ['PML01', 'PML02', 'MC9'])}
        routings = {'P1': [_routing('PML01')], 'P2': [_routing('PML02')],
                    'P9': [_routing('MC9')]}
        plan = {'P1': dict.fromkeys(PERIODS, 10000.0),
                'P2': dict.fromkeys(PERIODS, 5000.0),
                'P9': dict.fromkeys(PERIODS, 2000.0)}
        return _data(machines, materials, groups, routings, **extra), plan

    def test_without_changes_the_group_matches_line_07_exactly(self):
        data, plan = self._setup()
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []
        l07_group = next(r for r in results[LineType.CAPACITY_UTILIZATION.value]
                         if r.material_number == 'ZZ_G1')

        result = FteEngine(data, results).calculate()

        assert _line(result, 'ZZ_G1', CATEGORY_GROUP).hours['2025-01'] == pytest.approx(
            l07_group.values['2025-01'])

    def test_an_override_on_a_compound_machine_moves_the_group_by_the_average(self):
        """De compound-rij is het GEMIDDELDE van zijn componenten, dus een
        override op één component telt voor de helft mee — precies zoals
        CapacityEngine het doet. Eerder liet de werkbank het effect helemaal
        weg en waarschuwde hij; nu kan hij het gewoon uitdrukken."""
        overrides = {'PML01|P1': ThroughputOverride(
            machine_code='PML01', material_number='P1', throughput_t_per_hour=50.0)}
        data, plan = self._setup(throughput_overrides=overrides)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []

        result = FteEngine(data, results).calculate()
        group = _line(result, 'ZZ_G1', CATEGORY_GROUP)

        # PML01 100 u -> 200 u (halve doorzet). Compound-gemiddelde
        # (PML01+PML02)/2 gaat van 75 naar 125; MC9 blijft 20. MAX = 125.
        assert group.hours['2025-01'] == pytest.approx(125.0)
        assert not any('gegroepeerde productielijn' in w for w in result.warnings)

    def test_an_override_on_a_loose_machine_is_absorbed_by_the_maximum(self):
        """Regressie: de delta werd over alleen de NIET-compound leden
        gemaximeerd, waardoor +20 uur op MC9 gewoon bij de groepsrij werd
        opgeteld terwijl de compound-lijn (75 u) de MAX blijft bepalen."""
        overrides = {'MC9|P9': ThroughputOverride(
            machine_code='MC9', material_number='P9', throughput_t_per_hour=50.0)}
        data, plan = self._setup(throughput_overrides=overrides)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []

        result = FteEngine(data, results).calculate()
        group = _line(result, 'ZZ_G1', CATEGORY_GROUP)

        # MC9 20 -> 40 u, maar de compound-lijn zit op 75: MAX blijft 75.
        assert group.hours['2025-01'] == pytest.approx(75.0)

    def test_a_group_of_only_compound_machines_is_not_counted_twice(self):
        """Regressie: bij een groep die UITSLUITEND uit compound-machines
        bestaat bleef de groepsregel haar volle uren houden terwijl de
        combinatie er een tweede bemensing bovenop zette — een besparende
        combinatie verdubbelde het FTE-totaal."""
        machines = {'PML01': _machine('PML01', group='ZZ_G1'),
                    'PML02': _machine('PML02', group='ZZ_G1')}
        materials = {
            'ZZ_G1': _mat('ZZ_G1', mill_machine_group='1', fte_requirements=1.0),
            'COMP': _mat('COMP', grouped_production_line='1',
                         production_line='PML01-PML02'),
            'P1': _mat('P1'), 'P2': _mat('P2'),
        }
        groups = {'ZZ_G1': MachineGroup('ZZ_G1', ['PML01', 'PML02'])}
        routings = {'P1': [_routing('PML01')], 'P2': [_routing('PML02')]}
        plan = {'P1': dict.fromkeys(PERIODS, 10000.0),   # 100 u
                'P2': dict.fromkeys(PERIODS, 5000.0)}    # 50 u
        combos = {'C': MachineCombination(combination_id='C',
                                          machine_codes=['PML01', 'PML02'],
                                          operators=1.0)}
        data = _data(machines, materials, groups, routings,
                     machine_combinations=combos)
        cap = CapacityEngine(data, plan, {})
        results = cap.calculate()
        results[LineType.DEMAND_FORECAST.value] = []

        without = FteEngine(data, results).calculate()
        with_combo = FteEngine(data, results, active_combinations=['C']).calculate()

        # Line 07 geeft de groep het compound-gemiddelde: (100+50)/2 = 75.
        assert without.total_hours['2025-01'] == pytest.approx(75.0)
        # Met de combinatie bemenst één operator de langste machine (100 u) en
        # houdt de groep niets over — niet 75 + 100.
        assert with_combo.total_hours['2025-01'] == pytest.approx(100.0)
        assert _line(with_combo, 'ZZ_G1', CATEGORY_GROUP).hours['2025-01'] == pytest.approx(0.0)
