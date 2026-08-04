# Plan F2-CF — Capaciteits- en FTE-optimalisatie (werkbank)

**Site-scope: uitsluitend Maastricht (SAP-site `NLX1`) — dit is de hoofdrepo
`SOP tool/SOP_Git`.** Niet Winterswijk (`SOP-WSK`, NLK1) en niet Ankerkade
(`SOP-ANK`, NLU1). Alle datamodel-, reken- en UI-keuzes hieronder zijn ontworpen
en gevalideerd tegen het Maastricht-model; de site-uitgaven krijgen deze
functionaliteit pas via de normale synchronisatie uit de hoofdrepo, en dan met
hún eigen masterdata-waarden. Waar hieronder WSK/ANK genoemd wordt, gaat het om
open vragen of vervolgwerk buiten deze scope — niet om deliverables van dit plan.

Status: **uitgevoerd** (2026-08-03) — zie §8 voor wat er staat en wat open bleef.
Datum plan: 2026-08-03 · Bron-requirements: charter §7.4
(F2-CF-01..05) · Klantinput: `OEE model MTO APEX voorbeeld.xlsx` (Maastricht,
NLX1) · Uitvraag: `Uitvraag_Informatiebehoefte_FTE_Simulatie_{WSK,MST_Ankersmit}_v2.docx`

---

## 1. Wat het klantbestand is — en hoe we het gebruiken

Het bestand is het handmatige Maastricht-OEE/FTE-model. Relevante bladen:

| Blad | Inhoud | Rol in dit plan |
|---|---|---|
| `FTE` | Afleiding effectieve uren per FTE (2080 → 1.492,48 na verlof, ADV, feestdagen, 10% ziekte, 2% training), bezettingsgraad 85%, jaaruren per ploegensysteem (2-ploegen 4.160, 3-ploegen 6.240, 24/7 8.760) | Seed voor de FTE-parameters in de masterdata; het rekenmodel dat `fte_engine` moet reproduceren |
| `Normen ` | Per productie-unit × product: MES-doorzet vs PEER-doorzet (t/u), performance %, availability %, OEE = perf × avail, t/shift en t/dag; versiebeheer door Productie | Seed voor doorzet/OEE-normen per machine×product; belangrijkste normbron |
| `OEE Model MST ` | Het eigenlijke model: producten × installaties, volume-allocatie → machine-uren → `# FTE Staffing` per groep → FTE-aantal (÷ 1.492) → bezettingsgraad. Onderin: controlekamer, Marl-verlading, truck-laden/-lossen (tijd per truck, ton per truck → aantal trucks → uren) en maintenance-normen (9 machines per FTE; € per machine; % van OPEX) | Functionele specificatie van F2-CF-01/02 én validatie-ground-truth (totaal 311.846 t → 4.008 mill-uren → 2,69 FTE → 64% benutting moet reproduceerbaar zijn) |
| `MES_OEE Mills` | Gemeten OEE per workcenter (MES-actual) naast doelwaarde, met verklaringen | Benchmarkkolom "actual vs norm" in de werkbank |
| `PEER_Capacity` | Doorzet per machine × product uit PEER | Tweede normbron; brontriage nodig (zie §6) |
| `Illness` | Ziekteverzuim | Onderbouwing van de 10%-parameter; geen runtime-input |
| `Pivot FC` / `Export` | Forecast-pivot en platte export | Geen rol: transactionele data komt uit de bestaande SAP-extracts |

**Het handigste gebruik — drie rollen, géén vierde databron:**

1. **Éénmalige seed**: de normen (doorzet/OEE per machine×product, bemensing per
   groep, FTE-parameters, truck- en maintenance-normen) worden overgezet naar
   nieuwe masterdata-datasets en zijn daarna in de app en het masterwerkboek te
   beheren. Het Excel-bestand wordt daarna niet meer ingelezen.
2. **Validatie-ground-truth**: de eindcijfers van het model (uren, FTE,
   benutting per groep, trucks) worden regressietests, zoals de VBA-consolidatie
   dat is voor de planningcijfers (NF-02).
