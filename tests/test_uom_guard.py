"""UoM guard: kg-in-ton BOM detection, overrides, and the decision store.

Synthetic fixtures modeled on the June 2026 Winterswijk incident: slurry
recipes dosing additives in kg (ACTICIDE/OMNIVAAD/POLYMER pattern) while the
site plans in tons, which inflated dependent demand ~1000x and consolidated
to a -9.1M EUR inventory value. No client data is used.
"""

import pytest

from modules.models import BOMItem
from modules.uom_guard import (
    SUSPECT_TOTAL,
    analyze_bom,
    apply_uom_overrides,
)

pytestmark = pytest.mark.no_fixture


def _item(parent, component, qty_per, name='', coproduct=False, uom=None, pv='PV01'):
    return BOMItem(
        plant='NLK1', parent_material=parent, parent_name=f'{parent} name',
        component_material=component, component_name=name or f'{component} name',
        quantity_per=qty_per, bom_header_quantity=1.0,
        is_coproduct=coproduct, production_version=pv, component_uom=uom,
    )


def test_clean_ton_recipe_has_no_suspects():
    bom = [_item('P1', 'BULK-A', 0.6), _item('P1', 'BULK-B', 0.45)]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


def test_wsk_slurry_case_flags_exactly_the_kg_components():
    # The real June pattern: bulk ~1 t/t, additives 1.3-5 "t"/t (really kg),
    # process water 287 "t"/t (really kg/l). Bulk must survive.
    bom = [
        _item('SLURRY', 'BULK', 1.0),
        _item('SLURRY', 'ACTICIDE', 1.9),
        _item('SLURRY', 'OMNIVAAD', 5.0),
        _item('SLURRY', 'POLYMER', 1.3),
        _item('SLURRY', 'WATER', 287.0),
    ]
    suspects, warnings = analyze_bom(bom)
    flagged = {s.component_material for s in suspects}
    assert flagged == {'ACTICIDE', 'OMNIVAAD', 'POLYMER', 'WATER'}
    assert warnings == []
    # Largest offender first, and the proposal is the kg->ton factor.
    assert suspects[0].component_material == 'WATER'
    assert all(s.proposed_factor == 0.001 for s in suspects)


def test_piece_goods_rider_below_threshold_stays_clean():
    # Pallets/containers ride on top of the mass balance in small numbers.
    bom = [_item('P1', 'BULK', 1.0), _item('P1', 'PALLET', 0.3)]
    suspects, _ = analyze_bom(bom)
    assert suspects == []


def test_packaging_components_from_master_stay_outside_the_balance():
    # Real June false-positive pattern: big bags at 2/ton pushed packaged
    # recipes over the threshold and got flagged themselves. With the master
    # marking them as packaging they must vanish from the analysis entirely.
    bom = [
        _item('PACKED', 'BULK', 1.0),
        _item('PACKED', 'BIGBAG', 2.0),
        _item('PACKED', 'PALLET', 0.5),
    ]
    suspects, warnings = analyze_bom(bom, piece_components={'BIGBAG', 'PALLET'})
    assert suspects == []
    assert warnings == []


def test_coproduct_mass_counts_as_output():
    # Sieve-residue pattern: 6.67 t input yields 1 t product + 5.67 t
    # coproduct. The recipe is in balance and must stay clean.
    bom = [
        _item('RESIDUE', 'ORE', 6.67),
        _item('RESIDUE', 'MAIN', -5.67, coproduct=True),
    ]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


def test_kg_component_still_flagged_when_coproducts_present():
    # Output scaling must not blind the guard: a kg-dosed additive in a
    # coproduct recipe is still ~1000x the plausible total.
    bom = [
        _item('RESIDUE', 'ORE', 6.67),
        _item('RESIDUE', 'ADDITIVE', 40.0),
        _item('RESIDUE', 'MAIN', -5.67, coproduct=True),
    ]
    suspects, _ = analyze_bom(bom)
    assert [s.component_material for s in suspects] == ['ADDITIVE']


