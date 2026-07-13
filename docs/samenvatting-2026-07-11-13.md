# Samenvatting — werk na de grote bughunt (11–13 juli 2026)

Compleet overzicht van alles wat na de exhaustieve bughunt (10 juli, baseline
`Baseline before bugfix round`) is gebouwd, gefixt en gevalideerd op branch
`fase-3`. Niets weggelaten; kleine items staan kort. Tag `milestone-fase-3`
wijst naar de laatste commit. Backend- en browsersuites en de golden-parity
zijn op elk milestone groen.

---

## 1. Nieuwe functionaliteit

### Fase 1 — dashboard & bewerken
- **Grafiek-zoom modal** — grafieken vergroten in een pop-up (`7a26e60`).
- **Bulk-edit** — endpoint + sleep-selectie (rij én kolom) + gegroepeerde
  undo/redo; procent-schaal-lijnen uitgesloten (`5c60f4c`, `cb9353e`, `cc5f224`).
- **Configureerbare forecast-standaardvolumes** (opt-in: lege perioden vullen
  of optellen) (`bb7196f`).

### Fase 2 — analyse & annotatie
- **Commentaar/annotaties per cel**, per sessie, met een zichtbare "dog-ear"-
  hoekindicator; komt mee in de export (`024f2f1`, `4a0ac63`).
- **Machine-drilldown** — alleen-lezen detail per periode: welke producten
  draaien op een machine (`d1ff765`).
- **Directe effectieve-doorzet-regeling** — doeldoorzet ingeven, OEE wordt
  evenredig aangepast (`d26af63`, inline in de tabel `123d61f`).
- **Financiële afwijking + trend + drilldown** — metrics t.o.v. de baseline met
  doorklik naar de onderliggende regels (`8446e58`).

### Fase 3 — dynamische producten
- **Product-overlay + BOM-cyclusdetectie** — producten die niet in het
  bronbestand staan volledig doorrekenen (`417a9a8`, `a3196f7`).
- **CRUD + beheer-UI** in de Config-tab (`8aca4c7`, `dc70c7c`).
- **Sourcing-selector** (aangekocht / geproduceerd / mix) met combinatie-
  matrixtests (`32ab3f9`).
- **Financiële data exact geverifieerd** voor toegevoegde producten (`c04a9a6`).
- Meegenomen door **alle zes state-sync-punten**; fix voor verdwijnen/lekken
  bij sessiewissel (`95866a8`, `ab59451`).

### Grafiek-analyse (het "Analyse"-paneel)
- Verklaart stijgingen/dalingen per product; automatische detectie + twee
  punten klikken met verbindingspijl; op alle grafieken; bijdragen
  reconciliëren met het totaal.
- FTE-drill naar producten, top-movers naar de planningstabel, Excel-export.
- Commits: `30f49ce`, `1211075`, `d902b47`.

### Materiaalgroepen
- Opgeslagen groepen + dropdownfilter, combineerbaar met linetype-filters, per
  sessie persistent, overleeft herstart.
- "Maak actief" scopet dashboard + machines met een eerlijke **bijdragemarge**
  (omzet − grondstofkost − machinekost); vaste kosten, EBIT, ROCE en FTE blijven
  bewust fabrieksbreed; export blijft fabrieksbreed.
- Commits: `9abc686`, `210640f`, `820baf2`, `b98e331`, `78169a4`, `0d8b409`.

### Masterdata in de app (master-config vervangen)
- Masterdata (materialen, machines/OEE, FTE, veiligheidsvoorraad, inkoop,
  kosten, valuatie) wordt door de app beheerd i.p.v. een los basis-.xlsm.
- Eenmalige import → app-store + beheer-UI (grids per dataset); maandelijkse
  berekening heeft alleen de SAP-extracts nodig; app is de bron van waarheid
  (re-import met diff-bevestiging); post-parse opslag (geen tweede parser).
- Commits: `e12fd07`, `e513f6f`, `efc9c8b`, overlay-fix `21c9260` (§4).

---

