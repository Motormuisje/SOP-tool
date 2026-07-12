# Validatielijst — Apex Rainier fase 3

**Stempel:** 12-07-2026 · branch `fase-3` · commit `21c9260` (tag `milestone-fase-3`)

Deze lijst koppelt elke functie aan de geautomatiseerde tests die haar valideren,
met het resultaat van de laatste volledige run. Zie `docs/testverslag-fase3.md`
voor de teststrategie en garanties per laag; dit document is de afvinklijst.

## Totaaloverzicht (laatste volledige run, 12-07-2026)

| Suite | Omvang | Resultaat |
|---|---|---|
| Backend (`pytest tests --ignore=tests/browser --ignore=tests/performance`) | 680 tests | ✅ 679 geslaagd · 1 bewust overgeslagen¹ (5m28s) |
| Browser/UI (`pytest tests/browser`, Playwright) | 72 tests | ✅ 72 geslaagd · 0 JS-consolefouten (5m29s) |
| Pariteits-smoke (`python main.py --test`) | volledige pipeline | ✅ geslaagd |
| Golden cell-diff vs. fase-2 baseline-export | alle cellen, alle sheets | ✅ byte-identiek (exhaustieve ronde 11-07-2026) |
| Performance (`pytest tests/performance`, apart draaien) | 2 tests | ✅ ~+1% t.o.v. fase 2 (ronde 11-07-2026) |

¹ `test_routes_config.py::…master-file…` — vereist een echt .xlsm-uploadfixture;
de flow zelf wordt gedekt door de browserimport in `tests/browser/test_master_data.py`.

---

## 1. Rekenkern & golden parity

| Validatiepunt | Dekking | Status |
|---|---|---|
| Single-file-flow numeriek onaangeroerd (fase-2 baseline) | `test_golden_pipeline.py` (4) + cell-diff-script | ✅ |
| Forecast (L01), actuals/forecast-splitsing | `test_forecast_engine.py` (20), `test_forecast_defaults.py` (10) | ✅ |
| BOM-topologische volgorde, afhankelijke vraag | `test_bom_engine.py` (21), `test_cascade.py` (5) | ✅ |
| Voorraad & plannen (L03–L06), veiligheidsvoorraad, MOQ | `test_inventory_engine.py` (28) | ✅ |
| Capaciteit & FTE (L07–L12), bezetting, ploegen | `test_capacity_engine.py` (16) | ✅ |
| Voorraadkwaliteit-overlay | `test_inventory_quality_engine.py` (21) | ✅ |
| Waarde/€-overlay (omzet, kosten, EBIT, ROCE) | `test_value_planning_engine.py` (20) | ✅ |
| Synthetische randgevallen engine-breed | `test_planning_engine_synthetic.py` (6) | ✅ |
| MoM-vergelijking | `test_mom_comparison_engine.py` (36) + browser `test_mom.py` (1) | ✅ |

## 2. Sessies, persistentie & herstart

| Validatiepunt | Dekking | Status |
|---|---|---|
| Zes state-sync-punten (snapshot, sync, overrides, replay, recalc, persistentie) | `test_state_model.py` (3), `test_state_snapshot.py` (16), `test_engine_rebuild.py` (11) | ✅ |
| Replay = waarheid: live volgorde ≡ replay na herstart | `test_replay.py` (11), `test_pending_edits.py` (6) | ✅ |
| Sessie-opslag op schijf, corrupt-vangnet | `test_session_store.py` (9), `test_config_store.py` (10) | ✅ |
| Sessieroutes (aanmaken, wisselen, verwijderen, hernoemen) | `test_routes_sessions.py` (19) + browser `test_sessions.py` (6) | ✅ |
| Sessiewissel wist visuele scopes (geen cross-contaminatie) | browser `test_material_groups.py` (scope×wissel), `test_session_switch_products.py` (4) | ✅ |
| Workflow: upload → calculate → resultaten (incl. NL-foutmeldingen) | `test_routes_workflow.py` (43), browser `test_load.py` (6) | ✅ |

## 3. Bewerkingen & cascade

