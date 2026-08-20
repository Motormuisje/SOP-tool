"""De overzichtslaag van de FTE-werkbank (klantrichtlijn 2026-08-06).

De richtlijn: de werkbank moet in één oogopslag leesbaar zijn ("een lange
lijst is maar niks"), grafieken zijn bediening (klikken opent het bewerkpad),
en alles wat op een aanname rekent nodigt uit tot invullen. Deze tests draaien
op de gedeelde server ZONDER masterstore — precies de toestand waarin alle
normen op de aanname of de L12-coëfficiënt rekenen en er nog geen loontarief
bestaat, dus de toestand waarin de chips en badges móéten verschijnen.
"""

import pytest
from playwright.sync_api import expect

from tests.browser.test_fte_workbench import _open_workbench


def test_heatmap_covers_window_lines_over_the_full_horizon(browser_page):
    """De knelpuntenmatrix is de opening van het tabblad: elke groep met een
    beschikbaarheidsvenster, over de VOLLE horizon — ook als er op een
    deelbereik is ingezoomd, want het signaal mag niet meeschuiven."""
    page = browser_page
    _open_workbench(page)

    report = page.evaluate(
        """() => {
            const table = document.querySelector('#fteHeatmap table');
            if (!table) return null;
            const header = [...table.querySelectorAll('tr:first-child th')].slice(1);
            const rows = [...table.querySelectorAll('tr')].slice(1);
            return {
                columns: header.length,
                rows: rows.length,
                expectedRows: _fteWindowLines().length,
                horizon: _fteState.data.periods.length,
                sampleCells: rows.length ? rows[0].querySelectorAll('td').length - 1 : 0,
            };
        }""")
    assert report, "geen heatmap gerenderd"
    assert report["rows"] == report["expectedRows"] > 0
    assert report["columns"] == report["horizon"]
    assert report["sampleCells"] == report["horizon"]

    # De celwaarde volgt de MACHINEBELASTING (load_hours), niet de bemensing
    # (hours): bij een actieve combinatie verhuist de bemensing naar de
    # combinatieregel en zou de groep vals groen kleuren.
    formule = page.evaluate(
        """() => {
            const line = _fteWindowLines()[0];
            const p = _fteState.data.periods[0];
            const hours = Number(((line.load_hours || line.hours) || {})[p] || 0);
            const avail = Number((line.available_hours || {})[p] || 0);
            const verwacht = avail > 0 ? Math.round(hours / avail * 100) + '%' : '—';
            const cel = document.querySelector('#fteHeatmap tr:nth-child(2) td:nth-child(2)');
            return { verwacht, getoond: cel.textContent.trim() };
        }""")
    assert formule["getoond"] == formule["verwacht"], formule
    assert page.js_errors == []


def test_heatmap_cell_click_selects_month_and_focuses_group(browser_page):
    """Klikken is bedienen: een cel zet de maand in het periodefilter en
    scrolt naar de groep in de tabel. Zonder die koppeling is de matrix
    behang en blijft de gebruiker zelf zoeken waar het knelt."""
    page = browser_page
    _open_workbench(page)

    target = page.evaluate(
        """() => {
            const cell = document.querySelector('#fteHeatmap td[onclick]');
            if (!cell) return null;
            const m = cell.getAttribute('onclick').match(/focusFteGroup\\('(.+?)','(.+?)','(.+?)'\\)/);
            return m ? { category: m[1], key: m[2], period: m[3] } : null;
        }""")
    assert target, "geen klikbare heatmapcel"

    page.evaluate(
        "(t) => focusFteGroup(t.category, t.key, t.period)", target)
    assert page.evaluate("() => document.getElementById('ftePeriod').value") == target["period"]
    row = page.locator(f'#fteWbBody tr[data-fte-row="{target["category"]}:{target["key"]}"]')
    expect(row).to_be_visible()
    assert page.js_errors == []


