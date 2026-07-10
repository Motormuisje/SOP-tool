"""Unit tests for CapacityEngine user overrides on L7/L9/L11/L12 + L10 recalc.

Self-contained: stubs DataLoader/Material/Machine with minimal data so no
Excel fixture or DB load is needed.
"""

import copy
from types import SimpleNamespace

import pytest

from modules.capacity_engine import CapacityEngine
from modules.models import (
    LineType,
    Machine,
    MachineGroup,
    Material,
    PlanningConfig,
    ProductType,
    ShiftSystem,
)
from datetime import datetime


PERIODS = ["2026-01", "2026-02", "2026-03"]
MAT = "MAT-1"
MACHINE_CODE = "PML10"
MACHINE_ID = "Z_MACH10"
GROUP = "ZZ_GROUP1"


def _make_data():
    """Build a minimal DataLoader-like stub with one machine, one group,
    and one material that routes through the machine.
    """
    material = Material(
        material_number=MAT,
        name="Test material",
        product_type=ProductType.PACKAGED_PRODUCT,
        product_family="FAM",
    )
    group_marker = Material(
        material_number=GROUP,
        name="Group marker",
        product_type=ProductType.OTHER,
        product_family="FAM",
    )
    machine = Machine(
        machine_id=MACHINE_ID,
        machine_code=MACHINE_CODE,
        name="Mill 10",
        oee=1.0,
        machine_group=GROUP,
        availability_by_period={p: 0.9 for p in PERIODS},
        shift_system=ShiftSystem.THREE_SHIFT,
    )
    routing = SimpleNamespace(
        plant="P1",
        material=MAT,
        material_description="x",
        work_center=MACHINE_CODE,
        base_quantity=1.0,
        standard_time=1.0,
        production_version=None,
    )
    config = PlanningConfig(
        initial_date=datetime(2026, 1, 1),
        forecast_months=3,
        site="NLX1",
    )
    data = SimpleNamespace(
        config=config,
        periods=list(PERIODS),
        materials={MAT: material, GROUP: group_marker},
        bom=[],
        machines={MACHINE_CODE: machine},
        machine_groups={GROUP: MachineGroup(group_id=GROUP, machine_codes=[MACHINE_CODE])},
        shift_hours={
            "2-shift system": 347.0,
            "3-shift system": 520.0,
            "24/7 production": 730.0,
        },
        default_shift_name="3-shift system",
        fte_hours_per_year=1492.0,
        get_all_routings=lambda m: [routing] if m == MAT else [],
    )
    return data


def _production_plan():
    # 100 units per period — with base_qty=1, std_time=1 → 100 hours per period.
    return {MAT: {p: 100.0 for p in PERIODS}}


def _row_values(rows, material_number):
    for r in rows:
        if r.material_number == material_number:
            return r.values
    return None


@pytest.mark.no_fixture
def test_no_overrides_baseline():
    """overrides=None must behave identically to overrides={}."""
    data = _make_data()
    eng_a = CapacityEngine(data, _production_plan())
    eng_b = CapacityEngine(data, _production_plan(), overrides={})
    eng_a.calculate()
    eng_b.calculate()
    for attr in ("rows_07_cap", "rows_09", "rows_10", "rows_11", "rows_12"):
        a_vals = [(r.material_number, dict(r.values)) for r in getattr(eng_a, attr)]
        b_vals = [(r.material_number, dict(r.values)) for r in getattr(eng_b, attr)]
        assert a_vals == b_vals, f"{attr} diverged"


@pytest.mark.no_fixture
def test_l7_override_changes_only_target_cell():
    data = _make_data()
    baseline = CapacityEngine(data, _production_plan())
    baseline.calculate()
    baseline_l7 = copy.deepcopy(baseline.rows_07_cap)

    overrides = {
        LineType.CAPACITY_UTILIZATION.value: {
            GROUP: {PERIODS[1]: 999.0},
        }
    }
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    overridden = _row_values(eng.rows_07_cap, GROUP)
    assert overridden[PERIODS[1]] == 999.0
    # Other periods untouched on the group row
    base_group = _row_values(baseline_l7, GROUP)
    assert overridden[PERIODS[0]] == base_group[PERIODS[0]]
    assert overridden[PERIODS[2]] == base_group[PERIODS[2]]
    # Material-level and machine-level rows untouched (override is group-only)
    base_mat = _row_values(baseline_l7, MAT)
    new_mat = _row_values(eng.rows_07_cap, MAT)
    assert new_mat == base_mat


@pytest.mark.no_fixture
def test_l9_override_changes_only_target_cell():
    data = _make_data()
    baseline = CapacityEngine(data, _production_plan())
    baseline.calculate()
    base_avail = copy.deepcopy(_row_values(baseline.rows_09, MACHINE_ID))

    overrides = {
        LineType.AVAILABLE_CAPACITY.value: {
            MACHINE_ID: {PERIODS[0]: 0.5},
        }
    }
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    new = _row_values(eng.rows_09, MACHINE_ID)
    assert new[PERIODS[0]] == 0.5
    assert new[PERIODS[1]] == base_avail[PERIODS[1]]
    assert new[PERIODS[2]] == base_avail[PERIODS[2]]


