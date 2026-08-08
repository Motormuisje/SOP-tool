"""F2-CF — tabblad "Capaciteit & FTE" op een live server.

Draait op een werkboeksessie zonder masterstore: de werkbank valt dan terug op
de Line 12-coëfficiënt en kent geen combinaties. Dat is precies de toestand
waarin een klant hem voor het eerst opent, dus die moet kloppen.
"""

import pytest
from playwright.sync_api import expect


def _open_workbench(page):
    page.reload(wait_until="networkidle")
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    with page.expect_response(lambda r: "/api/fte" in r.url and r.ok):
        page.evaluate("() => window.showTab && window.showTab('fte')")
    page.wait_for_function(
        "() => document.querySelectorAll('#fteWbBody tr').length > 0", timeout=30000)


def test_workbench_opens_with_kpis_and_rows(browser_page):
    page = browser_page
    _open_workbench(page)

    expect(page.locator("#fteBody")).to_be_visible()
    expect(page.locator("#fteEmpty")).to_be_hidden()

    # KPI's zijn gevuld, niet leeg of NaN.
    for kpi in ("fteKpiTotal", "fteKpiIndirect", "fteKpiStaffed",
                "fteKpiUtilization", "fteKpiCost", "fteKpiTonsPerFte"):
        text = page.locator(f"#{kpi}").inner_text().strip()
        assert text and "NaN" not in text, f"{kpi} toont {text!r}"

    total = page.evaluate("() => parseLocaleNumber(document.getElementById('fteKpiTotal').textContent)")
    assert total > 0, "de werkbank rapporteert 0 FTE op een doorgerekende sessie"
    assert page.js_errors == []


def test_no_row_is_literally_named_nan(browser_page):
    """Groepsmaterialen dragen vaak geen naam; die kwam als de tekst 'nan'
    uit pandas. Een rij die "nan" heet is onbruikbaar voor de gebruiker."""
    page = browser_page
    _open_workbench(page)

    labels = page.evaluate(
        """() => Array.from(document.querySelectorAll('#fteWbBody tr td:first-child'))
                     .map(td => td.textContent.trim())""")
    assert labels
    assert not any(label.lower().startswith("nan") for label in labels), labels


def test_machine_detail_toggle_adds_and_removes_rows(browser_page):
    page = browser_page
    _open_workbench(page)

    with_detail = page.locator("#fteWbBody tr").count()
    page.uncheck("#fteShowMachines")
    page.wait_for_function(
        f"() => document.querySelectorAll('#fteWbBody tr').length < {with_detail}",
        timeout=10000)
    without_detail = page.locator("#fteWbBody tr").count()
    assert 0 < without_detail < with_detail

    page.check("#fteShowMachines")
    page.wait_for_function(
        f"() => document.querySelectorAll('#fteWbBody tr').length === {with_detail}",
        timeout=10000)
    assert page.js_errors == []


def test_period_selector_switches_between_total_and_one_month(browser_page):
    """Uren SOMMEREN over de horizon, FTE en benutting MIDDELEN. Eén maand mag
    dus nooit meer uren tonen dan alle maanden samen.

    Toetst _fteAgg rechtstreeks: de cel toont een nl-NL-getal ("2.249"), en dat
    terugparsen met parseLocaleNumber levert 2,249 op — de punt is daar per
    documentatie een decimaalteken. Vergelijken op weergavetekst zou dus de
    test testen, niet de rekenregel.
    """
    page = browser_page
    _open_workbench(page)

    periods = page.evaluate(
        "() => Array.from(document.querySelectorAll('#ftePeriod option')).map(o => o.value).filter(Boolean)")
    assert len(periods) > 1

    result = page.evaluate(
        """(period) => {
            const line = _fteState.data.lines.find(l => l.category === 'group');
            const select = document.getElementById('ftePeriod');
            select.value = '';
            const totalHours = _fteAgg(line.hours);
            const totalFte = _fteAgg(line.fte, 'avg');
            select.value = period;
            const oneHours = _fteAgg(line.hours);
            const oneFte = _fteAgg(line.fte, 'avg');
            select.value = '';
            return { totalHours, totalFte, oneHours, oneFte,
                     periodCount: _fteState.data.periods.length,
                     rawSum: _fteState.data.periods.reduce((s, p) => s + (line.hours[p] || 0), 0),
                     rawOne: line.hours[period] || 0 };
        }""", periods[0])

    assert result["totalHours"] == pytest.approx(result["rawSum"], rel=1e-9)
    assert result["oneHours"] == pytest.approx(result["rawOne"], rel=1e-9)
    assert result["oneHours"] <= result["totalHours"] + 1e-9
    # 'avg' middelt over de horizon in plaats van te sommeren; anders zou een
    # jaarhorizon een twaalfvoudige bezetting rapporteren.
    assert result["totalFte"] < result["oneFte"] * result["periodCount"] + 1e-9
    assert page.js_errors == []


