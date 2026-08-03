from types import SimpleNamespace

import pytest

from modules.models import LineType, PlanningRow
from ui.engine_rebuild import (
    build_clean_engine_for_session,
    get_config_overrides,
    get_session_config_overrides,
    install_clean_engine_baseline,
)
import ui.engine_rebuild as engine_rebuild


pytestmark = pytest.mark.no_fixture


def _row():
    return PlanningRow(
        material_number="MAT-1",
        material_name="Material 1",
        product_type="Bulk Product",
        product_family="Family",
        spc_product="SPC",
        product_cluster="Cluster",
        product_name="Product",
        line_type=LineType.DEMAND_FORECAST.value,
        values={"2025-12": 10.0},
    )


def _engine():
    machine = SimpleNamespace(
        oee=0.8,
        availability_by_period={"2025-12": 0.9},
        shift_hours_override=None,
    )
    return SimpleNamespace(
        data=SimpleNamespace(
            machines={"M1": machine},
            purchased_and_produced={"MAT-1": 0.5},
            valuation_params=None,
        ),
        results={LineType.DEMAND_FORECAST.value: [_row()]},
        value_results={},
    )


def test_get_config_overrides_returns_known_keys():
    # Storeless (de autouse-fixture isoleert de masterstore naar een niet-
    # bestaand pad): legacy globals gelden onverkort.
    global_config = {
        "site": "NLX1",
        "forecast_months": 12,
        "unlimited_machines": "M1",
        "forecast_align_to_month": False,
        "purchased_and_produced": "MAT-1:0.5",
    }

    overrides = get_config_overrides(global_config)

    assert overrides["site"] == "NLX1"
    assert overrides["forecast_months"] == 12
    assert overrides["unlimited_machines"] == "M1"
    assert overrides["forecast_align_to_month"] is False
    assert overrides["purchased_and_produced"] == "MAT-1:0.5"


def _seed_master_store(tmp_path, months=18):
    # Minimale echte masterstore op het geisoleerde pad (conftest herstelt).
    import json

    from modules.master_data import serialize_master
    from tests.test_master_data import fake_master_loader
    from ui import master_store

    master = json.loads(json.dumps(serialize_master(fake_master_loader()),
                                   default=str))
    master['config']['forecast_months'] = months
    path = tmp_path / 'gating_master_store.json'
    master_store.save_master_store(path, master, source_filename='seed.xlsm')
    master_store.set_store_path(path)
    return master


def test_get_config_overrides_store_gates_legacy_globals(tmp_path):
    # Met een masterstore zijn de masterdata-tabellen de bron van waarheid:
    # achtergebleven legacy globals (oude Config-kaart) mogen site, unlimited,
    # align en months niet meer overschaduwen; de storehorizon stuurt de load.
    _seed_master_store(tmp_path, months=18)

    overrides = get_config_overrides({
        "site": "NLX9",
        "forecast_months": 12,
        "unlimited_machines": "M1",
        "forecast_align_to_month": False,
    })

    assert "site" not in overrides
    assert "unlimited_machines" not in overrides
    assert "forecast_align_to_month" not in overrides
    assert overrides["forecast_months"] == 18


def test_session_overrides_with_store_drop_engine_snapshots(tmp_path):
    # Met masterstore: masterdata-tabellen zijn de bron voor VP en de PAP-
    # default. De engine-snapshot (met de OUDE masterwaarden) mag dus niet
    # als override terugkomen — anders bereikt een master-wijziging
    # bestaande sessies nooit en resurrecteert een verwijderde PAP-split.
    _seed_master_store(tmp_path)
    sess = {"engine": _engine()}  # engine heeft PAP- en (geen) VP-snapshot

    ov = get_session_config_overrides(sess, {})
    assert "purchased_and_produced" not in ov
    assert "valuation_params" not in ov

    # Sessie-eigen wat-als blijft winnen ('' = bewust leeggemaakt).
    sess["purchased_and_produced"] = "MAT-1:0.9"
    assert get_session_config_overrides(sess, {})["purchased_and_produced"] == "MAT-1:0.9"
    sess["purchased_and_produced"] = ""
    assert get_session_config_overrides(sess, {})["purchased_and_produced"] == ""

    # Global-spiegel (laatst actieve sessie) besmet geen verse sessies.
    ov = get_session_config_overrides({"engine": None},
                                      {"purchased_and_produced": "MAT-9:0.1",
                                       "valuation_params": {"1": "5"}})
    assert "purchased_and_produced" not in ov
    assert "valuation_params" not in ov


def test_session_overrides_storeless_keep_engine_first_vp():
    # Storeless (geen record op het geisoleerde pad): gedrag van vanouds —
    # de engine-snapshot is de beste bron, de global de terugval.
    sess = {"engine": _engine()}
    ov = get_session_config_overrides(sess, {"purchased_and_produced": "MAT-9:0.1"})
    assert ov["purchased_and_produced"] == "MAT-1:0.5"  # engine-snapshot wint