@pytest.mark.no_fixture
def test_l11_override_changes_only_target_cell():
    data = _make_data()
    baseline = CapacityEngine(data, _production_plan())
    baseline.calculate()
    base = copy.deepcopy(_row_values(baseline.rows_11, GROUP))

    overrides = {
        LineType.SHIFT_AVAILABILITY.value: {
            GROUP: {PERIODS[2]: 600.0},
        }
    }
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    new = _row_values(eng.rows_11, GROUP)
    assert new[PERIODS[2]] == 600.0
    assert new[PERIODS[0]] == base[PERIODS[0]]
    assert new[PERIODS[1]] == base[PERIODS[1]]


@pytest.mark.no_fixture
def test_l12_override_changes_only_target_cell():
    data = _make_data()
    baseline = CapacityEngine(data, _production_plan())
    baseline.calculate()
    base = copy.deepcopy(_row_values(baseline.rows_12, GROUP))

    overrides = {
        LineType.FTE_REQUIREMENTS.value: {
            GROUP: {PERIODS[0]: 7.5},
        }
    }
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    new = _row_values(eng.rows_12, GROUP)
    assert new[PERIODS[0]] == 7.5
    assert new[PERIODS[1]] == base[PERIODS[1]]
    assert new[PERIODS[2]] == base[PERIODS[2]]


@pytest.mark.no_fixture
def test_l10_recomputed_after_l7_l9_overrides():
    """L10 = cap_util / (shift_hours * availability) per machine.

    Overriding the L7 group hours and L9 machine availability must propagate to
    L10. The single-machine fixture makes the group override unambiguous.
    """
    data = _make_data()
    overrides = {
        LineType.CAPACITY_UTILIZATION.value: {
            GROUP: {PERIODS[0]: 200.0},
        },
        LineType.AVAILABLE_CAPACITY.value: {
            MACHINE_ID: {PERIODS[0]: 0.5},
        },
    }
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    # L10 row is keyed by machine_id, machine_code on the row.material_name.
    l10 = _row_values(eng.rows_10, MACHINE_ID)
    # Overridden group cap-util hours = 200; this fixture has one machine in
    # the group, so the machine-level utilization uses 200 hours.
    # Shift hours = 520, overridden availability = 0.5.
    expected = 200.0 / (520.0 * 0.5)
    assert l10[PERIODS[0]] == pytest.approx(expected)


@pytest.mark.no_fixture
def test_l7_override_recomputes_l12_from_group_hours():
    data = _make_data()
    overrides = {
        LineType.CAPACITY_UTILIZATION.value: {
            GROUP: {PERIODS[0]: 200.0},
        },
    }
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    l12 = _row_values(eng.rows_12, GROUP)
    expected = 200.0 / (data.fte_hours_per_year / 12)
    assert l12[PERIODS[0]] == pytest.approx(expected)


@pytest.mark.no_fixture
def test_l11_override_recomputes_l10_but_not_l12():
    data = _make_data()
    baseline = CapacityEngine(data, _production_plan())
    baseline.calculate()
    base_l12 = copy.deepcopy(_row_values(baseline.rows_12, GROUP))

    overrides = {
        LineType.SHIFT_AVAILABILITY.value: {
            GROUP: {PERIODS[0]: 400.0},
        },
    }
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    l10 = _row_values(eng.rows_10, MACHINE_ID)
    expected = 100.0 / (400.0 * 0.9)
    assert l10[PERIODS[0]] == pytest.approx(expected)
    assert _row_values(eng.rows_12, GROUP) == base_l12


@pytest.mark.no_fixture
def test_override_on_unknown_code_is_silent():
    data = _make_data()
    overrides = {
        LineType.CAPACITY_UTILIZATION.value: {
            "ZZ_DOES_NOT_EXIST": {PERIODS[0]: 12345.0},
        },
        LineType.FTE_REQUIREMENTS.value: {
            "ZZ_NOPE": {PERIODS[0]: 99.0},
        },
    }
    # Just verify no exception and existing rows are unchanged.
    eng_no = CapacityEngine(data, _production_plan())
    eng_no.calculate()
    eng = CapacityEngine(data, _production_plan(), overrides=overrides)
    eng.calculate()

    for attr in ("rows_07_cap", "rows_09", "rows_10", "rows_11", "rows_12"):
        a_vals = [(r.material_number, dict(r.values)) for r in getattr(eng_no, attr)]
        b_vals = [(r.material_number, dict(r.values)) for r in getattr(eng, attr)]
        assert a_vals == b_vals
