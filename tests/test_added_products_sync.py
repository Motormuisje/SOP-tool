"""Fase 3 — added_products through the state-sync points (mirrors the
forecast_defaults pattern in tests/test_forecast_defaults.py)."""

from types import SimpleNamespace

import pytest

from ui.config_store import sync_global_config_from_engine
from ui.engine_rebuild import get_config_overrides, get_session_config_overrides
from ui.session_store import load_sessions_from_disk, save_sessions_to_disk

pytestmark = pytest.mark.no_fixture

PRODUCT = {"material_number": "900000001", "name": "Test", "product_type": "bulk",
           "flat_volume": 100.0}


def _engine(added=None):
    return SimpleNamespace(
        data=SimpleNamespace(purchased_and_produced=None, valuation_params=None),
        config_overrides={"added_products": added} if added is not None else {},
    )


# ---------------------------------------------------- get_config_overrides

def test_global_config_feeds_calculate_overrides():
    ov = get_config_overrides({"added_products": [PRODUCT]})
    assert ov["added_products"] == [PRODUCT]
    assert "added_products" not in get_config_overrides({"added_products": []})
    assert "added_products" not in get_config_overrides({})


# -------------------------------------------- get_session_config_overrides

def test_session_products_do_not_leak_from_global_on_rebuild():
    global_config = {"added_products": [PRODUCT]}
    # Cold session without products: [] on load, no engine.
    sess = {"id": "a", "engine": None, "added_products": []}
    assert "added_products" not in get_session_config_overrides(sess, global_config)


def test_session_products_win_over_global():
    other = dict(PRODUCT, material_number="900000002")
    global_config = {"added_products": [PRODUCT]}
    sess = {"id": "b", "engine": None, "added_products": [other]}
    ov = get_session_config_overrides(sess, global_config)
    assert ov["added_products"] == [other]


def test_live_engine_is_fallback_when_session_field_missing():
    sess = {"id": "c", "engine": _engine([PRODUCT])}
    ov = get_session_config_overrides(sess, {})
    assert ov["added_products"] == [PRODUCT]


# ----------------------------------------------------- session persistence

