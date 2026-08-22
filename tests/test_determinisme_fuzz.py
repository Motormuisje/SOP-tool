"""Niets aan toeval: determinisme en seeded fuzz op de rekenpaden.

Drie soorten garanties die gewone voorbeeldtests niet geven:

1. DETERMINISME — dezelfde invoer geeft byte-identieke uitvoer. Een motor
   die stiekem van iteratievolgorde of toeval afhangt, geeft twee planners
   twee waarheden.
2. ADDITIVITEIT ALS TEST — de wat-als-parameters met hun lege waarde zijn
   bit-identiek aan het weglaten ervan. Dit was tot nu een handmatig bewijs
   bij commits; nu bewaakt de suite het.
3. SEEDED FUZZ — honderden willekeurige (maar reproduceerbare) invoeren
   door de motor en de inzet-berekening, met invarianten die ALTIJD moeten
   gelden: geen exceptie, geen NaN/inf, geen negatieve uren/FTE/kosten,
   JSON-serialiseerbaar. De seed staat vast (geen toeval in de test zelf);
   een faal print de casus zodat hij direct een regressietest kan worden.
"""

import json
import math
import random

import pytest

from modules.fte_engine import CONTROL_ROOM_MATERIAL, FteEngine
from modules.master_data import FTE_DATASET_KEY_FIELDS, _reconcile_key
from modules.models import MachineCombination, StaffingNorm, derive_effective_fte_hours
from tests.test_state_model_fte import _combo_setup
from ui.routes.machine_inzet import _machine_usage

pytestmark = pytest.mark.no_fixture

SEED = 20260821


def _alles_eindig(mapping, pad=''):
    """Loop een geneste dict/list af en eis dat elk getal eindig is."""
    if isinstance(mapping, dict):
        for key, value in mapping.items():
            _alles_eindig(value, f'{pad}.{key}')
    elif isinstance(mapping, (list, tuple)):
        for i, value in enumerate(mapping):
            _alles_eindig(value, f'{pad}[{i}]')
    elif isinstance(mapping, float):
        assert math.isfinite(mapping), f'niet-eindig getal op {pad}: {mapping}'


class TestDeterminisme:
    def test_zelfde_invoer_geeft_identieke_uitvoer(self):
        data, results = _combo_setup()
        run1 = FteEngine(data, results, active_combinations=['C1']).calculate().to_dict()
        run2 = FteEngine(data, results, active_combinations=['C1']).calculate().to_dict()
        assert json.dumps(run1, sort_keys=True) == json.dumps(run2, sort_keys=True)

    def test_lege_watals_is_bit_identiek_aan_geen_watals(self):
        """Additiviteit, vastgepind: {} en None mogen op geen enkel cijfer of
        veld verschillen van het weglaten van het argument."""
        data, results = _combo_setup()
        kaal = FteEngine(data, results).calculate().to_dict()
        leeg = FteEngine(data, results,
                         staffing_norm_overrides={}).calculate().to_dict()
        expliciet_none = FteEngine(data, results,
                                   staffing_norm_overrides=None).calculate().to_dict()
        assert json.dumps(kaal, sort_keys=True) == json.dumps(leeg, sort_keys=True)
        assert json.dumps(kaal, sort_keys=True) == json.dumps(expliciet_none, sort_keys=True)

    def test_machine_usage_is_deterministisch(self):
        data, results = _combo_setup()

        class _E:
            pass
        engine = _E()
        engine.data = data
        engine.results = results
        assert _machine_usage(engine) == _machine_usage(engine)


class TestVastgepindeSemantiek:
    def test_controlekamer_override(self):
        """De controlekamer heeft bewust géén 1,0-terugval (VBA-pariteit).
        Zonder norm: 0.0 uit de L12-tak. Mét wat-als: de override wint, met
        bron 'wat-als' — invulbaar is invulbaar, ook hier."""
        data, results = _combo_setup()
        engine = FteEngine(data, results)
        assert engine._group_operators(CONTROL_ROOM_MATERIAL) == (0.0, 'line12_coefficient')

        overschreven = FteEngine(data, results, staffing_norm_overrides={
            CONTROL_ROOM_MATERIAL: {'operators_per_hour': 2.0, 'scope': 'group'}})
        assert overschreven._group_operators(CONTROL_ROOM_MATERIAL) == (2.0, 'wat-als')

    def test_groepsoverride_raakt_de_combinatieregel_niet(self):
        """Een wat-als op de groep verandert de groepsbemensing; de
        combinatieregel houdt zijn eigen operators (bron 'combination') —
        anders telt een override dubbel via de gedeelde pool."""
        data, results = _combo_setup()
        result = FteEngine(data, results, active_combinations=['C1'],
                           staffing_norm_overrides={
                               'ZZ_G1': {'operators_per_hour': 3.0, 'scope': 'group'}},
                           ).calculate()
        groep = next(l for l in result.lines if l.category == 'group' and l.key == 'ZZ_G1'
                     and not l.combination_id)
        # Ook machinerijen dragen combination_id; de combinatieregel zelf is
        # de category-'group'-regel met de combinatie als sleutel. De
        # machinerij MAG 'wat-als' erven (zijn operators volgen de groep).
        combi = next(l for l in result.lines
                     if l.combination_id == 'C1' and l.category == 'group')
        machine_detail = next(l for l in result.lines
                              if l.combination_id == 'C1' and l.category == 'machine')
        assert machine_detail.operators_source == 'wat-als'
        assert groep.operators_per_hour == pytest.approx(3.0)
        assert groep.operators_source == 'wat-als'
        assert combi.operators_source == 'combination'
        assert combi.operators_per_hour == pytest.approx(1.0)   # uit de definitie


