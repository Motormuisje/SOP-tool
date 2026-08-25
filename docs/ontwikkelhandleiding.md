# Ontwikkelhandleiding — Apex Rainier Planning Tool

**Lees dit voordat je code aanraakt.** Wie iets wijzigt, bevestigt eerst voor
zichzelf dat de contracten en het state-model hieronder begrepen zijn. Bij
twijfel: vraag, gok niet.

---

## Wat dit is

Apex Rainier is een S&OP-tool (Sales & Operations Planning), gebouwd door Apex
Strategies en in gebruik bij een **klant in de mijnbouwsector**. De tool leest
maandelijkse SAP-achtige Excel-werkboeken (MS_RECONC `.xlsm`), draait de
volledige keten vraag → productie/inkoop → capaciteit → FTE, en schrijft een
planningswerkboek, optioneel een maand-over-maand-delta en optioneel een platte
DB-export.

Twee ingangen, dezelfde engines:
- **Web-UI** (`ui/app.py`, Flask, poort 5000) — de primaire manier waarop
  consultants en klantgebruikers werken. Meerdere gelijktijdige
  **planningssessies** ("instanties") met persistente state.
- **CLI** (`main.py --cli`) — single-shot runs voor scripts/batch.

Inzet: dit is productiesoftware bij een klant, geen prototype. Correctheid van
cijfers en stabiliteit over herstarts wegen zwaarder dan elegantie.

---

## Architectuur

```
main.py
├── run_cli()                         single-shot pad
│   └── PlanningEngine(xlsx).run()    orkestrator
│        ├── DataLoader               parse MS_RECONC-werkboek
│        ├── ForecastEngine           Line 01
│        ├── BOMEngine                niveauvolgorde, afhankelijke vraag
│        ├── InventoryEngine          Lines 03–06 (vraag, voorraad, plannen)
│        ├── CapacityEngine           Lines 07–12 (bezetting, FTE)
│        ├── InventoryQualityEngine   QC-overlay (optioneel)
│        ├── ValuePlanningEngine      €/kosten-overlay (optioneel)
│        └── FteEngine                capaciteits- & FTE-werkbank (F2-CF)
│
└── run_web() → ui/app.py (Flask)     sessiegebaseerd interactief pad
     ├── sessions (module-globaal)    alle planningsinstanties
     ├── _global_config               gedeelde config-spiegel
     └── per-sessie engine + edits    live state
```

De engine-dataflow is **strikt niveau-voor-niveau in BOM-topologische
volgorde**. Productieplannen van het ouderniveau worden afhankelijke vraag van
het kindniveau. Die volgorde doorbreken geeft geen fout — het levert stil
verkeerde cijfers op.

---

## ⚠️ Gedeelde contracten — NIET BREKEN

### `PlanningRow` (de universele uitvoereenheid, `modules/models.py`)
Elke engine levert `PlanningRow`-instanties. Downstream code gaat uit van:
- `material_number`, `line_type` — altijd gevuld, gebruikt als join-sleutels
- `values: Dict[str, float]` — gesleuteld op periodestring `"YYYY-MM"`, nooit None
- `aux_column`, `aux_2_column` — optionele weergavevelden; consumenten moeten
  None aankunnen
- `starting_stock` — alleen betekenisvol voor Line 04 (voorraad)
- Identificatiekolommen (`product_family`, `spc_product`, `product_cluster`,
  `product_name`) worden gekopieerd uit `Material`; wijzigen van de vulling
  raakt de Excel-groepering en de MoM-joins

### `LineType` (de canonieke rijen, `modules/models.py`)
Enum met stringwaarden zoals `"01. Demand forecast"`.
`PlanningEngine.EXPECTED_LINE_TYPES` assert de volledige lijst. Nooit
hernoemen, herordenen of toevoegen zonder:
1. `LineType`-enum ÉN `EXPECTED_LINE_TYPES` bij te werken
2. Elke engine die die lijn produceert bij te werken
3. Elke engine die hem consumeert bij te werken (vooral `CapacityEngine`,
   `MoMComparisonEngine`, `ValuePlanningEngine`)
