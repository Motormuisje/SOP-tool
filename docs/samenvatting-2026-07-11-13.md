# Samenvatting — werk na de grote bughunt (11–13 juli 2026)

Overzicht van alles wat na de exhaustieve bughunt is gebouwd, gefixt en
gevalideerd op branch `fase-3`. Alle genoemde commits staan op die branch;
tag `milestone-fase-3` wijst naar de laatste. Backend- en browsersuites en de
golden-parity zijn op elk milestone groen.

---

## 1. Nieuwe functionaliteit

### Grafiek-analyse (dashboard)
Een "Analyse"-knop in elke vergrote grafiek die stijgingen/dalingen verklaart
per product.
- Automatische detectie van de grootste beweging + handmatig twee punten
  klikken met een verbindingspijl.
- Werkt op alle grafieken (financieel, volume, FTE, machines, voorraadkwaliteit);
  bijdragen reconciliëren met het totale verschil.
- FTE-drill naar producten, top-movers doorklikken naar de planningstabel
  (om invoerfouten te corrigeren), en Excel-export van de analyse.
- Commits: `30f49ce`, `1211075`, `d902b47` (feedbackronde).

### Materiaalgroepen
Opgeslagen groepen (bv. "top 10 movers 04-26→06-26") met een dropdownfilter en
een "maak actief"-modus die het hele programma scopet.
- Filter combineerbaar met linetype-filters; per sessie persistent; overleeft
  herstart.
- "Maak actief" scopet dashboard + machines op de groep met een eerlijke
  **bijdragemarge** (omzet − grondstofkost − machinekost); vaste kosten, EBIT,
  ROCE en FTE blijven bewust fabrieksbreed.
- Groepen ontstaan vanuit de analyse; export blijft fabrieksbreed.
- Commits: `9abc686`, `210640f`, `820baf2`, `b98e331`, `78169a4`, `0d8b409`.

### Masterdata in de app (master-config vervangen)
De masterdata (materialen, machines/OEE, FTE, veiligheidsvoorraad, inkoop,
kosten, valuatie) wordt nu door de app beheerd in plaats van een los basis-.xlsm.
- Eenmalige import → app-store + beheer-UI (grids per dataset) in de Config-tab.
- De maandelijkse berekening heeft alleen nog de SAP-extracts nodig; de app is
  de bron van waarheid (re-import vraagt bevestiging met een diff).
- De store bewaart post-parse data (geen tweede parser) — golden-pariteit exact.
- Commits: `e12fd07`, `e513f6f`, `efc9c8b`, en de overlay-fix `21c9260` (zie §2).

---

## 2. Bugfixes

### Gevonden tijdens de handmatige validatieronde (12–13 juli)
1. **Getalparser accepteerde misvormde invoer** (`8dc4931`). "3000,5,6" werd
   stil 300056; "12abc" werd 12. Nu: groepering moet echte groepen van drie
   zijn en het hele veld een geldig getal; anders weigering. Regressietest met
   13 gevallen + het gemelde scenario.
2. **Numerieke nul-aux resurrecteerde na herstart** (`a82f824`). Een edit op een
   rij met `aux_column = 0` overleefde de undo en dook na herstart weer op
   (`aux or ''` behandelde 0 als leeg → sleutel-mismatch). Gefixt met een
   canonieke aux-normalisatie; regressietests toegevoegd.
3. **Toegevoegd product niet bruikbaar als component** (`f8e186f`). De
   materialenlijst filterde alle toegevoegde producten weg. Nu getoond
   (gemarkeerd "toegevoegd"); live geverifieerd dat product B product A als
   BOM-component gebruikt.

### Eerder gemeld en gefixt
4. **Masterdata-wijziging kwam niet door bij herberekening** (`21c9260`). De
   app-store voedde alleen werkboek-vrije sessies; nu overlayt hij bij élke
   berekening ook werkboek-sessies (merge per sleutel — app wint, nieuwe
   maand-SKU's blijven; Config-ankers en purchase-actuals blijven van het
   werkboek).
5. **Groepsdropdown vast in de groepsweergave** (`f710c1c`). Terugschakelen naar
   "Alle groepen" werkte niet bij een actieve groep; opgelost, en het testgat
   (tests dreven de echte `select` niet aan) gedicht.