3. **Antwoord op de uitvraag**: voor Maastricht (NLX1) dekt dit bestand het
   merendeel van de OPS/HR-sjablonen uit de uitvraag van 2026-07-28. De uitvraag
   blijft nodig voor: loonkosten per functiegroep (FIN) en de expliciete
   machinecombinatie-regels (sjabloon 2). Het WSK-equivalent valt buiten dit
   plan — dit is een MST-bestand en Winterswijk heeft eigen normen.

Dit bestand NIET als importformaat adopteren: het is een handmatig gegroeid
werkboek zonder stabiele structuur (merged headers, per-groep herhaalde
kolomblokken, jaar- i.p.v. periodegranulariteit). De masterdata-tabellen +
masterwerkboek-export zijn ons bewerkingsmedium; dat spoor is er al.

## 2. Wat er al staat (niet opnieuw bouwen)

- Keten volume → machine-uren → capaciteit per machine/groep bestaat
  (`capacity_engine`, L07/L09/L10) inclusief OEE, beschikbaarheid per periode,
  ploegensysteem en unlimited-machines.
- FTE-basisdata is masterdata sinds de Config/FTE-tabellenstap: uren per jaar,
  ploeguren, standaardploeg — bewerkbaar in de app én het masterwerkboek.
- Machine-overrides (OEE, beschikbaarheid, shifturen) bestaan met undo;
  waardeketen t/m ROCE bestaat (`value_planning_engine`, 20 consolidatieregels).
- Gap (uit de uitvraag-analyse): FTE alleen per machinegroep, loonkosten alleen
  sitebreed, geen operatornormen, geen combinaties, geen werkbank; scenario's
  bewaren machine-overrides niet; scenariovergelijking dekt alleen demand en
  voorraad.

## 3. Datamodel — nieuwe masterdata-datasets

Alles volgens het bestaande stramien: serialize/hydrate/overlay in
`modules/master_data.py`, PATCH-route + CAS, tabblad in het masterwerkboek,
spiegel-rewrite, rij in de masterdata-tabellen-UI, en een stap in de
productwizard waar relevant. De datasets zijn per definitie sitespecifiek; in dit
plan vullen we uitsluitend de Maastricht-waarden (NLX1). De structuur reist via
de normale sync mee naar `SOP-WSK`/`SOP-ANK`, die daar hun eigen waarden invullen
— dat is geen onderdeel van deze oplevering.

1. **`fte_params`** (uitbreiding van bestaande `fte`-dataset):
   bezettingsgraad, ziekte-%, training-%, en de afleiding bruto→effectieve uren
   (nu alleen het eindgetal 1.492). De afleiding blijft optioneel: het eindgetal
   is leidend, de componenten zijn documentatie/afleidingshulp.
2. **`staffing_norms`**: per machinegroep (of machine): benodigde operators per
   draaiend uur — voor NLX1 uit `# FTE Staffing` in het Maastricht-model —, met
   ingangsdatum-loos versiebeheer via de storeversie.
3. **`labor_rates`**: functiegroep → loonkost per FTE per jaar (FIN-uitvraag;
   tot die binnen is één sitebreed tarief als fallback, zoals nu).
4. **`machine_combinations`**: combinatie-ID → machinecodes + operators voor de
   combinatie + doorzet-effect-factor per machine bij gedeelde operator
   (sjabloon 2). Een combinatie is een masterdata-definitie; welke combinatie
   actief is, is scenario-state per sessie.
5. **`indirect_activities`**: controlekamer (vaste bezetting per ploeg),
   truck-laden/-lossen (uur per truck, ton per truck, mix container/pallet/bulk),
   maintenance (machines per FTE, € per machine of % OPEX), overige vaste
   activiteiten. Elk met een driver: vast, per ton, per truck, per machine.