4. De Excel-exportlogica in `planning_engine.to_excel_with_values` bij te werken
5. De web-UI-cascade bij te werken: een edit op een lijn moet correct door elke
   afhankelijke lijn propageren (zie State-model hieronder)
6. Het aantal asserts in `run_test()` bij te werken

### Periodeformaat
Alle periodesleutels zijn `"YYYY-MM"`-strings uit `PlanningConfig.get_periods()`.
Nooit `datetime` mengen. Sorteren is lexicografisch en leunt op dit formaat.

### `Material`, `BOMItem`, `Machine`, `MachineGroup`
Domeintypen. `Material.product_type_raw` draagt semantiek uit het VBA-tijdperk —
het kan een lijntype-string bevatten voor truck-/controlekamermaterialen die
`TruckOperationsFormulas` gebruikt. Niet "opschonen" zonder de consumenten te
kennen.

### `FteEngine` (`modules/fte_engine.py`) — additief, nooit in `results`

De capaciteits- & FTE-werkbank (charter F2-CF) leest de AFGERONDE
planningsrijen en levert een eigen resultaatobject op `engine.fte_results`. Ze
voegt **geen** `LineType` toe, dus `EXPECTED_LINE_TYPES`, de Excel-export en de
golden baseline blijven onaangeroerd — geverifieerd door hetzelfde werkboek op
beide bomen te draaien en `results` + `value_results` byte-voor-byte te
vergelijken.

Regels bij aanraken:
- Lees uit `engine.results`, niet uit `CapacityEngine`-internals. De edits en
  overrides van de web-UI leven in de rijen; die lezen maakt dat de werkbank
  elke cascade volgt zonder tweede override-mechanisme.
- Line 12 blijft de VBA-reproductie. Zonder `staffing_norms` valt de werkbank
  terug op `fte_requirements` uit de materiaalmaster en reproduceert Line 12
  exact (`tests/test_fte_engine_golden.py` pint dit vast).
- Machinerijen zijn DETAIL (`counts_in_total=False`). Een molengroep is de MAX
  van haar machines; machinerijen optellen telt dubbel.
- Haar masterdata (`staffing_norms`, `labor_rates`, `machine_combinations`,
  `indirect_activities`, `throughput_overrides`, `benchmark_throughput`) leeft in
  `modules/master_data.FTE_DATASETS` — één tabel stuurt serialize, hydrate,
  overlay, de werkboeksheets, de PATCH-routes en de statustellingen. Voeg daar
  een dataset toe en alle zes volgen.
- De waarde-impact (`FteResult.value_impact`) past de BESTAANDE
  consolidatierekenkunde opnieuw toe met één substitutie (werkbank-loonkost voor
  de directe-FTE-kost). Nooit de 20 VBA-consolidatierijen aanpassen om het te
  laten kloppen.

---

## ⚠️ Het state-model (hier komen de meeste bugs vandaan)

`ui/app.py` houdt state in **drie gekoppelde lagen**:

| Laag | Wat er staat | Levensduur |
|---|---|---|
| Module-globals | `sessions`, `active_session_id`, `_global_config` | Proces |
| Per-sessie dict | `reset_baseline`, `pending_edits`, `value_aux_overrides`, `machine_overrides`, `active_combinations`, `valuation_params`, `parameters` | Bewaard in `sessions_store.json` (engine NIET bewaard) |
| Live engine | `engine.results`, `engine.value_results`, `engine.fte_results`, `engine.data` | Per sessie, herbouwd na herstart |

`active_combinations` (F2-CF) is het uitgewerkte voorbeeld van de regel
hieronder: de sessie-dict is de autoriteit, ze rijdt mee via
`get_session_config_overrides` zodat een KOUDE rebuild goed start,
`snapshot_engine_state` legt haar vast voor Reset,
`recalculate_value_results` eindigt in `recalculate_fte_results`,
scenario-opslaan/laden draagt haar mee, en `session_store` bewaart haar.
Hetzelfde geldt voor `machine_overrides`, die scenario's nu ook meedragen.

Consistentie komt van **zes sync-/rebuildpunten**. Elk nieuw stuk state moet in
alle zes meedoen. Dit is de meest voorkomende bron van cross-cutting bugs:

