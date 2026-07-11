# Implementatieplan S&OP-optimalisaties (wensen Sibelco, juni 2026)

Versie 1.1 — 2026-07-11
Basis: e-mail Sacha Clermont 29-06-2026 + antwoordmail (sprintindeling), bugregister `BUGS.md`, docs/ontwikkelhandleiding.md-werkwijze.

---

## 0. Openstaande punten (bewust uitgesteld)

- **Forecast-standaardvolumes — herziening uitgesteld (klant, 2026-07-11).**
  De basisfunctie is gebouwd en werkt (Fase 1.3: globaal en/of per materiaal,
  modi *lege perioden vullen* / *optellen*, opt-in, per instance). De klant wil
  deze nog aanpassen maar heeft de richting nog niet bepaald. **Bewust
  open gelaten** tot de klant kiest. Kandidaat-richtingen om t.z.t. voor te
  leggen (niet besloten):
  1. Niveau *per productgroep/cluster* i.p.v. alleen globaal + per materiaal.
  2. Extra modus / drempel, bijv. *aanvullen tot minimaal N* of beperking tot
     bepaalde perioden.
  3. Zichtbaarheid: markeer in de planningtabel welke L01-cellen door een
     default zijn gezet (indicator + tooltip), niet alleen in de export.
  4. Beheer-UI: regels toevoegen/verwijderen i.p.v. het tekstveld `MAT:aantal`.
  Geen bouw hierop tot de klant de gewenste variant(en) aangeeft.

---

## 1. Uitgangspunten

- **Numerieke pariteit is heilig.** Geen enkele fase mag bestaande, geverifieerde
  cijfers wijzigen zonder dat dit expliciet de bedoeling is. Elke go/no-go bevat
  daarom een *golden-parity* check: dezelfde input → dezelfde output als vóór de fase.
- **Elk nieuw stuk sessie-state doorloopt de zes sync-punten** (docs/ontwikkelhandleiding.md): reset-baseline,
  config-sync bij instance-wissel, config-overrides bij rebuild, replay na herstart,
  juiste herberekening, serialisatie van/naar `sessions_store.json`. Het testprotocol
  van elke fase bevat deze zes als vaste testgevallen.
- **Replay is de bron van waarheid**: live gedrag na een edit moet identiek zijn aan
  het resultaat na server-herstart (replay uit `pending_edits`/nieuwe stores).
- Regressiebasis bij start: **510 passed, 1 skipped** (`python -m pytest tests -q
  --ignore=tests/browser --ignore=tests/performance`) + `python main.py --test` groen.
- Elke fase wordt opgeleverd op een eigen git-tag (`fase-0`, `fase-1`, …).
  Rollback = terug naar de vorige tag; sessies/config op schijf zijn
  backwards-compatible (nieuwe velden altijd optioneel met default).

## 2. Faseringsoverzicht

| Fase | Inhoud | Indicatie | Blokkerende klantvragen |
|---|---|---|---|
| 0 | Fundament: bugfixes die de nieuwe features raken | 2–3 dagen | geen (H1 wel z.s.m. beslissen) |
| 1 | Quick wins: grafiek-popup, bulk-aanpassing, forecast-defaultvolumes | ~1 week | vraag 4 (defaultvolumes) |
| 2 | Opmerkingen, machine-drilldown, directe throughput, financiële metrics | ~2 weken | vragen 1, 2, 3 |
| 3 | Ontwerp-eerst: producten dynamisch toevoegen, master-sheet-vervanging, integratie | apart te scopen | vragen 5, 6 |

Fase 1 kan starten zodra Fase 0 GO heeft; binnen Fase 1 kan onderdeel 1.3
(defaultvolumes) pas gebouwd worden na antwoord op vraag 4 — 1.1 en 1.2 niet.

---

## 3. Fase 0 — Fundament (bugfixes gekoppeld aan de features)

**Waarom eerst:** de gevraagde features bouwen precies op de plekken waar het
bugregister open punten heeft. Bulk-aanpassing vermenigvuldigt de impact van de
komma-bug en de edit-races; de opmerkingen-feature introduceert door gebruikers
getypte tekst in een UI die nu nog XSS-gevoelig is; "afwijkingen t.o.v. vorige
cyclus" (fase 2) kan alleen als de dode MoM-koppeling eerst gerepareerd is.