6. **Doorzetnormen per machine×product** bestaan al via SAP-routing in de
   maandextracts. De Normen-sheet wijkt daar soms van af (MES vs PEER vs SAP):
   geen derde normtabel toevoegen, maar de werkbank toont de effectieve
   doorzet en laat per machine×product een masterdata-override toe
   (`throughput_overrides`) met herkomstlabel. Brontriage: zie §6.

## 4. Rekenmodule en UI — gefaseerd

### Fase A — `modules/fte_engine.py` + FTE-regels (F2-CF-01)
Pure functie over de bestaande capacity-uitvoer, additief (geen bestaande
planningsregel verandert; golden blijft byte-gelijk):
- per periode, per machine: benodigde uren (bestaand) × operators-norm ÷
  effectieve FTE-uren per periode → directe FTE;
- ploegensysteem bepaalt beschikbare uren (bestaand) × bezettingsgraad →
  aanbod-FTE en bezettingsgraad-KPI;
- indirecte activiteiten: drivers (ton, trucks, machines, vast) → FTE;
- output: nieuwe regelset "FTE per installatie" + totalen, naast L12.
Tests: unit op de rekenregels + reproductie van het MST-model
(311.846 t → 4.008 u → 2,69 FTE → 64%; truck-aantallen exact).

### Fase B — loonkosten en realtime doorrekening (F2-CF-02)
- `labor_rates` × FTE → personeelskosten per periode/machine(groep) in de
  waardeketen; marge/EBITDA-doorwerking via de bestaande value-planning-cascade.
- Bestaande edit-cascade hergebruiken: volume-, doorzet-, uren- en
  bezettingswijzigingen triggeren dezelfde herberekening als celbewerkingen nu
  (NF-01: cascade < 1 s — FTE-laag is een lichte nabewerking op de bestaande
  resultaten, geen volledige rebuild).

### Fase C — combinaties en vergelijking (F2-CF-03/04)
- Sessie-state "actieve combinatieset" (door alle zes sync-punten);
  doorzet-effect-factor toegepast op de betrokken machines, operators gedeeld.
- Vergelijkingsview: 2+ combinatiescenario's naast elkaar op FTE, benutting,
  kosten, marge, arbeidsproductiviteit (t/FTE). Bouwt op het bestaande
  sessies/scenario-mechanisme; vult meteen de bekende gap dat machine-overrides
  niet in scenario's persisteren (randvoorwaarde, zie §5).

### Fase D — interactieve werkbank (F2-CF-05)
Eén nieuw tabblad "Capaciteit & FTE": tabel machines × (volume-aandeel,
doorzet, OEE-norm vs MES-actual, uren, operators, combinatie, FTE, benutting,
kosten, marge) met live herberekening, dirty-state-balk (bestaand patroon),
undo, en opslag als scenario. Kolom "actual vs norm" uit de MES-benchmark.

### Fase E — validatie en oplevering
- Golden-referentietest op het MST-model (NLX1) — dat is de enige site die dit
  plan oplevert; browsertests werkbank (bewerken → KPI-update → scenario-opslag
  → vergelijking); performancemeting NF-01 vastleggen. Een WSK-golden komt pas
  bij een eventuele WSK-uitrol, zodra sjabloon 1/3 terug is.

## 5. Randvoorwaarden / volgorde

1. **Machine-overrides in scenario's persisteren** (bestaande gap) — nodig
   vóór Fase C/D; klein, apart uit te voeren.
2. Masterdata-datasets (§3) eerst: Fase A rekent er direct uit; UI-tabellen en
   werkboek-tab zijn bestaand stramien (goedkoop na de Config/FTE-stap).
3. Seed-script éénmalig vanuit het klantbestand voor MST/NLX1. Er wordt in dit
   plan géén WSK- of ANK-seed gebouwd; die sites vullen hun masterdata zelf via
   de app/het masterwerkboek nadat de functionaliteit naar `SOP-WSK`/`SOP-ANK`
   gesynchroniseerd is.

## 6. Openstaande beslissingen / vragen aan de klant