1. **`_sync_global_config_from_engine(engine)`** — wanneer een sessie actief
   wordt, trek haar state in `_global_config` zodat latere reads/writes de
   juiste instantie raken. **Elk toegevoegd configveld moet hier gekopieerd
   worden, anders toont wisselen van instantie verouderde waarden van de vorige
   sessie.**
2. **`_get_session_config_overrides(sess)`** — bij het herbouwen van een engine
   voor een sessie, duw sessiespecifieke state terug in de engine-constructie.
   **Ontbreekt een nieuw configveld hier, dan vallen rebuilds (na herstart of
   parameterwijziging) stil terug op defaults.**
3. **`_ensure_reset_baseline(sess, engine)` / `_snapshot_engine_state`** — leg
   de snapshot vast waar "Reset" naar terugkeert. **Wordt nieuwe state niet
   vastgelegd, dan lijkt Reset te werken maar blijft de nieuwe state staan.**
4. **`_replay_pending_edits(sess, engine)`** — na een rebuild (herstart,
   parameterwijziging, reset) de opgeslagen edits opnieuw toepassen zodat de
   engine dezelfde eindstaat bereikt. **Replay-volgorde telt bij gecombineerde
   edits: eerst Line 01 dan Line 06 in de verkeerde volgorde herafspelen geeft
   een ander resultaat. Bewaar de invoegvolgorde.**
5. **`_recalculate_value_results(engine, sess)` en
   `_recalculate_capacity_and_values(engine, sess)`** — draai downstream
   engines opnieuw na elke upstream wijziging. **Een lijn-edit die niet de
   juiste recalc triggert laat de UI achter met tabellen die iets anders zeggen
   dan de grafieken.**
6. **`_save_sessions_to_disk()` / `_load_sessions_from_disk()`** —
   JSON-persistentie voor sessiemetadata. **Nieuwe sessievelden moeten
   serialiseerbaar zijn en door save én load afgehandeld worden, anders
   verdwijnen ze bij herstart.**

### Regel bij nieuwe of gewijzigde state

Voordat een wijziging af is die een veld toevoegt aan sessions,
`_global_config` of engine-state, beantwoord je **expliciet** (in de
PR-beschrijving of het commitbericht):
- Wordt het vastgelegd in `_ensure_reset_baseline`?
- Wordt het gekopieerd door `_sync_global_config_from_engine`?
- Wordt het toegepast door `_get_session_config_overrides`?
- Wordt het herafgespeeld / herberekend na rebuild?
- Triggert het de juiste recalc bij wijziging (en alleen die)?
- Wordt het geserialiseerd in `_save_sessions_to_disk` en hersteld in
  `_load_sessions_from_disk`?

Is een antwoord "nee" of "weet ik niet zeker": stoppen en overleggen.

---

## Cascade-invariant per lijntype

Edits cascaderen in BOM-topologische volgorde. Concreet moet een edit op
Line 01 (demand forecast) voor materiaal X herberekening triggeren van:
- Line 02/03 voor X
- Lines 04–06 voor X (indien van toepassing)
- Line 08 voor ouders van X (afhankelijke behoefte)
- Lines 07/09–12 voor elke machinegroep waar X doorheen loopt

Combinaties zijn waar bugs zich verstoppen: edit A gevolgd door edit B moet
hetzelfde resultaat geven of ze nu live na elkaar zijn toegepast of na een
herstart uit `pending_edits` zijn herafgespeeld. Het replay-pad is de bron van
waarheid — wijkt live gedrag af van replay, dan is **het live gedrag fout**
(want replay is wat over herstarts heen bewaard blijft).

---

## Wijzigingsprotocol

1. **Voordat je de uitvoer van een engine wijzigt**: grep op haar
   `LineType`-waarde en elk gewijzigd veld over `modules/` en `ui/app.py`. Noem
   elke consument in je plan voordat je code schrijft.
2. **Voordat je `models.py` wijzigt**: noem elk bestand dat de betrokken klasse
   importeert. Kies additieve wijzigingen (nieuw optioneel veld met default)
   boven hernoemen of verwijderen.