**Scope (uit `BUGS.md`):**

| # | Bug | Reden in dit traject |
|---|---|---|
| F0.1 | H9 — komma-decimalen (`2,5` → `2`) | Bulk-edit maakt dit ×N erger |
| F0.2 | H10/H11 — geen in-flight-guard; sessie-wissel tijdens edit | Bulk-edit = veel snelle requests |
| F0.3 | H12 — XSS-escaping (innerHTML) | Voorwaarde voor opmerkingen (vrije tekst) |
| F0.4 | H6 — PAP niet gepersisteerd per sessie | Zelfde persist-patroon als nieuwe stores |
| F0.5 | H7 + M13 — scenario laadt oude overrides / scenario's weg na herstart | Nieuwe stores volgen dit patroon |
| F0.6 | H5 — exportcrash bij ontbrekende valuatie-sheet | Stabiliteit oplevering |
| F0.7 | H8 — path traversal config-route | Zelfde klasse als eerder gefixt |
| F0.8 | H3 — cross-cycle MoM doodlopend | Alleen indien vraag 3 = "vorige cyclus"; anders fase 2-beslissing |

**Klantbeslissing parallel starten:** H1 (`months_actuals` doet niets) — kiezen:
veld werkend maken óf verwijderen. Geen bouwwerk in fase 0; wel beslissen.

### Testprotocol TP-0

Uitvoering: geautomatiseerd + 30 min handmatig. Elke fix krijgt (zoals in de
vorige bugfixronde) een eigen regressietest die aantoonbaar faalt op de oude code.

| ID | Test | Verwacht resultaat | Kritiek |
|---|---|---|---|
| TP0-01 | Volledige testsuite + `main.py --test` | Alles groen; aantal tests ≥ baseline | ja |
| TP0-02 | Golden parity: zelfde workbook, run vóór/na fase 0, exporteer beide en diff alle numerieke cellen | 0 afwijkingen | ja |
| TP0-03 | Typ `2,5` in een L01-cel; typ `1.234,5`; typ `2.5` | resp. 2,5 — 1234,5 — 2,5 opgeslagen; cascade klopt | ja |
| TP0-04 | Twee snelle edits (cel A, tab, cel B) op materiaal met diepe BOM | Beide edits toegepast; eindstand = sequentieel resultaat; geen "terugspringende" cellen | ja |
| TP0-05 | Start edit, wissel direct van instance | Edit belandt in de JUISTE sessie (controle `sessions_store.json`); UI toont geen oude data over nieuwe sessie | ja |
| TP0-06 | Materiaal hernoemen naar `<img src=x onerror=alert(1)>` in testbestand; laad en bekijk alle tabbladen | Geen script-uitvoering; naam letterlijk zichtbaar | ja |
| TP0-07 | PAP-split wijzigen in sessie A; herstart server; open sessie A én B | A behoudt eigen split; B onaangetast | ja |
| TP0-08 | Edit L07 machine M → scenario opslaan → edit machine N → scenario laden → willekeurige machine-edit | N komt niet terug; herstart geeft identiek resultaat | ja |
| TP0-09 | Scenario opslaan; server herstarten | Scenario nog aanwezig en laadbaar | ja |
| TP0-10 | Workbook zonder valuatie-sheet: run + export | Export slaagt; grafiek 5 leeg i.p.v. crash | ja |
| TP0-11 | Upload naar config-route met bestandsnaam `..\..\x.xlsx` | 400 of veilig opgeslagen binnen uploads | ja |
| TP0-12 | (indien F0.8) Twee cycli draaien; MoM-sheet in export | Sheet toont daadwerkelijk vorige-cyclus-vergelijking | ja indien in scope |

**GO-criteria fase 0:** alle kritieke cases PASS · volledige suite groen ·
TP0-02 exact 0 afwijkingen · geen nieuwe open blockers.
**NO-GO:** één kritieke FAIL → herstellen en volledig protocol opnieuw draaien
(niet alleen de gefaalde case).

---

