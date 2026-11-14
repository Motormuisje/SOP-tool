"""Load warnings: what the loader used to tell only the console.

A sheet that cannot be read or a cell that falls back to a default does not
make the numbers wrong, but the planner must know on which assumption the run
rests. These tests pin two things per case: the fallback number is the one the
loader always used (no silent numeric change), and the warning is recorded.
"""

from types import SimpleNamespace

import pandas as pd
import pytest
from flask import Flask

from tests.test_data_loader_errors import _loader
from ui.routes.read import create_read_blueprint


pytestmark = pytest.mark.no_fixture


def _messages(loader, source=None):
    return [
        w["message"] for w in getattr(loader, "load_warnings", [])
        if source is None or w["source"] == source
    ]


def _machines_frame(rows):
    return pd.DataFrame(rows, columns=["Machine code", "MachineID", "Machine name", "Machine group", "OEE (%)"])


def test_missing_config_sheet_is_a_clear_error_not_invented_anchors(monkeypatch):
    """BUGS.md M2. The old fallback (December 2025, NLX1) left
    forecast_actuals_months unset, so the run died later on an AttributeError.
    The loader now says what is wrong."""
    loader = _loader()

    def _no_sheet(*args, **kwargs):
        raise ValueError("Worksheet named 'Config' not found")

    monkeypatch.setattr(pd, "read_excel", _no_sheet)

    with pytest.raises(ValueError, match="Config-sheet ontbreekt of is onleesbaar"):
        loader._load_config()


def test_blank_oee_keeps_the_numbers_and_is_reported(monkeypatch):
    """BUGS.md M3. A blank OEE cell was NaN; every capacity formula guards with
    `oee > 0`, so hours were computed as with 100%. Same number now, without
    the NaN in the machines JSON, and the planner is told."""
    loader = _loader()
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _machines_frame([
        ["M-BLANK", "M-BLANK", "Blank", "G1", float("nan")],
        ["M-85", "M-85", "Percent", "G1", 85],
        ["M-FRAC", "M-FRAC", "Fraction", "G1", 0.9],
    ]))

    loader._load_machines()

    assert loader.machines["M-BLANK"].oee == 1.0
    assert loader.machines["M-85"].oee == pytest.approx(0.85)
    assert loader.machines["M-FRAC"].oee == pytest.approx(0.9)
    warnings = _messages(loader, "OEE + Machine groups")
    assert len(warnings) == 1
    assert "M-BLANK" in warnings[0] and "100%" in warnings[0]


def test_duplicate_machine_row_is_reported_and_grouping_is_unchanged(monkeypatch):
    """BUGS.md L5: detection only. The last row still wins and the group still
    lists the code once per row; counting it once would be a change in numbers
    for workbooks that carry such a row."""
    loader = _loader()
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _machines_frame([
        ["M1", "M1", "First", "G1", 0.8],
        ["M1", "M1", "Second", "G1", 0.6],
    ]))

    loader._load_machines()

    assert loader.machines["M1"].oee == pytest.approx(0.6)
    assert loader.machine_groups["G1"].machine_codes == ["M1", "M1"]
    warnings = _messages(loader, "OEE + Machine groups")
    assert len(warnings) == 1 and "M1" in warnings[0]


def test_unreadable_purchase_values_fall_back_to_one_and_are_reported(monkeypatch):
    loader = _loader()
    loader.purchase_moq = {}
    loader.purchase_sheet_materials = set()
    frame = pd.DataFrame([
        ["Material number", None, None, "Lead time", None, None, None, "MOQ"],
        ["MAT-OK", None, None, 2, None, None, None, 500],
        ["MAT-BAD", None, None, "twee", None, None, None, "veel"],
        ["MAT-BLANK", None, None, None, None, None, None, None],
    ])
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: frame)

    loader._load_purchase_sheet()

    assert loader.purchase_lead_times == {"MAT-OK": 2, "MAT-BAD": 1, "MAT-BLANK": 1}
    assert loader.purchase_moq == {"MAT-OK": 500.0, "MAT-BAD": 1.0, "MAT-BLANK": 1.0}
    warnings = _messages(loader, "Purchase sheet")
    # Unreadable is reported; blank is the documented default and is not.
    assert len(warnings) == 1
    assert "2 waarde(n)" in warnings[0] and "MAT-BAD" in warnings[0]
    assert "MAT-BLANK" not in warnings[0]


def test_unreadable_purchase_sheet_is_reported(monkeypatch):
    loader = _loader()
    loader.purchase_moq = {}
    loader.purchase_sheet_materials = set()

    def _broken(*args, **kwargs):
        raise ValueError("Worksheet named 'Purchase sheet' not found")

    monkeypatch.setattr(pd, "read_excel", _broken)

    loader._load_purchase_sheet()

    assert loader.purchase_lead_times == {}
    warnings = _messages(loader, "Purchase sheet")
    assert len(warnings) == 1 and "niet (volledig) gelezen" in warnings[0]