3. **Bij nieuwe sessie-/configstate**: loop de zes syncpunten hierboven af.
   Eén missen is de faalmodus, niet de uitzondering.
4. **Nooit stilzwijgend een numerieke formule wijzigen.** Zie je iets wat op
   een bug lijkt, beschrijf het en overleg voordat je het repareert.
5. **Refactoren van `planning_engine.py` of `ui/app.py` is welkom** als het
   het state-model of de cascade echt vereenvoudigt — maar (a) in een aparte
   branch zonder featurewerk, (b) `--test` groen bij elke commit, en (c) de
   architectuur vóór/na beschreven in de PR.

---

## Bekende faalmodi (snelle referentie)

Symptoom → onderliggend mechanisme:

- **"Reset reset niet volledig"** → veld ontbreekt in `_snapshot_engine_state`.
- **"Wisselen van instantie toont verkeerde waarden"** → veld ontbreekt in
  `_sync_global_config_from_engine`, of kruisbesmetting via de
  `_global_config`-fallback in `_get_session_config_overrides`.
- **"Configwijziging blijft niet staan na herstart"** → niet geserialiseerd in
  `_save_sessions_to_disk`, of niet toegepast in `_get_session_config_overrides`.
- **"Edits voelen traag"** → recalc-scope te breed; kijk welke `_recalculate_*`
  getriggerd wordt en of de scope smaller kan.
- **"Grafieken wijken af van de tabel"** → het edit-pad werkte tabellen bij maar
  niet de downstream recalc waar de grafieken uit lezen.
- **"Combinatie van edits geeft onverwacht resultaat"** → replay-volgorde in
  `_replay_pending_edits`, of een cascadestap die afhangt van state die een
  zuster-edit nog niet had herafgespeeld.
- **"Iets brak na herstart dat eerst werkte"** → bijna altijd een
  persistentiegat: state was alleen live, niet in `sessions_store.json`.

---

## Conventies

- **Taal:** code, identifiers en commentaar in het Engels. Gebruikersgerichte
  UI-teksten mogen Nederlands zijn; bestaande teksten behouden tenzij gevraagd.
- **Runtime-data:** standaard `%LOCALAPPDATA%\SOPPlanningEngine`. Respecteer
  `SOP_APP_DATA_DIR`. Nooit runtime-bestanden in de repo schrijven.
- **Repo-hygiëne:** `uploads/`, `exports/`, `imports/`, `sessions/` en alle
  `*.xlsm` / `*.xlsx` staan in `.gitignore`. Nooit klantdata committen.
- **Python-stijl:** dataclasses voor data, expliciete type hints op publieke
  engine-methoden, `pathlib.Path` boven `os.path`. Volg de bestaande patronen
  in `planning_engine.py`.
- **Imports:** `from modules.x import Y`. De `sys.path.insert` in `main.py`
  laat dit werken vanuit de repo-root.

---

## Commando's

```powershell
pip install -r requirements.txt

python main.py                                                      # web-UI
python main.py --cli pad/naar/MS_RECONC.xlsm --planning-month 2025-12 --months-actuals 11
python main.py --test                                               # smoke
python main.py --cli pad/naar/bestand.xlsm --export-db              # + DB-export
```

Omgevingsvariabelen: `SOP_HOST`, `SOP_PORT`, `SOP_NO_BROWSER`, `SOP_NO_BANNER`,
`SOP_APP_DATA_DIR`, `SOP_TEST_FILE`.

Validatie tegen de klant-Excel (ground truth): zie
[`docs/validatiestrategie.md`](validatiestrategie.md) en
`tools/ground_truth_diff.py`.

---

## Definition of done voor elke wijziging

Bevestig in de PR-beschrijving of het commitbericht:
1. Welke engines/bestanden zijn gewijzigd.
2. Welke contracten (`PlanningRow`, `LineType`, …) de wijziging raakt.
3. In welke van de zes state-syncpunten de wijziging meedoet.
4. Welke downstream consumenten geverifieerd zijn.
5. Of `python main.py --test` nog slaagt (of waarom het niet gedraaid kon worden).
6. Alles wat je zelf besloten hebt — benoem het, zodat een reviewer het kan
   afkeuren.