## 4. Fase 1 — Quick wins (Sprint 1)

### 1.1 Grafieken vergroten (popup)
Frontend-only: klik/knop per grafiek → modal met vergrote weergave (zelfde data,
groter canvas), sluiten met Esc/klik-buiten. Geen backend-wijziging, geen state.

### 1.2 Bulk-aanpassing volumes
- UI: bestaande celselectie + actiebalk "waarde instellen / delta (+250) / %".
- Backend: nieuw endpoint `/api/update_volume_bulk` dat de bestaande
  `apply_volume_change` per cel aanroept maar de zware herberekening
  (capaciteit + waarde) **één keer aan het einde** uitvoert i.p.v. per cel.
- Elke cel wordt een eigen `pending_edits`-entry (invoegvolgorde = selectievolgorde),
  zodat replay na herstart identiek verloopt — dit is de kern-risicopost.
- Undo: één bulk-actie = één undo-stap (groepsentry op de undo-stack).

### 1.3 Forecast-defaultvolumes (na antwoord vraag 4)
- Configureerbare regel (bijv. "materiaal X: minimaal/aanvullend N per periode"),
  toegepast op Line 01 vóór de cascade.
- Nieuwe config-state → **alle zes sync-punten** + zichtbaar in de UI als
  "default toegepast"-indicator + kolom in de Excel-export.
- Bouw pas na scherp antwoord (niveau, alleen-bij-lege-forecast vs. altijd erbovenop).

### Testprotocol TP-1

| ID | Test | Verwacht | Kritiek |
|---|---|---|---|
| TP1-01 | Regressie: volledige suite + `--test` + golden parity zonder gebruik nieuwe features | Groen; 0 numerieke afwijkingen | ja |
| TP1-02 | Elke grafiek (dashboard, capaciteit, financieel) vergroten en sluiten; daarna cel-edit doen | Popup toont zelfde data; na sluiten werkt alles; grafieken verversen correct na edit | ja |
| TP1-03 | Selecteer 10 L01-cellen over 3 materialen, +250 | Alle 10 verhoogd; cascade (L02–L12) klopt; MOQ/afronding gerespecteerd op L06 | ja |
| TP1-04 | Zelfde 10 cellen: vergelijk bulk-resultaat met 10× handmatig dezelfde edit | Identieke eindcijfers | ja |
| TP1-05 | Bulk-edit → server herstarten → sessie openen | Replay geeft identieke cijfers als live (steekproef 5 cellen + consolidatie) | ja |
| TP1-06 | Bulk-edit → Reset | Alles terug naar baseline; geen achtergebleven overrides | ja |
| TP1-07 | Bulk-edit → Undo → Redo | Undo draait de héle bulk terug in één stap; redo past hem opnieuw toe | ja |
| TP1-08 | Bulk over gemengde selectie met niet-bewerkbare regel (L10) | Duidelijke fout/overslaan-melding; bewerkbare cellen wel toegepast óf hele actie geweigerd (gekozen gedrag documenteren) | ja |
| TP1-09 | Bulk 100+ cellen op groot bestand | < 15 s totaal; UI geblokkeerd met voortgangsindicatie (geen dubbele submits) | nee |
| TP1-10 | Excel-export na bulk | Edits gemarkeerd (bestaande highlight-logica) incl. Edits Summary | ja |
| TP1-11 | Defaultvolume configureren; run | L01 toont default op afgesproken manier; indicator zichtbaar; export toont het | ja* |
| TP1-12 | Defaultvolume: herstart, instance-wissel, reset, duplicate | Config blijft per sessie correct (zes sync-punten aantoonbaar) | ja* |
| TP1-13 | Defaultvolume uitzetten | Cijfers exact terug naar situatie zonder default | ja* |

\* alleen van toepassing als 1.3 in deze release zit (vraag 4 beantwoord).

**GO-criteria fase 1:** alle kritieke PASS · TP1-04/05 (bulk = sequentieel = replay)
zonder één cijfer verschil · regressie groen · golden parity intact.
**NO-GO-drempel expliciet:** elke afwijking in TP1-05 (replay-pariteit) is een
blocker, ongeacht grootte — dat is de invariant van het hele model.