| Validatiepunt | Dekking | Status |
|---|---|---|
| Lijn-edits + cascade door alle afhankelijke lijnen | `test_routes_edits.py` (33), `test_volume_change.py` (6) | ✅ |
| Bulk-edits (incl. drag) | `test_bulk_edit.py` (5) + browser `test_bulk.py`/`test_bulk_drag.py` (4) | ✅ |
| L04-startvoorraad-edits | `test_edit_l4_starting_stock.py` (5), `test_inventory_engine_overrides.py` (3) | ✅ |
| Capaciteits-overrides (L07/L09/L11/L12) + persistentie | `test_edit_capacity_overrides.py` (4), `test_capacity_engine_overrides.py` (9), `test_capacity_overrides_persistence.py` (3) | ✅ |
| Edit-status, undo/reset | `test_routes_edit_state.py` (11) + browser `test_edits.py` (3) | ✅ |
| Scenario-semantiek (kopie, vergelijk) | `test_routes_scenarios.py` (25) | ✅ |
| Commentaar per cel/rij | `test_routes_comments.py` (7) + browser `test_comments.py` (1) | ✅ |

## 4. Dynamische producten (fase 3)

| Validatiepunt | Dekking | Status |
|---|---|---|
| Alle sourcing-combinaties (aangekocht / geproduceerd / mix × MOQ, leadtime, BOM, routing) | `test_product_overlay.py` (40) | ✅ |
| Financiële doorwerking op golden data (omzet, kosten, marge sluiten aan) | `test_product_overlay_golden.py` (24) | ✅ |
| Producten overleven sessiewissel en herstart | `test_added_products_sync.py` (13), `test_session_switch_products.py` (4) | ✅ |
| Product-routes + UI-flow (formulier, selector, verwijderen) | `test_routes_products.py` (10) + browser `test_products.py` (5) | ✅ |
| Purchased & produced-verhoudingen | `test_routes_pap.py` (6) | ✅ |

## 5. Grafiek-analyse

| Validatiepunt | Dekking | Status |
|---|---|---|
| Analyse op álle grafieken (financieel, volume, FTE, machines, kwaliteit) | browser `test_chart_analysis.py` (15) | ✅ |
| Autodetectie + twee-punten-selectie met verbindingspijl | idem (selectie- en connectortests) | ✅ |
| FTE-drill naar producten | idem + browser `test_machine_drilldown.py` (1) | ✅ |
| Top-movers → planningstabel (filter + aanpasbaar) | idem + `test_scoping.py` (7) | ✅ |
| Excel-export van de analyse | `test_routes_exports.py` (analyse-export) | ✅ |
| Analyse onder actieve groep (gescoopte labels, sluitende bijdragen) | browser `test_material_groups.py` (analyse-onder-groep) | ✅ |
| Grafiekrendering zelf (perioden, datasets) | `test_chart_renderer.py` (7) + browser `test_charts.py` (4), `test_financial_deviation.py` (1) | ✅ |

## 6. Materiaalgroepen & scoping

| Validatiepunt | Dekking | Status |
|---|---|---|
| Groepen opslaan/verwijderen, per sessie persistent | `test_routes_material_groups.py` (7) | ✅ |
| Dropdown combineerbaar met linetype-filters; terugschakelen naar "Alle groepen" (gemelde bug) | browser `test_material_groups.py` (7, echte `select_option`) | ✅ |
| "Maak actief" scopet dashboard + machines (bijdragemarge; vaste kosten/EBIT/ROCE bewust weggelaten) | `test_scoping.py` (7), `test_scoped_endpoints.py` (6) | ✅ |
| Lege doorsnede → uitleg + "Herstel filters"-knop | browser `test_material_groups.py` (empty-hint) | ✅ |
| Groep × sessiewissel, undo herstelt nooit óver actieve groep | browser `test_material_groups.py` (klasse-audit A/B) | ✅ |

## 7. Masterdata in de app