def _price_frame(volume_column):
    return pd.DataFrame(
        [["MAT-A", "NLX1", 100.0, 2500.0], ["MAT-B", "NLX1", 50.0, 1000.0]],
        columns=["ProductId", "PlantCode", volume_column, "ExWorks Revenue"])


def test_price_sheet_without_the_volume_column_is_reported(monkeypatch):
    # A newer price sheet that names the column after its own year gave every
    # material a price of nothing, so revenue became 0 without a word.
    loader = _loader()
    loader.excel_file = SimpleNamespace(sheet_names=["Average sales price"])
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _price_frame("Volume 2026"))

    loader._load_avg_sales_price()

    assert loader.sales_prices == {}  # the numbers themselves are unchanged
    warnings = _messages(loader, "Average sales price")
    assert len(warnings) == 1
    assert "Volume 2025" in warnings[0]
    assert "Volume 2026" in warnings[0]


def test_price_sheet_with_the_volume_column_loads_without_warning(monkeypatch):
    loader = _loader()
    loader.excel_file = SimpleNamespace(sheet_names=["Average sales price"])
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _price_frame("Volume 2025"))

    loader._load_avg_sales_price()

    assert set(loader.sales_prices) == {"MAT-A", "MAT-B"}
    assert _messages(loader, "Average sales price") == []


@pytest.mark.parametrize("text, expected", [
    # The shapes documented next to _SAP_NUMBER_RE.
    ("2833.768 TO", 2833.768),
    ("15999 PC", 15999.0),
    ("27.00 M", 27.0),
    ("2,895,386.20    EUR", 2895386.20),
    ("- 93.72    EUR", -93.72),
    # The pattern accepts units with a digit; the digit used to be glued onto
    # the number ('10 M3' read as 103).
    ("10 M3", 10.0),
    ("1,250.5 M2", 1250.5),
])
def test_sap_number_text_parses_to_the_number_before_the_unit(text, expected):
    loader = _loader()
    loader.sap_number_warnings = []
    assert loader._parse_sap_number(text, 0.0, "ctx") == pytest.approx(expected)
    assert loader.sap_number_warnings == []


@pytest.mark.parametrize("text", ["054C", "28.01.2027", "veel"])
def test_sap_number_rejects_codes_and_dates(text):
    loader = _loader()
    loader.sap_number_warnings = []
    assert loader._parse_sap_number(text, 0.0, "ctx") == 0.0
    assert loader.sap_number_warnings == [("ctx", text)]


def test_blank_and_boolean_stock_cells_do_not_become_quantities():
    # bool is an int in Python: without its own guard True would be one unit
    # of stock. Blank cells are the documented default and are not reported.
    loader = _loader()
    loader.sap_number_warnings = []
    for value in (True, False, None, pd.NA, float("nan"), "", "  NaN  "):
        assert loader._parse_sap_number(value, -7.5, "stock") == -7.5
    assert loader.sap_number_warnings == []


@pytest.mark.parametrize("text, expected", [("+1.25e3", 1250.0), ("-2E-3", -0.002)])
def test_plain_numeric_text_bypasses_the_sap_unit_pattern(text, expected):
    # The unit pattern has no exponent; plain numeric text must not need it.
    loader = _loader()
    loader.sap_number_warnings = []
    assert loader._parse_sap_number(text, -7.5, "stock") == pytest.approx(expected)
    assert loader.sap_number_warnings == []


def test_empty_price_sheet_does_not_report_a_missing_volume_column(monkeypatch):
    # Nothing to price, so no zero-revenue warning either.
    loader = _loader()
    loader.excel_file = SimpleNamespace(sheet_names=["Average sales price"])
    frame = pd.DataFrame(columns=["ProductId", "PlantCode", "ExWorks Revenue"])
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: frame)

    loader._load_avg_sales_price()

    assert loader.sales_prices == {}
    assert _messages(loader, "Average sales price") == []


def test_same_warning_is_recorded_once():
    loader = _loader()

    loader._warn_load("FTE", "zelfde melding", echo=False)
    loader._warn_load("FTE", "zelfde melding", echo=False)

    assert loader.load_warnings == [{"source": "FTE", "message": "zelfde melding"}]


def test_results_payload_carries_the_load_warnings():
    warning = {"source": "OEE + Machine groups", "message": "OEE ontbreekt voor machine M1; gerekend met 100%."}
    engine = SimpleNamespace(
        results={},
        data=SimpleNamespace(periods=["2025-01"], master_consistency_warnings=[], load_warnings=[warning]),
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_read_blueprint(
        lambda: ({"id": "s"}, engine),
        lambda row: {},
        lambda current_engine: {},
    ))

    payload = app.test_client().get("/api/results").get_json()

    assert payload["load_warnings"] == [warning]