## 2. Robuustheid & beveiliging (fixes uit de review na de bughunt)
- **Locale-aware invoer** — Nederlandse komma-decimalen ("2,5") (`d2ff04d`).
- **XSS** — werkboek-strings escapen in innerHTML-renderpaden (`1eb1434`).
- **Path traversal + stdout-race** in de master-file-uploadroute (`f245734`).
- **Scenario-persistentie** — scenario's opslaan en override-stores herafleiden
  bij laden (`ffcdcfd`).
- **Edit-serialisatie + sessiewissel-bescherming** bij in-flight edits
  (`9740234`).
- **`purchased_and_produced` per sessie** persistent (`9b012ff`).
- **Overzichtsgrafieken** afgeschermd tegen ontbrekende consolidatiedata
  (`73028a4`).
- **Vendor-assets hersteld** (Tailwind + Chart.js) (`3c69074`).
- Review-fixes: sessiewissel-guard bij enqueue, doorzet-plafondmelding, export-
  commentaar-guard, groep-bewuste stack-trim, redo behouden bij mislukte batch,
  één recalc per bulk, session-first forecast-defaults (`b9da659`, `da98969`,
  `2b6a963`).

---

## 3. Teststrategie-uitbreidingen
- Spiegel-gat forecast-defaults/valuatie/PAP + gedeelde rebuild-lock (`04618c0`).
- Echte procesherstart-test + Reset-contract (integratie) (`02c4a6f`).
- Scenario-semantiek, export-smoke, drift-detectie, UI-refresh (`45ccfad`).

---

## 4. Bugfixes

### Gevonden tijdens de handmatige validatieronde (12–13 juli)
1. **Getalparser accepteerde misvormde invoer** (`8dc4931`). "3000,5,6" werd
   stil 300056; "12abc" werd 12. Nu: groepering moet echte groepen van drie
   zijn en het hele veld een geldig getal; anders weigering. Regressietest.
2. **Numerieke nul-aux resurrecteerde na herstart** (`a82f824`). Een edit op een
   rij met `aux_column = 0` overleefde de undo en dook na herstart weer op
   (`aux or ''` → sleutel-mismatch). Canonieke aux-normalisatie + regressietests.
3. **Toegevoegd product niet bruikbaar als component** (`f8e186f`). De
   materialenlijst filterde toegevoegde producten weg; nu getoond (gemarkeerd).

### Eerder gemeld en gefixt
4. **Masterdata-wijziging kwam niet door bij herberekening** (`21c9260`). De
   store voedde alleen werkboek-vrije sessies; nu overlay bij élke berekening
   (merge per sleutel — app wint, maand-SKU's blijven; Config-ankers en
   purchase-actuals blijven van het werkboek).
5. **Groepsdropdown vast in de groepsweergave** (`f710c1c`). Terugschakelen naar
   "Alle groepen" werkte niet bij een actieve groep; opgelost + testgat gedicht.
6. **Klasse-audit: drie verwante combinatiefouten** (`c39b9f3`). Scope overleefde
   sessiewissel, undo herstelde over een actieve groep, lege doorsnedes zonder
   uitleg — alle drie gefixt + lege-tabel-vangnet ("Herstel filters").

### Uit de bughunt zelf (10 juli, ter volledigheid)
Reset herstelde `shift_hours_override` niet; teruggedraaide edits pinden
overrides; error-tuples braken callers; stdout-races en upload-path-traversal;
sessie-thread-safety en niet-atomische globale config-writes — plus een
bugregister uit een viervoudige agent-codescan.

### Weerlegde schijnbug
Een vermoede "undo herstelt BOM-kind niet"-bug bleek geen defect: het
testmateriaal (Chalk) stond nog gedeactiveerd van een eerdere test. Met een
actief materiaal round-trippt de undo exact; de rekenkern is niet gewijzigd en
de aangezette onvolledige fix is teruggedraaid.

---

## 5. UI-verbeteringen uit feedback
- **Verkoopprijzen-grid: prijs per eenheid als invoerveld** (`96bc661`). De bron
  kent alleen volume + ExWorks-omzet; de grid toont nu een bewerkbare prijs
  (= omzet / volume) met live herrekening.