1. **Brontriage doorzet**: SAP-routing (huidige motor), MES-norm en
   PEER-capaciteit verschillen per machine×product (bv. PE06/Ank125: 35 vs 27
   t/u). Voorstel: SAP-routing blijft de rekenbron; MES-norm als benchmark in
   de werkbank; afwijking > X% krijgt een signaalkleur. Klant bevestigt de
   voorkeursbron per unit.
2. **WSK-equivalent** van dit model — bestaat dat, of vullen we sjabloon 1/3
   handmatig? (Blokkeert dit plan niet: relevant voor een latere WSK-uitrol.)
3. **Loonkosten per functiegroep** (FIN-uitvraag) — tot dan sitebreed tarief.
4. **Combinatieregels expliciet** (sjabloon 2): welke combinaties zijn
   toegestaan en wat is het doorzet-effect van een gedeelde operator?
5. FTE-norm WSK 1.442 vs MST-model 1.492 u/jaar (bekende validatievraag). Voor
   dit plan geldt 1.492 (NLX1); het verschil is een sitewaarde in masterdata,
   geen rekenverschil.
6. Maintenance-FTE: meenemen als indirecte activiteit (9 machines/FTE) of
   buiten scope van de werkbank laten?

## 7. Inschatting

| Fase | Omvang |
|---|---|
| Masterdata-datasets + werkboek-tabs + seed MST | 1 dag |
| A: fte_engine + FTE-regels + MST-golden | 1–1,5 dag |
| B: loonkosten + realtime cascade | 1 dag |
| C: combinaties + vergelijking (incl. override-persistentie) | 1–1,5 dag |
| D: werkbank-UI | 1–1,5 dag |
| E: validatie, browsertests, documentatie | 0,5–1 dag |

Totaal ± 6–7,5 dagen; past binnen M3 van de charter. Fasen A/B leveren op
zichzelf al zichtbare waarde (FTE- en personeelskostenregels in de planning)
en kunnen vóór C/D opgeleverd worden.

Deze inschatting geldt voor Maastricht/NLX1 in de hoofdrepo. Het doorzetten naar
`SOP-WSK` en `SOP-ANK` (bestanden kopiëren buiten de vijf site-specifieke om,
plus daar de eigen masterdata vullen) zit er niet in en is apart werk.

## 8. Uitvoering — wat er staat

| Onderdeel | Waar |
|---|---|
| Zes masterdata-datasets + FTE-parameters | `modules/models.py`, `modules/master_data.py` (`FTE_DATASETS`) |
| Werkboekbladen (optioneel bij import: oude exports blijven werken) | `modules/master_workbook.py` |
| PATCH-routes, versiebump, statustellers | `ui/routes/master_data.py`, `ui/master_store.py` |
| Masterdata-tabellen-UI incl. rij toevoegen, csv-/map-/select-kolommen | `ui/templates/index.html` |
| Rekenmodule A/B/C | `modules/fte_engine.py` |
| Wiring + cascade | `modules/planning_engine.py` (`recalculate_fte`), `ui/replay.py` |
| Werkbank-routes en vergelijking | `ui/routes/fte.py` (`/api/fte`, `/combinations`, `/refresh`, `/compare`) |
| Tabblad "Capaciteit & FTE" | `ui/templates/index.html` |
| Machine-overrides + combinaties in scenario's | `ui/routes/scenarios.py` |
| Tests | `tests/test_fte_engine.py`, `test_fte_engine_golden.py`, `test_routes_fte.py`, `test_master_data_fte.py` |

**Additiviteit is gemeten, niet aangenomen**: dezelfde werkboekberekening op
`HEAD` en op de nieuwe code geeft byte-identieke `results` én `value_results`
(sha256 gelijk). Zonder bemensingsnormen reproduceert de werkbank Line 12 exact,
inclusief trucks en controlekamer. Het MST-ijkpunt (311.846 t → 4.008 u →
2,69 FTE → 64%) staat als testcase in `tests/test_fte_engine.py`.