def test_resolve_months_forecast_prefers_store_then_global_then_params(tmp_path):
    # Het tweede horizonkanaal (build_clean_engine_for_session) volgt dezelfde
    # bronregel als get_config_overrides: store > legacy global (alleen
    # storeless) > sessieparameter.
    assert engine_rebuild.resolve_months_forecast(
        {"months_forecast": 12}, {"forecast_months": 18}) == 18
    assert engine_rebuild.resolve_months_forecast(
        {"months_forecast": 12}, {}) == 12
    _seed_master_store(tmp_path, months=24)
    assert engine_rebuild.resolve_months_forecast(
        {"months_forecast": 12}, {"forecast_months": 18}) == 24


def test_get_config_overrides_omits_missing_keys():
    overrides = get_config_overrides({})

    assert overrides == {}


def test_get_config_overrides_includes_nonzero_valuation_params():
    overrides = get_config_overrides({"valuation_params": {"1": "0", "2": "12.5"}})

    assert overrides["valuation_params"] == {"1": "0", "2": "12.5"}


def test_get_session_config_overrides_merges_session_engine_state_into_global():
    vp = SimpleNamespace(
        direct_fte_cost_per_month=1.0,
        indirect_fte_cost_per_month=2.0,
        overhead_cost_per_month=3.0,
        sga_cost_per_month=4.0,
        depreciation_per_year=5.0,
        net_book_value=6.0,
        days_sales_outstanding=7.0,
        days_payable_outstanding=8.0,
    )
    sess = {
        "engine": SimpleNamespace(
            data=SimpleNamespace(
                valuation_params=vp,
                purchased_and_produced={"MAT-1": 0.5},
            ),
        ),
    }
    global_config = {"site": "NLX1", "forecast_months": 12}

    overrides = get_session_config_overrides(sess, global_config)

    assert overrides["site"] == "NLX1"
    assert overrides["forecast_months"] == 12
    assert overrides["valuation_params"]["1"] == pytest.approx(1.0)
    assert overrides["purchased_and_produced"] == "MAT-1:0.5"


def test_get_session_config_overrides_uses_session_valuation_without_engine():
    sess = {"parameters": None, "valuation_params": {"1": 2.0}}

    overrides = get_session_config_overrides(sess, {"site": "NLX2"})

    assert overrides["site"] == "NLX2"
    assert overrides["valuation_params"] == {"1": 2.0}


def test_get_session_config_overrides_uses_global_without_session_params():
    sess = {"parameters": None}

    overrides = get_session_config_overrides(sess, {"site": "NLX2"})

    assert overrides["site"] == "NLX2"


def test_get_session_config_overrides_accepts_none_session():
    assert get_session_config_overrides(None, {"site": "NLX2"}) == {"site": "NLX2"}


def test_build_clean_engine_for_session_returns_none_without_params():
    assert build_clean_engine_for_session({"file_path": "unused"}, {}) is None


def test_build_clean_engine_for_session_constructs_and_runs_planning_engine(monkeypatch):
    calls = []

    class RecordingPlanningEngine:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.run_called = False
            calls.append(self)

        def run(self):
            self.run_called = True

    monkeypatch.setattr(engine_rebuild, "PlanningEngine", RecordingPlanningEngine)
    sess = {
        "file_path": "workbook.xlsm",
        "extract_files": ["extract.xlsx"],
        "parameters": {
            "planning_month": "2026-01",
            "months_actuals": "6",
            "months_forecast": "9",
        },
    }

    engine = build_clean_engine_for_session(sess, {"site": "NLX1", "forecast_months": 12})

    assert engine is calls[0]
    assert engine.run_called is True
    assert engine.args == ("workbook.xlsm",)
    assert engine.kwargs["planning_month"] == "2026-01"
    assert engine.kwargs["months_actuals"] == 6
    assert engine.kwargs["months_forecast"] == 12
    assert engine.kwargs["extract_files"] == ["extract.xlsx"]
    assert engine.kwargs["config_overrides"]["site"] == "NLX1"


def test_install_clean_engine_baseline_captures_snapshot_and_clears_overrides():
    sess = {
        "machine_overrides": {"M1": {"oee": 0.9}},
        "machine_undo": [{"machine": "M1"}],
        "machine_redo": [{"machine": "M1"}],
    }

    install_clean_engine_baseline(sess, _engine(), lambda machine, data: 520.0, clear_machine_overrides=True)

    assert "reset_baseline" in sess
    assert sess["reset_baseline"]["machines"]["M1"]["shift_hours_computed"] == pytest.approx(520.0)
    assert sess["machine_overrides"] == {}
    assert sess["machine_undo"] == []
    # Current production behavior invalidates machine_undo only; machine_redo is untouched.
    assert sess["machine_redo"] == [{"machine": "M1"}]


def test_install_clean_engine_baseline_preserves_overrides_when_flag_false():
    sess = {
        "machine_overrides": {"M1": {"oee": 0.9}},
        "machine_undo": [{"machine": "M1"}],
    }

    install_clean_engine_baseline(sess, _engine(), lambda machine, data: 520.0, clear_machine_overrides=False)

    assert "reset_baseline" in sess
    assert sess["machine_overrides"] == {"M1": {"oee": 0.9}}
    assert sess["machine_undo"] == []