def test_period_selector_updates_the_rendered_table(browser_page):
    """Naast de rekenregel: verandert de tabel ook zichtbaar mee?"""
    page = browser_page
    _open_workbench(page)

    before = page.locator("#fteWbBody").inner_text()
    periods = page.evaluate(
        "() => Array.from(document.querySelectorAll('#ftePeriod option')).map(o => o.value).filter(Boolean)")
    page.select_option("#ftePeriod", periods[0])
    page.wait_for_timeout(200)
    after = page.locator("#fteWbBody").inner_text()

    assert before != after, "de tabel reageert niet op de periodekeuze"
    assert page.js_errors == []


def test_combination_panel_explains_itself_when_empty(browser_page):
    """Zonder masterdata zijn er geen combinaties. Dan moet er staan waar je
    ze aanmaakt, niet een lege doos."""
    page = browser_page
    _open_workbench(page)

    text = page.locator("#fteCombinations").inner_text()
    assert "Masterdata-tabellen" in text or "combinatie" in text.lower()


def test_compare_renders_a_variant_table(browser_page):
    page = browser_page
    _open_workbench(page)

    with page.expect_response(lambda r: "/api/fte/compare" in r.url and r.ok):
        page.evaluate("() => compareFteCombinations()")
    expect(page.locator("#fteComparePanel")).to_be_visible()
    page.wait_for_function(
        "() => document.querySelectorAll('#fteCompareBody tr').length > 0", timeout=15000)

    headers = page.locator("#fteCompareHead").inner_text()
    for column in ("FTE", "Benutting", "Loonkosten", "Ton/FTE"):
        assert column in headers, f'kolom "{column}" ontbreekt in de vergelijking'
    assert page.js_errors == []


def test_norm_edit_raises_the_dirty_bar_and_revert_clears_it(browser_page):
    page = browser_page
    _open_workbench(page)

    expect(page.locator("#fteDirtyBar")).to_be_hidden()
    changed = page.evaluate(
        """() => {
            const input = document.querySelector('#fteWbBody input[data-fte-key]');
            if (!input) return false;
            input.value = '2.5';
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""")
    assert changed, "geen bewerkbare bemensingsnorm gevonden in de tabel"

    expect(page.locator("#fteDirtyBar")).to_be_visible()
    assert page.locator("#fteDirtyCount").inner_text().strip() == "1"

    page.evaluate("() => revertFteNorms()")
    expect(page.locator("#fteDirtyBar")).to_be_hidden()
    assert page.js_errors == []


def test_reopening_the_tab_refreshes_and_keeps_the_what_if(browser_page):
    """Een getypte norm is sinds de wat-als-werkstroom SESSIESTATE: hij rekent
    direct mee en overleeft tabwissel en verversing omdat de server hem
    draagt — niet omdat een lokale overlay hem vasthoudt."""
    page = browser_page
    _open_workbench(page)

    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.evaluate(
            """() => {
                const input = document.querySelector('#fteWbBody input[data-fte-key]');
                input.value = '3';
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }""")
    expect(page.locator("#fteDirtyBar")).to_be_visible()

    # Tabblad verlaten en terugkomen haalt nieuwe data op; de wat-als komt
    # uit de sessie terug.
    with page.expect_response(lambda r: "/api/fte" in r.url and r.ok):
        page.evaluate("() => { showTab('planning'); showTab('fte'); }")
    page.wait_for_function(
        "() => document.querySelectorAll('#fteWbBody tr').length > 0", timeout=30000)

    assert page.evaluate("() => Object.keys(_fteState.overrides).length") == 1
    expect(page.locator("#fteDirtyBar")).to_be_visible()
    assert page.evaluate(
        "() => document.querySelector('#fteWbBody input[data-fte-key]').value") == "3"

    # Opruimen: de gedeelde server terug naar schoon.
    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.evaluate("() => revertFteNorms()")
    assert page.js_errors == []


