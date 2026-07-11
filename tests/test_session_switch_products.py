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
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=Path(__file__).resolve().parents[1],
            env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("Server exited early:\n"
                                + log_path.read_text(encoding="utf-8", errors="replace"))
                try:
                    if requests.get(base_url + "/", timeout=1).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(0.25)
            else:
                pytest.fail("Server did not start within 60s")
            yield {"base_url": base_url, "fixture": golden_fixture_path}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
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
