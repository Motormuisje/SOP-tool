"""Fase 3 regressie — dynamische producten over sessiegrenzen heen.

Full-stack: eigen serverproces (zelfde harnas als tests/browser/conftest, maar
zonder browser). Dekt de gemelde bug "producten verdwijnen na sessiewissel" en
de spiegelbeeldbug (verse sessie erft producten van de vorige):

1. product toevoegen in sessie A → aanwezig;
2. instantie-snapshot B → producten MEEGEKOPIEERD (en onafhankelijk);
3. wisselen B → A → producten nog aanwezig;
4. herberekenen van A → producten overleven (sessie-first, geen global-spiegel);
5. nieuwe upload C + berekenen → GEEN geërfde producten;
6. verwijderen in A raakt de kopie in B niet.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

MN = "900000077"
PRODUCT = {"material_number": MN, "name": "Switchtest product",
           "product_type": "other", "sourcing": "purchased", "flat_volume": 100.0}
CALC = {"planning_month": "2025-12", "months_actuals": 11, "months_forecast": 12}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def switch_server(golden_fixture_path):
    """Restartable app server on a persistent temp SOP_APP_DATA_DIR.

    ``restart()`` kills the process and boots a fresh one against the SAME
    app-data dir — a true restart: sessions_store.json reload, cold sessions,
    warmup on switch.
    """
    app_data_dir = Path(tempfile.mkdtemp(prefix="sop-switch-app-data-"))
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = app_data_dir / "server.log"
    env = os.environ.copy()
    env.update({
        "SOP_APP_DATA_DIR": str(app_data_dir), "SOP_HOST": "127.0.0.1",
        "SOP_PORT": str(port), "SOP_DISABLE_AUTORUN": "1",
        "SOP_NO_BROWSER": "1", "PYTHONUNBUFFERED": "1",
    })
    state = {"process": None, "log_file": None}

    def _start():
        state["log_file"] = log_path.open("a", encoding="utf-8")
        state["process"] = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=Path(__file__).resolve().parents[1],
            env=env, stdout=state["log_file"], stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if state["process"].poll() is not None:
                pytest.fail("Server exited early:\n"
                            + log_path.read_text(encoding="utf-8", errors="replace"))
            try:
                if requests.get(base_url + "/", timeout=1).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.25)
        pytest.fail("Server did not start within 60s")

    def _stop():
        process = state["process"]
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if state["log_file"] is not None:
            state["log_file"].close()
        state["process"] = None
        state["log_file"] = None

    def restart():
        _stop()
        _start()

    _start()
    try:
        yield {"base_url": base_url, "fixture": golden_fixture_path,
               "restart": restart}
    finally:
        _stop()
        shutil.rmtree(app_data_dir, ignore_errors=True)


def _upload_and_calculate(base_url: str, fixture: Path, name: str) -> str:
    with fixture.open("rb") as workbook:
        upload = requests.post(
            base_url + "/api/upload",
            files={"file": (fixture.name, workbook)},
            data={"custom_name": name, **{k: str(v) for k, v in CALC.items()}},
            timeout=180,
        )
    upload.raise_for_status()
    session_id = upload.json()["session_id"]
    calc = requests.post(base_url + "/api/calculate", json=CALC, timeout=300)
    calc.raise_for_status()
    assert calc.json().get("success"), calc.json()
    return session_id


def _switch(base_url: str, session_id: str) -> None:
    resp = requests.post(base_url + "/api/sessions/switch",
                         json={"session_id": session_id}, timeout=300)
    resp.raise_for_status()
    assert resp.json().get("success"), resp.json()


def _product_numbers(base_url: str) -> list:
    resp = requests.get(base_url + "/api/products/added", timeout=120)
    resp.raise_for_status()
    return [p["material_number"] for p in resp.json()["added_products"]]


def _wait_until_ready(base_url: str, session_id: str, timeout_s: float = 180) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        groups = requests.get(base_url + "/api/sessions", timeout=60).json()["groups"]
        for entries in groups.values():
            for entry in entries:
                if entry["id"] == session_id and entry["restore_status"] in ("ready", "cold"):
                    return
        time.sleep(0.5)
    pytest.fail(f"session {session_id} not ready within {timeout_s}s")


# Session ids shared across the sequential integration tests in this module
# (they intentionally build on each other against one server lifetime).
_STATE: dict = {}


def test_products_survive_session_switching_and_do_not_leak(switch_server):
    base_url = switch_server["base_url"]
    fixture = switch_server["fixture"]

    # --- sessie A met product P -------------------------------------------
    sid_a = _upload_and_calculate(base_url, fixture, "Sessie A")
    resp = requests.post(base_url + "/api/products/added", json=PRODUCT, timeout=300)
    assert resp.ok, resp.text
    assert _product_numbers(base_url) == [MN]

    # --- instantie-snapshot B: product MEEGEKOPIEERD ------------------------
    snap = requests.post(base_url + "/api/sessions/snapshot",
                         json={"name": "Instantie B"}, timeout=120)
    assert snap.ok, snap.text
    sid_b = snap.json()["session"]["id"]
    _wait_until_ready(base_url, sid_b)
    _switch(base_url, sid_b)
    assert _product_numbers(base_url) == [MN], \
        "snapshot-instantie verloor het dynamische product"

    # --- terugwisselen naar A: product nog aanwezig -------------------------
    _switch(base_url, sid_a)
    assert _product_numbers(base_url) == [MN], \
        "product verdween na terugwisselen van sessie"

    # --- herberekenen van A: product overleeft (geen global-spiegel) --------
    calc = requests.post(base_url + "/api/calculate", json=CALC, timeout=300)
    assert calc.ok and calc.json().get("success"), calc.text
    assert _product_numbers(base_url) == [MN], \
        "product verdween na herberekening"

    # --- verse upload C: erft NIETS van A -----------------------------------
    _upload_and_calculate(base_url, fixture, "Sessie C")
    assert _product_numbers(base_url) == [], \
        "nieuwe sessie erfde dynamische producten van de vorige sessie"

    # --- verwijderen in A raakt de kopie in B niet ---------------------------
    _switch(base_url, sid_a)
    resp = requests.delete(base_url + f"/api/products/added/{MN}", timeout=300)
    assert resp.ok, resp.text
    assert _product_numbers(base_url) == []
    _switch(base_url, sid_b)
    assert _product_numbers(base_url) == [MN], \
        "verwijderen in de bronsessie raakte de snapshot-kopie"

    _STATE.update({"sid_a": sid_a, "sid_b": sid_b})


FD = {"mode": "add", "default": 1000.0}
MN2 = "900000088"


def test_forecast_defaults_and_reset_survive_switching(switch_server):
    """Zelfde spiegel-klasse voor forecast-defaults + het Reset-contract:
    Reset wist bewerkingen maar behoudt dynamische producten (config)."""
    base_url = switch_server["base_url"]
    sid_a, sid_b = _STATE["sid_a"], _STATE["sid_b"]

    _switch(base_url, sid_a)
    resp = requests.post(base_url + "/api/config/settings",
                         json={"forecast_defaults": FD}, timeout=300)
    assert resp.ok, resp.text

    product = dict(PRODUCT, material_number=MN2)
    resp = requests.post(base_url + "/api/products/added", json=product, timeout=300)
    assert resp.ok, resp.text
    assert _product_numbers(base_url) == [MN2]

    # Reset: bewerkingen weg, product blijft (het is sessieconfig, geen edit).
    resp = requests.post(base_url + "/api/reset_edits", timeout=300)
    assert resp.ok, resp.text
    assert _product_numbers(base_url) == [MN2], "Reset verwijderde het product"

    # Wissel weg en terug: fd en product intact.
    _switch(base_url, sid_b)
    _switch(base_url, sid_a)
    assert _product_numbers(base_url) == [MN2]
    cfg = requests.get(base_url + "/api/config", timeout=60).json()
    assert cfg["forecast_defaults"] == FD, cfg["forecast_defaults"]

    # Herberekenen: beide overleven (sessie-first, geen stale spiegel).
    resp = requests.post(base_url + "/api/calculate", json=CALC, timeout=300)
    assert resp.ok and resp.json().get("success"), resp.text
    assert _product_numbers(base_url) == [MN2]
    cfg = requests.get(base_url + "/api/config", timeout=60).json()
    assert cfg["forecast_defaults"] == FD

    # B mag niets geërfd hebben.
    _switch(base_url, sid_b)
    cfg = requests.get(base_url + "/api/config", timeout=60).json()
    assert cfg["forecast_defaults"] in ({}, None), cfg["forecast_defaults"]


def test_true_process_restart_keeps_per_session_state(switch_server):
    """Echte herstart: proces killen en opnieuw starten op dezelfde app-data.
    Elke sessie houdt haar EIGEN producten en forecast-defaults; niets lekt."""
    base_url = switch_server["base_url"]
    sid_a, sid_b = _STATE["sid_a"], _STATE["sid_b"]
    _switch(base_url, sid_a)  # A actief bij afsluiten

    switch_server["restart"]()

    # Alle sessies zijn terug uit sessions_store.json.
    groups = requests.get(base_url + "/api/sessions", timeout=60).json()["groups"]
    ids = {entry["id"] for entries in groups.values() for entry in entries}
    assert {sid_a, sid_b} <= ids

    # B: cold rebuild via het switch-herstelpad → eigen product terug.
    _switch(base_url, sid_b)
    assert _product_numbers(base_url) == [MN], \
        "sessie B verloor haar product na een echte herstart"
    cfg = requests.get(base_url + "/api/config", timeout=60).json()
    assert cfg["forecast_defaults"] in ({}, None), \
        "sessie B erfde forecast-defaults na herstart"

    # A: eigen product + forecast-defaults terug, geen kruisbesmetting.
    _switch(base_url, sid_a)
    assert _product_numbers(base_url) == [MN2], \
        "sessie A verloor haar product na een echte herstart"
    cfg = requests.get(base_url + "/api/config", timeout=60).json()
    assert cfg["forecast_defaults"] == FD, \
        "sessie A verloor haar forecast-defaults na een echte herstart"


def test_material_groups_survive_switch_and_restart(switch_server):
    """Materiaalgroepen + actieve groep zijn per sessie: wisselen laat de
    buursessie ongescoopt, en een echte herstart brengt groep én actieve
    status terug (dashboard blijft gescoopt na cold rebuild)."""
    base_url = switch_server["base_url"]
    sid_a, sid_b = _STATE["sid_a"], _STATE["sid_b"]

    _switch(base_url, sid_a)
    results = requests.get(base_url + "/api/results", timeout=120).json()["results"]
    mats = [str(r["material_number"])
            for r in results.get("03. Total demand", [])
            if sum(r["values"].values()) > 0][:2]
    assert len(mats) == 2
    resp = requests.post(base_url + "/api/material_groups", json={
        "name": "Herstartgroep", "materials": mats}, timeout=60)
    gid = resp.json()["group"]["id"]
    requests.post(base_url + f"/api/material_groups/{gid}/activate", timeout=60)
    assert "scoped" in requests.get(base_url + "/api/dashboard", timeout=120).json()

    # Buursessie B: geen groepen, ongescoopt dashboard.
    _switch(base_url, sid_b)
    body = requests.get(base_url + "/api/material_groups", timeout=60).json()
    assert body["groups"] == [] and body["active_group_id"] is None
    assert "scoped" not in requests.get(base_url + "/api/dashboard", timeout=120).json()

    # Terug naar A: groep en actieve status intact.
    _switch(base_url, sid_a)
    body = requests.get(base_url + "/api/material_groups", timeout=60).json()
    assert [g["id"] for g in body["groups"]] == [gid]
    assert body["active_group_id"] == gid

    # Echte herstart: alles terug, dashboard nog steeds gescoopt.
    switch_server["restart"]()
    _switch(base_url, sid_a)
    body = requests.get(base_url + "/api/material_groups", timeout=60).json()
    assert [g["id"] for g in body["groups"]] == [gid], \
        "materiaalgroep verdween na een echte herstart"
    assert body["active_group_id"] == gid, \
        "actieve groep verdween na een echte herstart"
    dash = requests.get(base_url + "/api/dashboard", timeout=120).json()
    assert dash.get("scoped", {}).get("name") == "Herstartgroep"

    # Opruimen: deactiveren + verwijderen.
    requests.post(base_url + "/api/material_groups/deactivate", timeout=60)
    requests.delete(base_url + f"/api/material_groups/{gid}", timeout=60)
    assert "scoped" not in requests.get(base_url + "/api/dashboard", timeout=120).json()
