# Plan F2-CF — Capaciteits- en FTE-optimalisatie (werkbank)

Status: concept ter review · Datum: 2026-08-03 · Bron-requirements: charter §7.4
(F2-CF-01..05) · Klantinput: `OEE model MTO APEX voorbeeld.xlsx` (Maastricht) ·
Uitvraag: `Uitvraag_Informatiebehoefte_FTE_Simulatie_{WSK,MST_Ankersmit}_v2.docx`

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
3. **Antwoord op de uitvraag**: voor Maastricht dekt dit bestand het merendeel
   van de OPS/HR-sjablonen uit de uitvraag van 2026-07-28. De uitvraag blijft
   nodig voor: het WSK-equivalent (dit is een MST-bestand), loonkosten per
   functiegroep (FIN), en de expliciete machinecombinatie-regels (sjabloon 2).

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
productwizard waar relevant. Sitespecifiek (WSK- en MST-waarden verschillen).

1. **`fte_params`** (uitbreiding van bestaande `fte`-dataset):
   bezettingsgraad, ziekte-%, training-%, en de afleiding bruto→effectieve uren
   (nu alleen het eindgetal 1.492). De afleiding blijft optioneel: het eindgetal
   is leidend, de componenten zijn documentatie/afleidingshulp.
2. **`staffing_norms`**: per machinegroep (of machine): benodigde operators per
   draaiend uur (`# FTE Staffing` uit het model, WSK-coëfficiënten uit
   sjabloon 1), met ingangsdatum-loos versiebeheer via de storeversie.
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
- Golden-referentietest op het MST-model; WSK-variant zodra sjabloon 1/3 terug
  is; browsertests werkbank (bewerken → KPI-update → scenario-opslag →
  vergelijking); performancemeting NF-01 vastleggen.

## 5. Randvoorwaarden / volgorde

1. **Machine-overrides in scenario's persisteren** (bestaande gap) — nodig
   vóór Fase C/D; klein, apart uit te voeren.
2. Masterdata-datasets (§3) eerst: Fase A rekent er direct uit; UI-tabellen en
   werkboek-tab zijn bestaand stramien (goedkoop na de Config/FTE-stap).
3. Seed-script éénmalig vanuit het klantbestand voor MST; WSK-waarden uit de
   uitvraagsjablonen (of het WSK-equivalent van dit model, als dat bestaat —
   vraag uitstaand).

## 6. Openstaande beslissingen / vragen aan de klant

1. **Brontriage doorzet**: SAP-routing (huidige motor), MES-norm en
   PEER-capaciteit verschillen per machine×product (bv. PE06/Ank125: 35 vs 27
   t/u). Voorstel: SAP-routing blijft de rekenbron; MES-norm als benchmark in
   de werkbank; afwijking > X% krijgt een signaalkleur. Klant bevestigt de
   voorkeursbron per unit.
2. **WSK-equivalent** van dit model — bestaat dat, of vullen we sjabloon 1/3
   handmatig?
3. **Loonkosten per functiegroep** (FIN-uitvraag) — tot dan sitebreed tarief.
4. **Combinatieregels expliciet** (sjabloon 2): welke combinaties zijn
   toegestaan en wat is het doorzet-effect van een gedeelde operator?
5. FTE-norm WSK 1.442 vs model 1.492 u/jaar (bekende validatievraag).
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