def test_round_trip_engine_authoritative(tmp_path):
    sessions = {"s1": {"id": "s1", "engine": _engine([PRODUCT]),
                       "added_products": [],  # stale session field: engine wins
                       "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    assert loaded["s1"]["added_products"] == [PRODUCT]


def test_round_trip_without_engine_uses_session_field(tmp_path):
    sessions = {"s1": {"id": "s1", "engine": None, "added_products": [PRODUCT],
                       "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    assert loaded["s1"]["added_products"] == [PRODUCT]


def test_old_store_files_default_to_empty_list(tmp_path):
    sessions = {"s1": {"id": "s1", "engine": None,
                       "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    # Simulate a pre-Fase-3 store: drop the field entirely.
    import json
    payload = json.loads(store.read_text(encoding="utf-8"))
    payload["sessions"]["s1"].pop("added_products", None)
    store.write_text(json.dumps(payload), encoding="utf-8")
    loaded, _ = load_sessions_from_disk(store)
    assert loaded["s1"]["added_products"] == []


# ------------------------------------------------- calculate (stale mirror)

def test_calculate_overrides_take_session_products_over_stale_global():
    """Session-switch bug: /api/calculate used the global mirror, which is
    only refreshed when switching to a session WITH a live engine. A stale
    mirror must neither drop this session's products nor leak another's."""
    from ui.engine_rebuild import get_calculate_config_overrides

    other = dict(PRODUCT, material_number="STALE-OTHER-SESSION")
    # Stale global still mirrors another session; active session has its own.
    ov = get_calculate_config_overrides(
        {"id": "a", "engine": None, "added_products": [PRODUCT]},
        {"added_products": [other]})
    assert ov["added_products"] == [PRODUCT]

    # Active session without products: the stale global must NOT leak in.
    ov = get_calculate_config_overrides(
        {"id": "b", "engine": None, "added_products": []},
        {"added_products": [other]})
    assert "added_products" not in ov

    # Live engine is the fallback when the session field was never set.
    ov = get_calculate_config_overrides(
        {"id": "c", "engine": _engine([PRODUCT])}, {"added_products": []})
    assert ov["added_products"] == [PRODUCT]


def test_calculate_overrides_take_session_fd_vp_pap_over_stale_global():
    """Same mirror hole as the products bug, for the OTHER per-session config:
    forecast defaults, valuation params and purchased_and_produced must come
    from the session, not from a stale global mirror."""
    from ui.engine_rebuild import get_calculate_config_overrides

    stale_global = {
        "forecast_defaults": {"mode": "add", "default": 999.0},
        "valuation_params": {"1": 111.0},
        "purchased_and_produced": "ANDERE-SESSIE:0.9",
    }
    sess = {
        "id": "a", "engine": None,
        "forecast_defaults": {"mode": "fill_empty", "default": 5.0},
        "valuation_params": {"1": 42.0},
        "purchased_and_produced": "EIGEN:0.5",
        "added_products": [],
    }
    ov = get_calculate_config_overrides(sess, stale_global)
    assert ov["forecast_defaults"] == {"mode": "fill_empty", "default": 5.0}
    assert ov["valuation_params"] == {"1": 42.0}
    assert ov["purchased_and_produced"] == "EIGEN:0.5"

    # Session WITHOUT defaults must not inherit them from the stale mirror;
    # '' PAP means deliberately cleared and must also win over the mirror.
    empty_sess = {"id": "b", "engine": None, "forecast_defaults": {},
                  "purchased_and_produced": "", "added_products": []}
    ov = get_calculate_config_overrides(empty_sess, stale_global)
    assert "forecast_defaults" not in ov
    assert ov["purchased_and_produced"] == ""

    # A brand-new session: VP/PAP still fall through to the global config
    # (they are config-tab values, visible before the first calculate), but
    # forecast defaults are NEVER inherited — saving them in the config tab
    # writes the session field, so a missing field means "not this session's".
    ov = get_calculate_config_overrides({"id": "new", "engine": None}, stale_global)
    assert "forecast_defaults" not in ov
    assert "added_products" not in ov
    assert ov["valuation_params"] == {"1": 111.0}
    assert ov["purchased_and_produced"] == "ANDERE-SESSIE:0.9"


# ------------------------------------------------------- snapshot/instances

def _snapshot_app(sess_a):
    import contextlib

    from flask import Flask

    from ui.routes.sessions import create_sessions_blueprint

    sessions = {"a": sess_a}

    def crash(*args, **kwargs):
        raise RuntimeError("unexpected callback in snapshot test")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_sessions_blueprint(
        sessions,
        lambda: "a",
        lambda sid: None,
        lambda: (sessions["a"], sessions["a"].get("engine")),
        {},
        lambda s, e: {},
        lambda: None,
        lambda e: None,
        crash, crash, crash,
        lambda snap: False,
        lambda e: False,
        lambda: contextlib.nullcontext(),
        start_session_warmup=None,
        wait_for_session_warmup=None,
    ))
    return app, sessions


def _base_session(**over):
    sess = {
        "id": "a", "file_path": "x.xlsm", "filename": "x.xlsm", "engine": None,
        "custom_name": "A", "metadata": {}, "uploaded_at": "", "parameters": None,
        "pending_edits": {}, "value_aux_overrides": {}, "machine_overrides": {},
        "comments": {},
    }
    sess.update(over)
    return sess


def test_snapshot_copies_added_products_deep():
    """An instance snapshot without the products would rebuild WITHOUT them
    and silently skip every copied pending edit referencing them."""
    sess_a = _base_session(added_products=[dict(PRODUCT)])
    app, sessions = _snapshot_app(sess_a)
    resp = app.test_client().post("/api/sessions/snapshot", json={"name": "B"})
    assert resp.status_code == 200
    new_id = resp.get_json()["session"]["id"]
    copied = sessions[new_id]["added_products"]
    assert copied == [PRODUCT]
    assert copied is not sess_a["added_products"]          # deep copy
    assert copied[0] is not sess_a["added_products"][0]


def test_snapshot_prefers_live_engine_products():
    sess_a = _base_session(engine=_engine([PRODUCT]), added_products=[])
    app, sessions = _snapshot_app(sess_a)
    resp = app.test_client().post("/api/sessions/snapshot", json={"name": "B"})
    assert resp.status_code == 200
    new_id = resp.get_json()["session"]["id"]
    assert sessions[new_id]["added_products"] == [PRODUCT]


# ----------------------------------------------------------- workbook drift

def test_switch_restore_fails_cleanly_when_overlay_rejected():
    """Workbook drift: a new monthly workbook can contain a number that was
    added as a dynamic product earlier. The rebuild then (correctly) raises;
    the switch must surface a clean failed status + message, not crash or
    half-install an engine."""
    import contextlib

    from flask import Flask

    from ui.routes.sessions import create_sessions_blueprint

    sess = {
        "id": "a", "file_path": "x.xlsm", "filename": "x.xlsm", "engine": None,
        "custom_name": "A", "metadata": {}, "uploaded_at": "",
        "parameters": {"planning_month": "2025-12", "months_actuals": 11,
                       "months_forecast": 12},
        "pending_edits": {}, "value_aux_overrides": {}, "machine_overrides": {},
        "added_products": [PRODUCT],
    }
    sessions = {"a": sess}

    def failing_build(s, params=None):
        raise ValueError(
            "Materiaalnummer 900000001 bestaat al in het bronbestand. "
            "Kies een eigen nummerreeks (bijv. 9xxxxxxxx).")

    def crash(*args, **kwargs):
        raise RuntimeError("unexpected callback")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_sessions_blueprint(
        sessions, lambda: None, lambda sid: None,
        lambda: (sess, None), {}, lambda s, e: {}, lambda: None,
        lambda e: None,
        failing_build, crash, crash,
        lambda snap: False, lambda e: False,
        lambda: contextlib.nullcontext(),
        start_session_warmup=None, wait_for_session_warmup=None,
    ))

    resp = app.test_client().post("/api/sessions/switch", json={"session_id": "a"})
    assert resp.status_code == 500
    assert "bestaat al in het bronbestand" in resp.get_json()["error"]
    assert sess["restore_status"] == "failed"
    assert "900000001" in (sess["restore_error"] or "")
    assert sess["engine"] is None  # nothing half-installed


# ------------------------------------------------------------ global mirror

def test_sync_global_mirrors_active_session_and_clears_stale():
    global_config = {"added_products": [dict(PRODUCT, material_number="STALE")]}
    sync_global_config_from_engine(_engine([PRODUCT]), global_config, lambda pap: "")
    assert global_config["added_products"] == [PRODUCT]

    # Active session without products must clear the stale global list.
    sync_global_config_from_engine(_engine(), global_config, lambda pap: "")
    assert global_config["added_products"] == []