---

## 5. Fase 2 — Uitbreidingen (Sprint 2)

### 2.1 Opmerkingen (na antwoord vraag 1)
- Nieuwe sessie-store `comments`: sleutel = regel/machine/periode; waarde =
  {tekst, gebruiker, datum}. Gebruiker: vrij veld of Windows-gebruikersnaam
  (geen login aanwezig — afstemmen).
- Volledige zes-sync-punten-behandeling; optioneel mee in Excel-export
  (als celcommentaar + apart tabblad) afhankelijk van antwoord vraag 1.
- Weergave met escaping (fase 0-fix is voorwaarde); indicator op cellen met opmerking.

### 2.2 Machine-drilldown
Read-only detailpaneel per machine: volumes per periode, bezetting vs.
capaciteit, historie (binnen beschikbare data), actieve overrides. Geen nieuwe
state; alleen presentatie + endpoints die bestaande engine-data serialiseren.

### 2.3 Directe effective throughput (na antwoord vraag 2)
- Invoer per machine (eenheid volgens klantantwoord); teruggerekend naar de
  bestaande override-mechaniek (OEE/beschikbaarheid/shift of capaciteitsoverride)
  zodat replay/reset/persist gratis meeliften op de bestaande stores.
- Zichtbaar als afgeleide waarde + "override actief"-indicator.

### 2.4 Financiële metrics: trend, afwijking, drilldown (na antwoord vraag 3)
- Trend over periodes: aanwezig datamodel, nieuwe weergave.
- Afwijking: referentie afhankelijk van antwoord (vorige cyclus ⇒ F0.8 verplicht
  in scope; budget/target ⇒ nieuwe configureerbare invoer met zes-sync-punten).
- Drilldown: van metric naar onderliggende regels (bestaande data).

### Testprotocol TP-2

| ID | Test | Verwacht | Kritiek |
|---|---|---|---|
| TP2-01 | Regressie + golden parity (features ongebruikt) | Groen; 0 afwijkingen | ja |
| TP2-02 | Opmerking plaatsen op regel/machine/periode | Zichtbaar met gebruiker+datum; indicator op cel | ja |
| TP2-03 | Opmerking met `<script>`/HTML/emoji/lange tekst | Letterlijk weergegeven, geen uitvoering, geen layoutbreuk | ja |
| TP2-04 | Opmerkingen: herstart, instance-wissel, reset, scenario save/load, duplicate | Gedrag conform ontwerpkeuze per actie (vooraf vastleggen: blijft reset-proof of niet) en consistent na replay | ja |
| TP2-05 | Excel-export met opmerkingen (indien in scope) | Celcommentaar + overzichtstabblad kloppen | ja |
| TP2-06 | Drilldown openen voor 3 machines (incl. één met overrides, één ZZ-groep) | Cijfers identiek aan planningstabel/L07-L12; overrides zichtbaar | ja |
| TP2-07 | Drilldown open terwijl elders een edit cascadeert | Paneel ververst of toont expliciet "verouderd" — nooit stilzwijgend stale | ja |
| TP2-08 | Throughput direct invoeren; herberekening | L07/L09/L10/L12 consistent; terugrekening klopt met afgesproken eenheid | ja |
| TP2-09 | Throughput: herstart/reset/instance-wissel | Zes sync-punten aantoonbaar; replay identiek | ja |
| TP2-10 | Throughput-invoer vs. indirecte route (OEE) die hetzelfde effect heeft | Zelfde eindcijfers (consistentiecontrole) | ja |
| TP2-11 | Afwijkingsweergave tegen gekozen referentie; controle met handberekening van 3 waardes | Klopt op 2 decimalen | ja |
| TP2-12 | Financiële drilldown: van metric naar onderliggende regels | Som onderliggend = metric | ja |
| TP2-13 | Metrics bij ontbrekende referentie (eerste cyclus / geen budget) | Nette lege staat, geen crash/∞ | ja |

**GO-criteria fase 2:** alle kritieke PASS · voor elke nieuwe store (opmerkingen,
throughput, evt. budget) zijn de zes sync-punten elk met een geslaagde test
aangetoond · regressie + golden parity groen.
**NO-GO:** een sync-punt-gat (bijv. opmerkingen weg na herstart) is per definitie
blocker — dit is precies de bugklasse uit het register.