def test_coproducts_never_participate():
    bom = [
        _item('P1', 'BULK', 1.0),
        _item('P1', 'COPROD', -0.4, coproduct=True),
        _item('P1', 'COPROD2', 3.0, coproduct=True),
    ]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


def test_single_oversized_component_is_not_gutted_but_warned():
    # One component at 2.0 t/t: converting it would leave 0.002 (< lower
    # bound), so it must NOT be flagged — but the recipe stays implausible
    # and must be surfaced as a warning instead of silently passing.
    bom = [_item('P1', 'ORE', 2.0)]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert len(warnings) == 1
    assert warnings[0].parent_material == 'P1'
    assert warnings[0].total_ratio == pytest.approx(2.0)


def test_mildly_imbalanced_recipe_warns_without_suspects():
    # Real Maastricht pattern: a blend summing to 1.56 t/t. Odd enough to
    # surface, too mild to accuse a component (that band is dominated by
    # yield-loss recipes, not kg entries).
    bom = [_item('BLEND', 'HUNTITE', 1.3), _item('BLEND', 'MAGNESITE', 0.26)]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert len(warnings) == 1
    assert warnings[0].total_ratio == pytest.approx(1.56)


def test_component_aggregates_across_recipes():
    bom = [
        _item('P1', 'BULK', 1.0), _item('P1', 'ADDITIVE', 5.0),
        _item('P2', 'BULK', 1.0), _item('P2', 'ADDITIVE', 3.0),
    ]
    suspects, _ = analyze_bom(bom)
    assert len(suspects) == 1
    assert suspects[0].component_material == 'ADDITIVE'
    assert {r.parent_material for r in suspects[0].recipes} == {'P1', 'P2'}
    assert suspects[0].max_ratio == pytest.approx(5.0)


def test_alternative_boms_balance_independently():
    # Real June false-positive pattern: one parent, one PV, three alternative
    # BOMs of ~1.0 each. Grouped naively they read as a 3.0 recipe.
    bom = []
    for alt, (lime, carb) in enumerate([(0.06, 0.94), (0.02, 0.98), (0.04, 0.96)], start=1):
        for comp, qty in (('LIME', lime), ('CARB', carb)):
            item = _item('COMPOSITE', comp, qty)
            item.bill_of_material = '00001234'
            item.alternative_bom = str(alt)
            bom.append(item)
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


def test_recipes_are_grouped_per_production_version():
    # PV01 is broken, PV02 is fine: only the PV01 line may be flagged.
    bom = [
        _item('P1', 'BULK', 1.0, pv='PV01'), _item('P1', 'ADDITIVE', 5.0, pv='PV01'),
        _item('P1', 'BULK', 1.0, pv='PV02'), _item('P1', 'ADDITIVE', 0.005, pv='PV02'),
    ]
    suspects, _ = analyze_bom(bom)
    assert len(suspects) == 1
    assert [r.production_version for r in suspects[0].recipes] == ['PV01']


def test_trusted_mass_uom_rows_are_never_flagged():
    # Loader already converted this KG row; it counts toward the balance but
    # is exempt from flagging even though the recipe total is fine.
    bom = [
        _item('P1', 'BULK', 1.0, uom='TO'),
        _item('P1', 'ADDITIVE', 0.005, uom='KG'),
    ]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


def test_piece_uom_rows_stay_outside_the_mass_balance():
    # 3 PC per ton would push the naive total over the threshold; a known
    # piece unit must keep the recipe clean.
    bom = [_item('P1', 'BULK', 1.0), _item('P1', 'CONTAINER', 3.0, uom='PC')]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