6. **Klasse-audit: drie verwante combinatiefouten** (`c39b9f3`). Scope overleefde
   sessiewissel, undo herstelde over een actieve groep, en lege doorsnedes gaven
   geen uitleg — alle drie gefixt, met een lege-tabel-vangnet ("Herstel filters").

### Weerlegde schijnbug
Een aanvankelijk vermoede "undo herstelt BOM-kind niet"-bug bleek geen defect:
het testmateriaal (Chalk) stond nog gedeactiveerd van een eerdere test, waardoor
de volledige build 0 gaf en de incrementele cascade een waarde. Met een actief
materiaal round-trippt de undo exact. De rekenkern is niet gewijzigd; de
onvolledige fix die ik had aangezet is bewust teruggedraaid.

---

## 3. UI-verbeteringen uit feedback
- **Verkoopprijzen-grid: prijs per eenheid als invoerveld** (`96bc661`). De bron
  kent alleen volume + ExWorks-omzet; de grid toont nu een bewerkbare prijs
  (= omzet / volume) met live herrekening, i.p.v. de twee rauwe totalen.
- **Config-tab gesplitst** (`1d7b319`) in "Deze instantie" (planning-config,
  valuatie, producten) en "App-breed" (masterdata, mappen) met een waarschuwing
  dat app-brede wijzigingen in elke instantie doorwerken.
- **Effectieve doorzet inline bewerkbaar** in de machinetabel (`123d61f`).

---

## 4. Handmatige validatieronde (92 checks)
De volledige applicatie is tegen de live-server gevalideerd via een checklist
van **92 controles in 9 domeinen** (A masterdata, B sessies, C bewerkingen,
D producten, E analyse, F groepen, G machines, H exports, I afsluiting). Elke
check draaide tegen de draaiende app, waar mogelijk met API-verificatie van de
onderliggende cijfers náást een screenshot.

**Resultaat: 91/92 OK, 1 afwijking** (de getalparser-bug, tijdens de ronde
gefixt en als bewijs bewaard).

Diepere verificaties o.a.:
- Totale vraag = forecast + afhankelijke vraag: 360/360 cellen exact.
- Bijdragemarge = omzet − grondstofkost − machinekost: exact (gescoopte P&L).
- Omzet = prijs × volume voor toegevoegde producten: exact per product.
- Undo van een BOM-parent-edit herstelt het actieve kind exact naar baseline.
- Effectieve doorzet schaalt lineair met OEE (basis van de doeldoorzet-functie).
- KPI's byte-identiek voor/na een echte procesherstart.

---

## 5. Test- en documentdeliverables
- **`docs/checklist-manuele-validatie.md`** — de 92-check checklist (`2051c72`,
  `7f0e430`).
- **`docs/validatielijst-fase3.md`** — elke functie gekoppeld aan de dekkende
  geautomatiseerde tests (`86e0237`).
- **`docs/testverslag-fase3.md`** — formeel testverslag met garantie-onderbouwing;
  bijgewerkt met de 92-check ronde en de bevindingen (`7296f9e`, `4c35b96`).
- **`exports/` (klantdata, buiten git):** ingevuld Excel-werkboek met 92
  screenshots, een Word-versie, en de demo-PPT met live screenshots.

**Suites (laatste run):** backend 682 geslaagd / 1 overgeslagen · browser 74
geslaagd · golden-parity (`python main.py --test`) groen.

---

## 6. Openstaande punten
- **Chalk (150000483) staat inactief** — dit matcht de A8-demo waarin het
  bewust werd uitgeschakeld. Reactiveren kan met een volledige herberekening.
- **Per-sessie prijs/kost-overrides** (scenario's zonder de app-masterdata te
  raken): afgesproken om ná de validatieronde eerst een plan te schrijven,
  dan te bouwen (valuation-params-patroon).
- **SAP-koppeling** voor de maandelijkse extracts (volledige Excel-vrijheid) —
  aparte vervolgstap.
- **Export/MoM gescoopt op groepen** — bewust niet in v1 (groepen scopen alleen
  de weergave).
- **Merge `fase-3` → `main`** — wacht op akkoord.