Bewust anders dan het plan:

- **Geen nieuw `LineType`.** De werkbank leeft in `engine.fte_results`, naast
  `value_results`. Een regelset ín `results` zou `EXPECTED_LINE_TYPES`, de
  Excel-export en de golden raken; dat botst met "golden blijft byte-gelijk".
- **Doorwerking in de waardeketen is een herrekening, geen tweede P&L.** De 20
  VBA-consolidatieregels blijven onaangeroerd; de werkbank vervangt alleen de
  directe-FTE-kost en laat alles stroomafwaarts met exact dat verschil meebewegen.
- **Doorzet-overrides bewerk je in de masterdata-tabellen, niet in de werkbank.**
  De werkbank toont het effect en de MES/PEER-benchmark. De werkbank-cel die wél
  bewerkbaar is (operators per draaiuur) schrijft via de gewone masterdata-PATCH
  en ververst daarna de draaiende engine — één eigenaar per getal.
- **Een combinatie bemenst het langst draaiende lid**, niet de som van de leden;
  dat is wat "gedeelde operator" betekent. Openstaand ter bevestiging bij de
  klant (§6.4).

## 9. De seed (§5.3) — uitgevoerd

`tools/seed_fte_masterdata.py` vult de masterdata uit `OEE model MTO APEX
voorbeeld.xlsx`. Het script LEEST het werkboek; er staan geen overgetypte
getallen in. Droogdraaien is de standaard; `--apply` maakt eerst een back-up van
de store en ververst daarna het masterwerkboek. Het rapport (met alle herkomsten
en rekencontroles) hoort in de datamap, niet in de repo — het bevat klantcijfers.

Wat erin ging: de FTE-parameters (2080 → 1492,48 met bezettingsgraad 85%),
10 bemensingsnormen, 9 indirecte activiteiten en 71 benchmarkregels
(MES-OEE + PEER-doorzet). De 24 machines zijn uit het MS_RECONC-werkboek
bijgevuld: de NLX1-store had er **nul**, waardoor een werkboekvrije run geen
capaciteit en dus geen FTE kende. De machinegroepen hebben een leesbare naam
gekregen (ze heetten letterlijk "nan").

Drie correcties op wat dit plan aannam, met het werkboek als bewijs:

1. **De bruto→netto-afleiding is additief, niet stapelend.** Het model trekt
   ziekte (10%) én training (2%) van dezelfde 1696 uur af: 1696 − 169,60 −
   33,92 = 1492,48. Stapelend (×0,90 ×0,98) geeft 1495,87 — 3,4 uur per FTE per
   jaar te veel, en dus structureel te weinig benodigde FTE.
2. **"9" bij onderhoud is een AANTAL FTE, geen "9 machines per FTE"** (§6.6).
   Het model deelt zijn kengetallen dóór 9, en het sitetotaal van 32,06 FTE in
   rij 195 is exclusief onderhoud.
3. **De 4.008 uur / 2,69 FTE / 64% is de brekerlijn (MRL), niet de molens.**
   De getallen kloppen; alleen het label in §4 was mis.

Ook bevestigd door het werkboek: een gedeelde operator bemenst het LANGST
draaiende lid, niet de som (rij 170/181 nemen het MAXIMUM van breker en zeef).
Dat was in §6.4 een openstaande vraag en is nu onderbouwd.

Niet geseed omdat de app het al doet — dat zou dubbel tellen: de controlekamer
(4,181 FTE, identiek aan wat ZZZZZ_CONTROLROOM oplevert), de truckbelading (zit
in ZZZZ_TRUCK01/02) en "crusher + sieve" (ZZ_GROUP01 is een molengroep en
aggregeert al met MAX). Uit gezet omdat de volumebron in de app nog niet
vaststaat: truckLOSSING en de feed door Janssen — met de klantnorm erbij en één
vinkje van actief.

Nog niet gedaan: browsertests voor het nieuwe tabblad en de
NF-01-performancemeting vastleggen.