def test_apply_overrides_and_reanalyze_is_idempotent():
    bom = [
        _item('SLURRY', 'BULK', 1.0),
        _item('SLURRY', 'ACTICIDE', 1.9),
        _item('SLURRY', 'OMNIVAAD', 5.0),
    ]
    applied = apply_uom_overrides(bom, {'ACTICIDE': 0.001, 'OMNIVAAD': 0.001})
    assert sorted(applied) == [('ACTICIDE', 0.001, 1), ('OMNIVAAD', 0.001, 1)]
    acticide = next(i for i in bom if i.component_material == 'ACTICIDE')
    assert acticide.quantity_per == pytest.approx(0.0019)
    # Converted doses are plausible now: nothing left to flag.
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


def test_apply_overrides_reports_zero_rows_for_absent_components():
    bom = [_item('P1', 'BULK', 1.0)]
    applied = apply_uom_overrides(bom, {'GONE': 0.001})
    assert applied == [('GONE', 0.001, 0)]
    assert bom[0].quantity_per == pytest.approx(1.0)


def test_neutral_factors_are_skipped():
    bom = [_item('P1', 'BULK', 1.0)]
    assert apply_uom_overrides(bom, {'BULK': 1}) == []
    assert apply_uom_overrides(bom, {'BULK': 0}) == []
    assert bom[0].quantity_per == pytest.approx(1.0)


def test_threshold_boundary_is_exclusive():
    bom = [_item('P1', 'BULK', SUSPECT_TOTAL)]
    suspects, warnings = analyze_bom(bom)
    assert suspects == []
    assert warnings == []


class TestUomStore:
    @pytest.fixture(autouse=True)
    def _store(self, tmp_path):
        from ui import uom_store
        uom_store.set_store_path(tmp_path / 'uom_overrides.json')
        yield
        uom_store.set_store_path(tmp_path / 'gone.json')

    def test_convert_dismiss_clear_roundtrip(self):
        from ui import uom_store
        uom_store.record_decisions([
            {'component': 'A', 'action': 'convert', 'factor': 0.001},
            {'component': 'B', 'action': 'dismiss'},
        ])
        assert uom_store.get_confirmed_overrides() == {'A': 0.001}
        assert uom_store.get_dismissed() == {'B': True}

        # A dismissal replaces an earlier conversion and vice versa.
        uom_store.record_decisions([{'component': 'A', 'action': 'dismiss'}])
        assert uom_store.get_confirmed_overrides() == {}
        assert uom_store.get_dismissed() == {'A': True, 'B': True}

        uom_store.record_decisions([
            {'component': 'A', 'action': 'clear'},
            {'component': 'B', 'action': 'clear'},
        ])
        assert uom_store.get_confirmed_overrides() == {}
        assert uom_store.get_dismissed() == {}

    def test_persists_across_reload(self, tmp_path):
        from ui import uom_store
        uom_store.record_decisions([{'component': 'A', 'action': 'convert', 'factor': 0.001}])
        # Fresh module state: same path, cache cleared.
        uom_store.set_store_path(tmp_path / 'uom_overrides.json')
        assert uom_store.get_confirmed_overrides() == {'A': 0.001}

    def test_invalid_decisions_are_ignored(self):
        from ui import uom_store
        uom_store.record_decisions([{'component': 'A', 'action': 'convert', 'factor': 0.001}])
        uom_store.record_decisions([
            {'component': '', 'action': 'convert'},
            {'component': 'X', 'action': 'nonsense'},
            {'component': 'Y', 'action': 'convert', 'factor': 'abc'},
            # Een ongeldige factor mag een bestaande override niet stil
            # verwijderen en al helemaal niet stil 0.001 worden.
            {'component': 'A', 'action': 'convert', 'factor': 0},
            {'component': 'A', 'action': 'convert', 'factor': -1},
        ])
        assert uom_store.get_confirmed_overrides() == {'A': 0.001}

    def test_missing_store_file_is_empty(self):
        from ui import uom_store
        assert uom_store.get_confirmed_overrides() == {}
        assert uom_store.get_dismissed() == {}