| Validatiepunt | Dekking | Status |
|---|---|---|
| Serialisatie-round-trip (post-parse, geen tweede parser) | `test_master_data.py` (5) | ✅ |
| Werkboek-vrij rekenen (store + extracts, geen basis-.xlsm) | `test_master_data.py`, `test_routes_master_data.py` (6) | ✅ |
| **Overlay op werkboek-sessies bij elke herberekening (gemelde bug: naam wijzigen + calculate)** | `test_master_data.py` (overlay + rebuild) + browser `test_master_data.py` (grid-rename → calculate → resultaat) | ✅ |
| Merge-semantiek: app wint per sleutel, nieuwe werkboek-SKU's blijven, Config-ankers/purchase-actuals van werkboek | `test_master_data.py::test_workbook_overlay_applies_app_edits` (25 ongewijzigde materialen identiek) | ✅ |
| Import met diff-bevestiging, PATCH-validatie-door-hydratie, versieteller | `test_routes_master_data.py` (6) + browser `test_master_data.py` (1) | ✅ |
| Store-persistentie over herstart; testisolatie van de gebruikers-store | `test_master_data.py` + autouse-fixture `tests/conftest.py::_isolate_master_store` | ✅ |

## 8. Exports

| Validatiepunt | Dekking | Status |
|---|---|---|
| Planningswerkboek-export (structuur + waarden) | `test_routes_exports.py` (23), `test_serializers.py` (3) | ✅ |
| MoM-delta-export | `test_mom_comparison_engine.py` (36) | ✅ |
| DB-export (flat) | `test_database_exporter.py` (6) | ✅ |
| Analyse-export (Excel) | `test_routes_exports.py` | ✅ |
| Financiële leesroutes | `test_routes_financials.py` (5), `test_routes_read.py` (14) | ✅ |

## 9. Machines & capaciteit (UI)

| Validatiepunt | Dekking | Status |
|---|---|---|
| Machine-overrides (OEE, beschikbaarheid) + herberekening | `test_routes_machines.py` (18) + browser `test_machines.py` (5) | ✅ |
| Machine → productendrill | `test_routes_machine_products.py` (2) + browser `test_machine_products.py` (1) | ✅ |
| Directe doorzet-aanpassing | browser `test_direct_throughput.py` (4) | ✅ |
| Cyclusbeheer | `test_cycle_manager.py` (5) | ✅ |

## 10. Foutafhandeling & robuustheid

| Validatiepunt | Dekking | Status |
|---|---|---|
| Kapotte/onvolledige invoerbestanden → nette NL-fouten | `test_data_loader_errors.py` (9), `test_errors.py` (8) | ✅ |
| Ontbrekende vendor-assets breken de UI niet | browser `test_asset_failure_repro.py` (1) | ✅ |
| Grote tabellen: lazy render + sorteren | browser `test_lazy_render.py` (2), `test_sort.py` (4) | ✅ |
| Geen JS-consolefouten in de hele browsersuite | `assert page.js_errors == []` in elke browsertest | ✅ |

---

## Niet geautomatiseerd (bewuste begrenzingen)

- **Echte SAP-maandextracts van de klant** — de suites draaien op het golden
  fixture; de eerstvolgende echte maandrun blijft een handmatige controle
  (aantallen per dataset + steekproef van 3 materialen door de hele pipeline).
- **Gelijktijdige gebruikers op dezelfde sessie** — de rebuild-lock is getest,
  echte multi-user-races niet; afspraak: één planner per instantie.
- **Visuele inspectie van de Excel-export** — cellen zijn byte-getest, opmaak
  (kleuren, groepering) is één keer handmatig geverifieerd per release.
- **`POST /api/config/master-file`** (legacy-uploadroute) — skip in backend;
  gedekt via de browserimportflow, route verdwijnt zodra iedereen op de
  app-masterdata zit.

## Zo draai je alles opnieuw

```powershell
python -m pytest tests -q --ignore=tests/browser --ignore=tests/performance   # backend
python -m pytest tests/browser -q                                             # UI (Playwright)
python -m pytest tests/performance -q                                         # performance (apart)
python main.py --test                                                          # pariteits-smoke
```

Vereist: golden fixture op de locatie uit `tests/conftest.py` (of `SOP_TEST_FILE`).
Na browserruns: `git checkout -- test-results/` (screenshots zijn runtime-artefacten).