def test_groups_start_collapsed_and_open_on_click(browser_page):
    """De lange platte lijst is vervangen door een accordion: machinerijen
    staan ingeklapt (wel in de DOM — rijtellingen behouden hun betekenis)
    onder hun groep en klappen open op de groepsrij."""
    page = browser_page
    _open_workbench(page)

    state = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#fteWbBody tr[data-fte-row^="machine:"]')];
            // Wezen (machines zonder groepsregel) staan bewust altijd
            // zichtbaar achteraan: niets mag stil wegvallen.
            const groupKeys = new Set(_fteState.data.lines
                .filter(l => l.category === 'group').map(l => String(l.key)));
            const orphans = _fteState.data.lines
                .filter(l => l.category === 'machine'
                             && !groupKeys.has(String(l.machine_group || ''))).length;
            return { total: rows.length, orphans,
                     hidden: rows.filter(r => r.classList.contains('hidden')).length };
        }""")
    assert state["total"] > 0, "geen machinerijen in de DOM (machinedetail staat aan)"
    assert state["hidden"] == state["total"] - state["orphans"], (
        "machinerijen met een groep horen ingeklapt te starten", state)

    opened = page.evaluate(
        """() => {
            const groupRow = document.querySelector('#fteWbBody tr[data-fte-row^="group:"]');
            const key = groupRow.dataset.fteRow.split(':').slice(1).join(':');
            toggleFteGroup(key);
            const machines = [...document.querySelectorAll('#fteWbBody tr[data-fte-row^="machine:"]')]
                .filter(r => !r.classList.contains('hidden'));
            return { key, visible: machines.length };
        }""")
    assert opened["visible"] > 0, f"groep {opened['key']} klapt niet open"
    page.evaluate("(k) => toggleFteGroup(k)", opened["key"])
    assert page.js_errors == []


def test_range_presets_aggregate_over_the_chosen_window(browser_page):
    """'Komende 3 maanden' moet exact het gemiddelde over dat venster tonen.
    De presets bestaan omdat het horizongemiddelde de piek wegpoetst waarover
    de planner deze cyclus beslist."""
    page = browser_page
    _open_workbench(page)

    result = page.evaluate(
        """() => {
            setFteRange('next3');
            const scope = _ftePeriodsInScope();
            const totals = _fteState.data.totals.fte;
            const expected = scope.reduce((s, p) => s + Number(totals[p] || 0), 0) / scope.length;
            const shown = parseLocaleNumber(document.getElementById('fteKpiTotal').textContent);
            const sub = document.getElementById('fteKpiTotalSub').textContent;
            setFteRange('all');
            return { scopeLen: scope.length, expected, shown, sub };
        }""")
    assert result["scopeLen"] == 3
    assert abs(result["shown"] - result["expected"]) < 0.005, result
    assert "komende 3 mnd" in result["sub"]
    assert page.js_errors == []


def test_kpi_peak_is_the_argmax_and_click_selects_that_month(browser_page):
    """Werven en ploegen plan je op de piekmaand; de subregel moet de échte
    argmax tonen en erheen springen bij een klik."""
    page = browser_page
    _open_workbench(page)

    result = page.evaluate(
        """() => {
            const totals = _fteState.data.totals.fte;
            let peak = null;
            for (const p of _fteState.data.periods) {
                const v = Number(totals[p] || 0);
                if (!peak || v > peak.value) peak = { period: p, value: v };
            }
            const sub = document.getElementById('fteKpiTotalSub');
            const button = sub.querySelector('button');
            if (button) button.click();
            return { expected: peak, subText: sub.textContent,
                     selected: document.getElementById('ftePeriod').value };
        }""")
    assert result["expected"]["period"] in result["subText"]
    assert result["selected"] == result["expected"]["period"], "piekklik selecteert de maand niet"
    page.evaluate("() => { document.getElementById('ftePeriod').value = ''; renderFteWorkbench(); }")
    assert page.js_errors == []


def test_stacked_chart_carries_all_groups_plus_indirect(browser_page):
    """De FTE-opbouwgrafiek moet exact de meetellende groepen als lagen
    dragen plus één indirecte laag, met de payloadwaarden als data — een
    grafiek die niet uit de API komt is decor."""
    page = browser_page
    _open_workbench(page)

    report = page.evaluate(
        """() => {
            if (!_fteWbChartInstance) return null;
            const groups = _fteState.data.lines
                .filter(l => l.category === 'group' && l.counts_in_total !== false);
            const ds = _fteWbChartInstance.data.datasets;
            const first = groups[0];
            const chartFirst = ds.find(d => d._fteKey === first.key);
            const periods = _fteState.data.periods;
            const matches = chartFirst && periods.every((p, i) =>
                Math.abs(chartFirst.data[i] - Number((first.fte || {})[p] || 0)) < 1e-9);
            return { datasets: ds.length, expected: groups.length + 1,
                     labels: _fteWbChartInstance.data.labels.length,
                     horizon: periods.length, firstSeriesMatches: !!matches };
        }""")
    assert report, "geen grafiekinstantie"
    assert report["datasets"] == report["expected"]
    assert report["labels"] == report["horizon"]
    assert report["firstSeriesMatches"] is True
    assert page.js_errors == []


def test_assumption_chips_invite_filling_in(browser_page):
    """Zonder masterstore rekent alles op aannames en zonder tarief: de
    aannamenstrip en de €0-badges moeten dat als invul-uitnodiging tonen —
    doctrine 'alles invulbaar', geen stil meetellende defaults."""
    page = browser_page
    _open_workbench(page)

    strip = page.locator("#fteAssumptions").inner_text()
    assert "masterdata is de bron" in strip

    defaults = page.evaluate(
        "() => _fteState.data.lines.filter(l => l.operators_source === 'default').length")
    if defaults:
        assert "aanname 1,0" in strip
        badge = page.locator('#fteWbBody button:has-text("aanname 1,0")').first
        expect(badge).to_be_attached()

    zero_cost = page.evaluate(
        """() => _fteState.data.lines.filter(l => l.category !== 'machine' && !l.combination_id
                 && _fteAgg(l.fte, 'avg') > 0.005 && _fteAgg(l.cost) === 0).length""")
    if zero_cost:
        assert "zonder loontarief" in strip
        expect(page.locator('#fteWbBody button:has-text("geen tarief")').first).to_be_attached()
    assert page.js_errors == []


def test_comparison_shows_materiality_and_dirty_note(browser_page):
    """Twee eerlijkheidsregels van het vergelijkingspaneel: ruis onder de
    materialiteitsdrempel staat als ≈ 0 (exact getal in de tooltip), en met
    onopgeslagen normen staat er dat de vergelijking met de OPGESLAGEN normen
    rekent."""
    page = browser_page
    _open_workbench(page)

    # Synthetische varianten door de echte renderer: delta's rond de drempel.
    verdict = page.evaluate(
        """() => {
            const base = { fte_avg: 10, staffed_fte_avg: 11, hours_total: 1000,
                           utilization: 0.5, labor_cost_total: 50000, tons_per_fte: 200,
                           gross_margin_total: 90000, ebitda_total: 70000 };
            const variant = { ...base, fte_avg: 10.01, labor_cost_total: 50040,
                              ebitda_total: 71000 };
            _renderFteComparison([
                { label: 'Basis', summary: base },
                { label: 'Variant', summary: variant,
                  delta: { fte_avg: 0.01, staffed_fte_avg: 0, hours_total: 0,
                           utilization: 0, labor_cost_total: 40, tons_per_fte: 0,
                           gross_margin_total: 0, ebitda_total: 1000 } },
            ]);
            const html = document.getElementById('fteCompareBody').innerHTML;
            return {
                approxZero: (html.match(/≈ 0/g) || []).length,
                exactInTitle: html.includes('title="exact:'),
                realDelta: html.includes('+1.000'),
            };
        }""")
    # fte 0,01 < 0,05 en € 40 < € 100 zijn ruis; € 1.000 EBITDA is echt.
    assert verdict["approxZero"] >= 2, verdict
    assert verdict["exactInTitle"] is True
    assert verdict["realDelta"] is True, verdict

    # Sinds de wat-als-werkstroom rekent de vergelijking de sessie-wat-als in
    # álle varianten mee; het bijschrift zegt dat expliciet en de oude
    # 'onopgeslagen normen'-melding bestaat niet meer.
    with page.expect_response(lambda r: "/api/fte/compare" in r.url):
        page.evaluate("() => { showTab('inzet'); compareFteCombinations(); }")
    expect(page.locator("#fteComparePanel")).to_be_visible()
    bijschrift = page.locator("#fteComparePanel").inner_text()
    assert "wat-als-normen" in bijschrift.lower(), bijschrift
    assert page.evaluate("() => document.getElementById('fteCompareDirtyNote')") is None
    assert page.js_errors == []


def test_machine_rows_carry_throughput_actions(browser_page):
    """Elke machinerij draagt de ✎-actie (eigen doorzet invullen als override
    met bronlabel) — het invulpad hoort te zitten waar de planner kijkt, niet
    drie tabbladen verderop."""
    page = browser_page
    _open_workbench(page)

    report = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#fteWbBody tr[data-fte-row^="machine:"]')];
            const withEdit = rows.filter(r => r.querySelector('button[onclick^="openFteThroughputGrid"]'));
            const withMes = rows.filter(r => r.querySelector('button[onclick^="adoptFteBenchmark"]'));
            const mesLines = _fteState.data.lines.filter(l => l.category === 'machine' && l.throughput_mes);
            return { rows: rows.length, withEdit: withEdit.length,
                     withMes: withMes.length, mesLines: mesLines.length };
        }""")
    assert report["rows"] > 0
    assert report["withEdit"] == report["rows"], "niet elke machinerij heeft de invul-actie"
    # De overname-knop bestaat precies waar een MES-meting is (zonder store: 0).
    assert report["withMes"] == report["mesLines"]
    assert page.js_errors == []