- **Config-tab gesplitst** (`1d7b319`) in "Deze instantie" vs "App-breed" met een
  waarschuwing dat app-brede wijzigingen in elke instantie doorwerken.
- **Rij-gewijze bulk-selectie**, zichtbare commentaar-dog-ear, machine-producten
  + doorzet-delta's (`4a0ac63`).

---

## 6. Handmatige validatieronde (128 checks)
Volledige app tegen de live-server gevalideerd via een checklist die is
uitgebreid naar **128 controles in 9 domeinen** (A masterdata 12, B sessies 10,
C bewerkingen 12, D producten 14, E analyse 18, F groepen 22, G machines 14,
H exports 14, I afsluiting 12), elk met API-verificatie náást een screenshot.
De edit-checks tonen een **VOOR/NA-beeld** (grote, leesbare composities in het
werkboek). **Resultaat: 128/128 OK** (de eerder gevonden parser-afwijking is
gefixt en zit nu als geslaagde regressie in de suite).

Diepere verificaties o.a.: totale vraag = forecast + afhankelijke vraag
(360/360 cellen), voorraad lopend saldo L04 (480/480 cellen), geen NaN/inf
(0 op 23.772 waarden), alle 14 linetypes aanwezig, bijdragemarge = omzet −
grondstof − machinekost (exact), omzet = prijs × volume per product (exact),
masterdata-bewerkingen (naam/prijs/OEE/veiligheidsvoorraad/valuatie/kosten)
werken door herberekening, materiaal deactiveren/reactiveren, undo/redo,
herhaalde edits, BOM-cyclusdetectie, mix-grenswaarden 0/1, MOQ > vraag,
effectieve doorzet ~ OEE, overbezetting >100%, unlimited-machine, groep = hele
fabriek, groep hernoemen/1-materiaal/lege-naam, export FTE/kwaliteit/values-
sheets, DB-kolomstructuur, scenario opslaan/laden, derde instantie
aanmaken/verwijderen, KPI's byte-identiek na herstart. Ook gevalideerd:
commentaarvelden, bulk-edits + sleep-selectie, L04-startvoorraad, capaciteits-
overrides (persistent na herstart), MoM- en DB-export, machine-drill.

De checklist zelf staat in `docs/checklist-manuele-validatie.md`; het ingevulde
werkboek met VOOR/NA-screenshots in
`exports/Checklist_manuele_validatie_Apex_Rainier_VOLLEDIG.xlsx`.

---

## 7. Test- en documentdeliverables
- `docs/checklist-manuele-validatie.md` — de 92-check checklist (`2051c72`,
  `7f0e430`).
- `docs/validatielijst-fase3.md` — elke functie gekoppeld aan de dekkende
  geautomatiseerde tests (`86e0237`).
- `docs/testverslag-fase3.md` — formeel testverslag met garantie-onderbouwing;
  bijgewerkt met de 92-check ronde (`7296f9e`, `4c35b96`).
- `exports/` (klantdata, buiten git): ingevuld Excel-werkboek met 92
  screenshots, Word-versie, en demo-PPT met live screenshots.

**Suites (laatste run):** backend 682 geslaagd / 1 overgeslagen · browser 74
geslaagd · golden-parity (`python main.py --test`) groen.

---

## 8. Openstaande punten
- **Chalk (150000483) staat inactief** — matcht de A8-demo waarin het bewust
  werd uitgeschakeld. Reactiveren kan met een volledige herberekening.
- **Per-sessie prijs/kost-overrides** (scenario's zonder de app-masterdata te
  raken): eerst een plan schrijven, dan bouwen (valuation-params-patroon).
- **SAP-koppeling** voor de maandelijkse extracts (volledige Excel-vrijheid) —
  aparte vervolgstap.
- **Export/MoM gescoopt op groepen** — bewust niet in v1 (groepen scopen alleen
  de weergave).
- **Forecast-standaardvolumes-revisie** — geparkeerd als klantkeuze (`1c927e6`).
- **Merge `fase-3` → `main`** — wacht op akkoord.