---

## 6. Fase 3 — Dynamische producten (GEBOUWD, 2026-07-11)

Status: **gebouwd op branch `fase-3`** als volwaardige feature (besluit
opdrachtgever 2026-07-11: geen aparte PoC-omgeving; de PoC-criteria TP3-01..06
zijn de acceptatietests van de feature zelf). Ontwerp: additieve per-sessie
**product-overlay** (zie [ontwerpnota-fase3.md](ontwerpnota-fase3.md)) —
workbook blijft bron van waarheid, zonder overlay is de berekening
byte-voor-byte identiek.

Geleverd: `modules/product_overlay.py` (contract, validatie NL,
cyclusdetectie), STEP 1c-hook in `planning_engine.py`, alle zes
state-sync-punten, `/api/products/added` (GET/POST/DELETE met structurele
rebuild + rollback), beheer-kaart in de Config-tab met product-modal
(BOM-koppelingen, routing, inkoop- en financiële velden, per-periode volumes).

### Acceptatiecriteria — status

| ID | Criterium | Status | Bewijs |
|---|---|---|---|
| TP3-01 | Nieuw product correct in L01–L12, waarde-overlay en export | **PASS** | `tests/test_product_overlay_golden.py` (standalone + integrated) |
| TP3-02 | Golden parity: export verschilt uitsluitend in regels van het nieuwe product | **PASS** | `test_parity_existing_rows_unchanged` (assert_frame_equal) |
| TP3-03 | Product als child én als parent (dependent demand beide richtingen) | **PASS** | `test_dependent_demand_parent_direction` / `_child_direction` |
| TP3-04 | Herstart: product overleeft rebuild/replay | **PASS** | `test_restart_rebuild_and_replay_restore_product_and_edit` |
| TP3-05 | Verwijderen laat geen wees-regels of kapotte cascade achter | **PASS** | route-prune (`prune_material_state`) + `test_delete_removes_and_prunes_material_state` |
| TP3-06 | Performance binnen 20% van huidig niveau | **PASS** | meting 2026-07-11: baseline min 5,43 s vs 5 producten min 4,23 s (binnen meetruis, geen degradatie) |

### Bekende beperkingen (v1)

- **MoM-vergelijking tussen cycli** toont nieuwe producten niet (inner-join,
  hangt aan BUGS.md H3). De sequentiële MoM in de export werkt wel.
- **Alleen bestaande machines** als routing-doel; nieuwe machines zijn een
  latere iteratie.
- Werkboek-materiaalnummers worden hard geweigerd; advies eigen reeks
  (9xxxxxxxx). Producten toevoegen kan pas ná de eerste berekening.
- Reset behoudt toegevoegde producten (het is configuratie, geen bewerking).

### Teststrategie-uitbreiding sessiegrenzen (2026-07-11)

Naar aanleiding van de bug "producten verdwijnen na sessiewissel" is de
teststrategie uitgebreid van geïsoleerde sync-punt-tests naar **overgangen**:

- **Sessie-first herberekenen**: `/api/calculate` neemt per-sessie config
  (forecast-defaults, VP, PAP, producten) via `get_calculate_config_overrides`
  — een stale global-spiegel kan niets meer droppen of laten erven. Unit-tests
  dekken beide richtingen; integratietests dekken wissel + herberekenen.
- **Gedeelde rebuild-lock** (`ui/locks.py`): calculate, product-CRUD,
  structurele config-rebuilds en switch-restore zijn geserialiseerd;
  concurrency-test met overlap-detectie.
- **Echte herstart-integratietest** (`tests/test_session_switch_products.py`):
  proces killen + herstarten op dezelfde app-data; elke sessie behoudt eigen
  producten/defaults, geen kruisbesmetting. Plus snapshot-, Reset- en
  upload-erfenis-scenario's.
- **Scenario's × producten (besluit)**: een scenario registreert de
  productenlijst bij opslaan; laden herstelt producten NIET (dat zou een
  structurele rebuild zijn) maar waarschuwt in het Nederlands wanneer de
  lijst niet meer klopt. Oude scenario's (zonder veld) waarschuwen niet.