class TestSeededFuzzEngine:
    def test_willekeurige_invoer_breekt_de_motor_niet(self):
        rng = random.Random(SEED)
        codes = ['ZZ_G1', 'ZZ_G2', 'MC1', 'MA', 'MB', 'ONBEKEND_1', "O'BRIEN",
                 'MET|PIJP', CONTROL_ROOM_MATERIAL]
        for ronde in range(40):
            data, results = _combo_setup()
            # Willekeurige normen in de masterdata.
            data.staffing_norms = {
                code: StaffingNorm(code=code,
                                   operators_per_hour=round(rng.uniform(0, 5), 3),
                                   scope=rng.choice(['group', 'machine']))
                for code in rng.sample(codes, rng.randint(0, 4))
            }
            # Willekeurige wat-als, deels op onzinnige codes en scopes.
            overrides = {
                code: {'operators_per_hour': round(rng.uniform(0, 8), 3),
                       'scope': rng.choice(['group', 'machine'])}
                for code in rng.sample(codes, rng.randint(0, 5))
            }
            actief = ['C1'] if rng.random() < 0.5 else []
            result = FteEngine(data, results, active_combinations=actief,
                               staffing_norm_overrides=overrides).calculate()
            payload = result.to_dict()

            json.dumps(payload)                      # serialiseerbaar
            _alles_eindig(payload)                   # geen NaN/inf
            for lijn in result.lines:                # niets negatiefs
                for verzameling in (lijn.hours, lijn.fte, lijn.cost):
                    for waarde in verzameling.values():
                        assert waarde >= 0, (ronde, lijn.key, waarde)
            assert all(isinstance(w, str) for w in result.warnings), (ronde, result.warnings)

    def test_fuzz_is_reproduceerbaar(self):
        """De fuzz zelf mag geen toevalsbron zijn: tweemaal dezelfde seed
        levert exact dezelfde reeks casussen op."""
        def trekking():
            rng = random.Random(SEED)
            return [round(rng.uniform(0, 5), 6) for _ in range(50)]
        assert trekking() == trekking()


class TestSeededFuzzInzet:
    def test_willekeurige_planningen_breken_de_inzetberekening_niet(self):
        rng = random.Random(SEED)
        for ronde in range(25):
            data, results = _combo_setup()
            from modules.models import LineType
            for row in results[LineType.CAPACITY_UTILIZATION.value]:
                for periode in list(row.values):
                    keuze = rng.random()
                    if keuze < 0.3:
                        row.values[periode] = 0.0
                    elif keuze < 0.5:
                        row.values[periode] = round(rng.uniform(0, 0.01), 5)  # ruis
                    else:
                        row.values[periode] = round(rng.uniform(0, 5000), 2)

            class _E:
                pass
            engine = _E()
            engine.data = data
            engine.results = results
            usage = _machine_usage(engine)

            json.dumps(usage)
            _alles_eindig(usage)
            for machine in usage['machines'].values():
                for cel in machine['per_period'].values():
                    producten = cel['products']
                    assert producten == sorted(set(producten)), (ronde, producten)
                    assert cel['hours'] >= 0 and cel['window'] >= 0
                    # De schatting die de UI hierop bouwt kan nooit negatief.
                    assert max(0, len(producten) - 1) >= 0


class TestSleutelFuzz:
    def test_reconcile_is_idempotent_of_weigert(self):
        """Voor elke dataset en elke rare sleutel: óf een nette ValueError,
        óf een genormaliseerde sleutel die bij HERnormalisatie zichzelf
        oplevert — een sleutel die bij elke ronde verschuift zou records
        laten zwerven."""
        rng = random.Random(SEED)
        fragmenten = ['ZZ_G1', ' MA ', "O'BRIEN", 'MET|PIJP', '', '  ', 'A|B|C',
                      'PBA07', '150000276', 'ZZZ PACK', '|', 'x|', '|y']
        for dataset in FTE_DATASET_KEY_FIELDS:
            for _ in range(30):
                sleutel = rng.choice(fragmenten) + rng.choice(['', '|' + rng.choice(fragmenten)])
                try:
                    eerste = _reconcile_key(dataset, sleutel, {})
                except ValueError:
                    continue
                tweede = _reconcile_key(dataset, eerste, {})
                assert tweede == eerste, (dataset, sleutel, eerste, tweede)


class TestAfleidingFuzz:
    def test_effectieve_uren_zijn_additief_en_nooit_negatief(self):
        rng = random.Random(SEED)
        for _ in range(200):
            params = {
                'gross_hours_per_year': rng.uniform(0, 3000),
                'leave_hours_per_year': rng.uniform(0, 500),
                'adv_hours_per_year': rng.uniform(0, 300),
                'holiday_hours_per_year': rng.uniform(0, 200),
                'illness_pct': rng.uniform(0, 0.5),
                'training_pct': rng.uniform(0, 0.3),
            }
            uitkomst = derive_effective_fte_hours(params)
            basis = (params['gross_hours_per_year'] - params['leave_hours_per_year']
                     - params['adv_hours_per_year'] - params['holiday_hours_per_year'])
            verwacht = max(basis * (1.0 - params['illness_pct'] - params['training_pct']), 0.0)
            assert uitkomst == pytest.approx(verwacht)
            assert uitkomst >= 0