def test_invalid_norm_is_refused_without_touching_the_dirty_state(browser_page):
    """Een niet-numerieke norm mag niet als 0 of NaN in de dirty-state landen —
    dat zou bij opslaan een bemensing van nul in de masterdata schrijven."""
    page = browser_page
    _open_workbench(page)

    posted = []
    page.on("request", lambda req: posted.append(req.url))
    page.evaluate(
        """() => {
            const input = document.querySelector('#fteWbBody input[data-fte-key]');
            input.value = 'veel';
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }""")
    assert page.evaluate("() => Object.keys(_fteState.overrides).length") == 0
    assert [u for u in posted if "/api/fte/norm_overrides" in u] == [],         "een geweigerde invoer mag geen wat-als POSTen"
    expect(page.locator("#fteDirtyBar")).to_be_hidden()


def test_workbench_knows_the_master_version_it_is_based_on(browser_page):
    """Zonder die versie stuurt opslaan geen base_version mee en overschrijft
    de werkbank stil de wijziging van een tweede tabblad."""
    page = browser_page
    _open_workbench(page)

    has_field = page.evaluate("() => 'masterVersion' in _fteState")
    assert has_field, "_fteState houdt de masterversie niet bij"


def test_wat_als_werkstroom_direct_resultaat_en_terugzetten(browser_page):
    """De werkstroom van de klant (2026-08-06): aanpassen, Enter, METEEN
    resultaat, verder spelen — zonder masterdata-omweg. Het paneel rechtsonder
    houdt de wijzigingen bij (oud → nieuw) en Terugzetten herstelt alles."""
    page = browser_page
    _open_workbench(page)

    # Schoon beginnen: een eerdere test kan een wat-als hebben achtergelaten
    # (de sessie draagt hem server-side; een gesloten pagina neemt hem niet
    # mee het graf in). Zonder deze reset meet de basis hieronder een
    # overridden stand en klopt de verdubbelingsverwachting niet meer.
    if page.evaluate("() => Object.keys(_fteState.overrides).length"):
        with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
            page.evaluate("() => revertFteNorms()")

    target = page.evaluate(
        """() => {
            const input = document.querySelector('#fteWbBody input[data-fte-key]');
            const row = input.closest('tr');
            return { key: input.dataset.fteKey, value: input.value,
                     rowId: row.dataset.fteRow };
        }""")
    base_fte = page.evaluate(
        "(id) => _fteAgg(_fteState.data.lines.find(l => `${l.category}:${l.key}` === id).fte, 'avg')",
        target["rowId"])
    doubled = str(float(target["value"].replace(",", ".")) * 2)

    patched = []
    page.on("request", lambda req: patched.append(req.url)
            if req.method == "PATCH" else None)
    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.evaluate(
            """([val]) => {
                const input = document.querySelector('#fteWbBody input[data-fte-key]');
                input.value = val;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }""", [doubled])

    # Eerst het contract: de override staat geregistreerd met precies de
    # getypte waarde — een faal hier verklaart zichzelf.
    registered = page.evaluate("() => _fteState.overrides")
    assert list(registered) == [target["key"]], registered
    assert registered[target["key"]]["operators_per_hour"] == pytest.approx(float(doubled)), registered

    # Meteen resultaat: de regel rekent verdubbeld, bron is 'wat-als', en er
    # is GEEN masterdata-PATCH vertrokken.
    after = page.evaluate(
        "(id) => _fteAgg(_fteState.data.lines.find(l => `${l.category}:${l.key}` === id).fte, 'avg')",
        target["rowId"])
    assert abs(after - base_fte * 2) < 0.01, (base_fte, after)
    assert patched == [], "wat-als mag de masterdata niet raken"
    source = page.evaluate(
        "(id) => _fteState.data.lines.find(l => `${l.category}:${l.key}` === id).operators_source",
        target["rowId"])
    assert source == "wat-als"

    # Het paneel rechtsonder toont oud → nieuw.
    expect(page.locator("#fteWhatIfTray")).to_be_visible()
    tray = page.locator("#fteWhatIfList").inner_text()
    assert "→" in tray, tray

    # Terugzetten herstelt alles exact.
    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.evaluate("() => revertFteNorms()")
    restored = page.evaluate(
        "(id) => _fteAgg(_fteState.data.lines.find(l => `${l.category}:${l.key}` === id).fte, 'avg')",
        target["rowId"])
    assert abs(restored - base_fte) < 0.01
    expect(page.locator("#fteWhatIfTray")).to_be_hidden()
    expect(page.locator("#fteDirtyBar")).to_be_hidden()
    assert page.js_errors == []