- **Reset-contract**: Reset wist bewerkingen, behoudt dynamische producten.
- **Export-smoke**: volledige `to_excel_with_values` met overlay-product.
- **Werkboek-drift**: botst een nieuw bronbestand met een eerder toegevoegd
  productnummer, dan faalt de switch-restore netjes (`failed` + NL-melding).
- **UI**: de productenkaart ververst bij sessiewissel (browser-test).

### Grafiek-analyse (dashboard, 2026-07-11)

In de vergrote grafiek (zoom-modal) verklaart de knop **"Analyse"** stijgingen
en dalingen: automatische detectie van de grootste beweging (of klik twee
punten voor een eigen segment) met een zijpaneel met de top-bijdragen,
"Overige"-rest en de som-tegenover-grafiekbeweging-controle. Volledig
client-side; hergebruikt bestaande endpoints.

| Grafiek | Verklaring |
|---|---|
| Financiële metrics (dashboard + values-tab) | per product (omzet, grondstofkost, machinekost, FTE-kost, voorraadwaarde); afgeleide metrics (COGS, brutomarge, EBITDA, EBIT) via exacte componentsplitsing, doorklikbaar naar producten |
| Demand trend / Inventory vs Target | top-productbewegingen (zelfde linetypes als de grafiek sommeert) |
| Machine-utilization (dashboard + capaciteits-slots) | exacte splitsing benodigde-uren-effect vs capaciteitseffect + grootste productbewegingen op de machine (volumes, expliciet gelabeld) |
| FTE per groep | per-machine urenbijdragen (eerlijkheidsnotitie: FTE volgt uit uren) |
| Inventory quality | per materiaal per bucket (onder-/veiligheids-/overvoorraad) |
| ROCE(-componenten) | exacte ratio-splitsing EBIT-effect vs kapitaaleffect; kasstroom = EBITDA-effect + voorraadmutatie |

Eerlijkheidsregels: bijdragen die niet exact optellen (bezetting, FTE) worden
als zodanig benoemd; referentielijnen (targets/gemiddelden) zijn uitgesloten;
nieuwe/verdwenen producten verschijnen vanzelf als 100% van de beweging.

### Materiaalgroepen (2026-07-11)