def test_override_skips_rows_with_authoritative_mass_uom():
    """Review-fix R1: zodra het extract een UoM-kolom krijgt is de rij al
    bij inladen geconverteerd; de opgeslagen factor mag hem niet nogmaals
    x0.001 doen (dosering zou 1.000.000x te klein worden)."""
    bom = [
        _item('P1', 'ADDITIVE', 0.0019, uom='KG'),   # loader-geconverteerd
        _item('P2', 'ADDITIVE', 1.9),                # oude stijl, geen UoM
    ]
    applied = apply_uom_overrides(bom, {'ADDITIVE': 0.001})
    assert applied == [('ADDITIVE', 0.001, 1)]
    assert bom[0].quantity_per == pytest.approx(0.0019)   # onaangeroerd
    assert bom[1].quantity_per == pytest.approx(0.0019)   # geconverteerd


def test_small_genuine_bulk_survives_unresolvable_recipe():
    """Review-fix R5: een klein, op zichzelf plausibel component waarvan
    conversie het recept niet eens plausibel maakt, is echte bulk en mag
    niet geflagd worden — ook niet als het recept onopgelost blijft."""
    bom = [
        _item('P1', 'WATER', 1000.0),
        _item('P1', 'ADDITIVE', 400.0),
        _item('P1', 'BULK', 0.3),
    ]
    suspects, warnings = analyze_bom(bom)
    flagged = {s.component_material for s in suspects}
    assert 'BULK' not in flagged
    assert flagged == {'WATER', 'ADDITIVE'}
    assert len(warnings) == 1  # recept blijft eerlijk gemarkeerd als onopgelost


def test_multi_small_kg_imbalance_flags_all_offenders():
    """Codereview 2026-08-02: de bulk-veto blokkeerde ELKE kandidaat zodra
    de scheefstand over 2+ kleine kg-regels verdeeld was (elk item alleen
    lost het recept niet op) — nul verdachten voor precies de doelklasse.
    De veto geldt nu alleen als ook de resterende kandidaten samen het
    recept niet plausibel krijgen."""
    bom = [
        _item('P1', 'BULK', 0.9),
        _item('P1', 'ADD-A', 1.2),
        _item('P1', 'ADD-B', 1.1),
    ]
    suspects, warnings = analyze_bom(bom)
    flagged = {s.component_material for s in suspects}
    assert flagged == {'ADD-A', 'ADD-B'}
    assert 'BULK' not in flagged
    assert warnings == []


def test_override_never_touches_piece_uom_rows():
    """Codereview: de heroverride-vrijstelling gold alleen voor massa-
    eenheden; een als kg bevestigd component dat later met PC-regels
    terugkomt werd alsnog x0.001 gedaan. Elke autoritatieve eenheid is
    vrijgesteld."""
    bom = [_item('P1', 'COMP', 2.0, uom='PC')]
    applied = apply_uom_overrides(bom, {'COMP': 0.001})
    assert applied == [('COMP', 0.001, 0)]
    assert bom[0].quantity_per == pytest.approx(2.0)


class TestUomStoreHardening:
    @pytest.fixture(autouse=True)
    def _store(self, tmp_path):
        from ui import uom_store
        uom_store.set_store_path(tmp_path / 'uom.json')
        yield

    def test_nan_and_inf_factors_rejected(self):
        """Codereview: NaN glipte door de <=0-check (NaN <= 0 is False) en
        vergiftigde via quantity_per *= NaN de hele planning."""
        from ui import uom_store
        uom_store.record_decisions([{'component': 'A', 'action': 'convert', 'factor': 0.001}])
        uom_store.record_decisions([
            {'component': 'A', 'action': 'convert', 'factor': float('nan')},
            {'component': 'B', 'action': 'convert', 'factor': float('inf')},
        ])
        assert uom_store.get_confirmed_overrides() == {'A': 0.001}

    def test_generation_bumps_on_decisions(self):
        from ui import uom_store
        g0 = uom_store.generation()
        uom_store.record_decisions([{'component': 'A', 'action': 'convert', 'factor': 0.001}])
        assert uom_store.generation() == g0 + 1