Opgeslagen, benoemde productsets per sessie (bijv. "Top movers 2026-04 →
2026-06", bewaard vanuit de grafiek-analyse) met twee gebruiksmodi:

1. **Filtermodus**: dropdown in de planningstoolbar filtert de tabel op de
   groep, vrij combineerbaar met linetype-filter en zoeken (dit verving en
   repareerde de fragiele materiaal-scope die door badge-refreshes werd
   gewist). Beheer (activeren, hernoemen, verwijderen) via het ⚙-menu.
2. **Actieve groep ("maak actief")**: het HELE programma toont alleen de
   groepsbijdrage — dashboard (trends, inventory quality, top-10, KPI's),
   values-tab en machines-tab — met een permanente banner op elk tabblad en
   één klik deactiveren. Scoping gebeurt server-side op de read-endpoints
   (view-laag; de engine wordt nooit aangeraakt, zonder actieve groep zijn
   de payloads byte-identiek).

Eerlijkheidsregels bij een actieve groep:
- Financieel toont uitsluitend toerekenbare cijfers + **bijdragemarge**
  (groepsomzet − grondstofkost − machinekost, "excl. vaste kosten");
  EBIT(DA), brutomarge, ROCE, kapitaal en kasstroom worden bewust verborgen.
- Machinebezetting = het **groepsaandeel** (urenratio); capaciteit, OEE en
  beschikbaarheid blijven de volledige machine; machine-bewerken is
  geblokkeerd zolang een groep actief is.
- FTE is niet toerekenbaar en blijft fabrieksbreed (expliciete notitie).
- Verwijderde producten worden uit groepen gepruned; onbekende nummers na
  een nieuw bronbestand worden genegeerd en in de banner geteld.

Persistentie: groepen + actieve status per sessie (sessions_store), gekopieerd
naar instantie-snapshots, meegeleverd in het switch-payload; géén global
config, baseline, replay of recalc (pure view-metadata). Export en MoM zijn
in v1 bewust niet gescoopt.

### Master-config vervanging — gradatie (a) GEBOUWD (2026-07-11)

Klantvraag 5 is beantwoord met gradatie (a): **de app is eigenaar van de
masterdata**. Kernontwerp: de store bewaart POST-PARSE data — de import
draait de bestaande, VBA-getrouwe xlsm-loader precies één keer en
serialiseert het resultaat; het store-geladen pad deserialiseert alleen.
Er is dus géén tweede parser en de pariteit is exact getest (golden
round-trip: elke masterstructuur identiek aan de xlsm-loader).

- **Eenmalige import** (Config-tab "Masterdata (in app)"): parse master-.xlsm
  → `master_store.json` met versieteller. Re-import over bestaande data
  vraagt bevestiging met diff (de app is bron van waarheid).
- **Werkboek-vrij rekenen**: de multi-upload gebruikt automatisch de
  app-masterdata; de maandelijkse run heeft alleen nog de 4 SAP-extracts
  nodig. Rebuilds/herstarts halen altijd de láátste storeversie op.
- **Beheer-UI**: per dataset bekijken/bewerken (materialen, machines/OEE,
  veiligheidsvoorraad, inkoop lead-time/MOQ, prijzen, kosten, valuatie);
  elke wijziging wordt gevalideerd door hydratie (geen tweede regelset),
  bumpt de versie en geldt bij de eerstvolgende berekening.
- **Compatibiliteit**: de single-file-flow (één complete .xlsm) is
  regel-voor-regel onaangeroerd — golden parity blijft het vangnet. Het
  legacy-masterbestand blijft werken als terugvaloptie én als importbron.

**Volledig Excel-vrij?** Masterdata: ja. De maandelijkse transactiedata
(forecast, voorraad, BOM/routing-extracts) blijven SAP-exports; die worden
pas Excel-vrij met een directe SAP-koppeling (gradatie (c)) — dat vergt
API/DB-toegang van Sibelco plus een security review en staat als aparte
vervolgstap open. De koppeling hoeft dan alleen nog de extracts te vervangen.

---

## 7. Overkoepelende testaanpak

- **Automatisch, elke fase:** volledige pytest-suite (uitbreidend per feature; elke
  bugfix/feature met eigen regressietest), `main.py --test`, en de golden-parity-diff
  (script: run → export → cellenvergelijking met vorige tag).
- **Handmatig, elke fase:** het TP-protocol hierboven, uitgevoerd door iemand anders
  dan de bouwer, vastgelegd in een kopie van het protocol met PASS/FAIL + bewijs
  (screenshot/exportbestand), zelfde format als de bestaande HUMAN_VERIFICATION-documenten.
- **Acceptatie klant:** per release een korte demosessie met Sacha; klant-GO is
  onderdeel van de release (documenteren in het protocol).
- **Release:** git-tag per fase, exe-build (packaging in `extra/packaging`) na GO,
  changelog per release. Rollback = vorige tag + vorige exe; sessies op schijf
  blijven leesbaar (alle nieuwe velden optioneel).

## 8. Beslispunten die nu open staan

| Vraag (uit antwoordmail) | Blokkeert | Deadline-advies |
|---|---|---|
| 1. Opmerkingen: vrije tekst? in export? | 2.1 | vóór start fase 2 |
| 2. Throughput: eenheid + terugrekenwijze | 2.3 | vóór start fase 2 |
| 3. Afwijkingen: referentie | 2.4 (en F0.8) | vóór einde fase 0 (bepaalt of MoM-fix in fase 0 moet) |
| 4. Defaultvolumes: doel/niveau/wanneer | 1.3 | vóór start fase 1 (1.1/1.2 kunnen zonder) |
| 5. Integratiegradatie a/b/c | fase 3 | vóór werksessie fase 3 |
| 6. Dynamische producten: harde wens? | fase 3 | vóór werksessie fase 3 |
| Extra (intern): H1 `months_actuals` werkend maken of verwijderen | los | vóór einde fase 1 |
