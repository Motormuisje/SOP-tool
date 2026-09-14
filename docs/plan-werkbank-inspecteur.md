# Werkbank-inspecteur — één paneel naast de tabel

**Datum:** 2026-09-14 · **Scope:** tabblad "Capaciteit & FTE", hoofdrepo
(NLX1). Niet voor de site-uitgaven WSK/ANK (die kennen de werkbank niet).

Dit stuk legt vast wat er in september 2026 aan de werkbank is veranderd en
waarom. Het bouwt voort op [plan-werkbank-presentatie.md](plan-werkbank-presentatie.md)
(doctrine "alles invulbaar, import is populatie") en vervangt de daar
beschreven *ingangen*: de invulpaden liepen via sprongen naar het Config-tab,
en dat voelde slordig. De doctrine zelf staat overeind.

## 1. Wat er mis was

- Elk getal had een invulpad, maar bijna elk pad was `showTab('config')` +
  het juiste masterdata-grid, en daarna terug. De planner verloor zijn plek.
- Drie wat-als-oppervlakken tegelijk (balk boven de tabel, zwevende lade
  rechtsonder, chips) zonder duidelijke hiërarchie.
- De kolom "Doorzet & benchmark" toonde MES en PEER als referentie, maar
  nooit het getal waarmee de planning rekent. In de praktijk waren die
  kolommen leeg en werden ze door niemand gevoed.
- De FTE-eigen `throughput_overrides` waren een tweede waarheid: de
  FTE-motor rekende ermee, de capaciteitsmotor niet.

## 2. Het ontwerp

**Eén paneel, gedockt aan de tabel.** Klik een regel en rechts naast de
tabel opent een paneel met alles van díe regel. De tabel wordt compact
(Bron en Beschikbaar tijdelijk verborgen) zodat beide leesbaar blijven. Het
paneel staat `position: fixed`, volgt de tabelstrook bij scrollen, blijft
onder de bovenbalk en verdwijnt zodra de tabel uit beeld is. Esc sluit.

Drie invoersoorten, elk met precies één eigenaar:

| Wat | Waar het leeft | Route | Doorwerking |
|---|---|---|---|
| Bemensingsnorm | sessie-wat-als | `POST /api/fte/norm_overrides` | werkbank direct; opslaan in masterdata of meenemen in een scenario |
| Loontarief per functiegroep | masterdata | `PATCH /api/master_data/labor_rates` + `POST /api/fte/refresh` | alle instanties, werkbank ververst meteen |
| Effectieve doorzet per machine | sessie-wat-als, via het Machines-mechanisme | `POST /api/machines/update` (veld `oee`) | de hele planning: Line 07/09/10/12, bezetting, werkbank |

**Doorzet.** Het paneel toont de effectieve doorzet zoals de Machines-tab die
berekent (output / benodigde uren, gemiddeld over het gekozen bereik), de OEE
als "rekenfactor", de theoretische doorzet en de SAP-routingnorm per product
als leeswaarde. Aanpassen gebruikt exact de omrekening van de Machines-tab:
`OEE_nieuw = OEE × doel / huidig`, begrensd op 150 %. "Terug naar origineel"
zet de OEE terug naar de reset-baseline, dezelfde betekenis als op de
Machines-tab. Bewuste keuze: één knop per machine, geen doorzet per product.
Wil iemand per product afwijken, dan hoort dat in de planning zelf (fase 2,
§5), niet in een werkbank-eigen tabel.

**MES en PEER** staan niet meer in de werkbank. De dataset
`benchmark_throughput` blijft bestaan als slapende masterdata (Config-grid),
zonder importfunctie. Hetzelfde geldt voor `throughput_overrides`: de werkbank
toont en schrijft ze niet meer; of ze in de capaciteitsmotor gaan meetellen of
verdwijnen is een apart besluit.

**Kanttekeningen in de KPI-tegels** vervangen de chipstrip. Onder "FTE
benodigd" staat "n regels op aanname 1,0", onder "Loonkosten" "n regels zonder
tarief"; beide openen het paneel op de eerste betreffende regel. Onder "Bij
bezettingsdoel" staat "doel x %", dat het masterdata-formulier `fte` in het
paneel opent (de bestaande editor wordt fysiek in het paneel gezet en keert
bij sluiten terug naar Config). De strip zelf is weg: de tellingen waren
dubbel met de rij-chips en de doctrine-chip was een etiket.

**Wat-als.** De balk boven de tabel is weg. Met het paneel open staat de
wat-als-stand in de voet van het paneel; met het paneel dicht blijft de
zwevende lade rechtsonder. Nooit allebei.

## 3. Combineren vanuit de werkbank

De knop "Combineren" (links van de bereikknoppen) zet de tabel in kiesmodus:
alle groepen klappen open, elke machinerij krijgt een vinkje, machines die al
in een actieve combinatie zitten zijn grijs. Het paneel wordt "Nieuwe
combinatie" en vult zich mee: naam, operators samen, doorzetverlies (optioneel
per machine), loontarief via functiegroep (bestaand of nieuw), toelichting en
een voorvertoning. "Aanmaken en aanzetten" schrijft de definitie naar de
masterdata (`PATCH machine_combinations`), laat de motor de datasets opnieuw
inlezen (`/api/fte/refresh`) en zet de combinatie in deze sessie aan
(`POST /api/fte/combinations`). Een combinatierij in de tabel opent haar eigen
paneel: aan/uit, leden, parameters, opslaan definitie, verwijderen, tarief.

**Semantiek van "operators samen".** Het is de ploeggrootte van de pool per
draaiuur en vervangt de normen van de leden volledig; de motor rekent
`operators × uren van het langst draaiende lid`. Zinvol tussen 1 (één gedeelde
operator) en de som van de losse normen; daarboven is combineren duurder dan
los bemannen. Daarom: beginwaarde 1, naast het veld de bandbreedte
("los: 1 + 1 = 2 · gedeeld: 1") en amber met "meer dan los bemannen" boven de
som. De voorvertoning rekent `MAX(uren_lid / factor_lid) × operators /
(FTE-uren per jaar / 12)`; het echte cijfer volgt zodra de combinatie aanstaat.

**Strafkosten** zijn geen apart veld: een toeslag voor de multi-inzetbare
operator is een eigen functiegroep met een hoger tarief. **Doorzetverlies** is
de bestaande `throughput_factor`; die telt in de uren en de FTE van de
werkbank, nog niet in de planning (fase 2).

Weergave: een combinatierij toont "—" bij benutting (een operatorpool heeft
geen machinebelasting); een groep waarvan álle machines gecombineerd zijn
toont "0 via combinatie" bij FTE, met de naam van de combinatie in de tooltip.

## 4. Wat er is verdwenen

- Aannamenstrip (`#fteAssumptions`, `_renderFteAssumptions`).
- Wat-als-balk boven de tabel (`#fteDirtyBar`).
- Samenvattingskaart "n combinaties actief — Naar Machine-inzet".
- `openFteThroughputGrid` (✎) en `adoptFteBenchmark` (→ MES overnemen).
- Kolom "Doorzet & benchmark" → "Doorzet (t/u)" met de effectieve doorzet.

Het tabblad Machine-inzet (omstellingen, combinatielijst, vergelijking van
varianten) is ongewijzigd.

## 5. Fase 2 — enginewerk, niet stiekem

1. `throughput_factor` van een actieve combinatie laten doorwerken in de
   capaciteitsmotor (Line 07-uren), zodat planning en werkbank hetzelfde getal
   zien. Zelfde verificatieronde als in plan-werkbank-presentatie §4:
   additiviteitsbewijs (geen combinaties = byte-identiek), golden baseline
   opnieuw met bewijs, browsertests op de cascade.
2. Besluit over `throughput_overrides` (machine × product): meenemen in de
   capaciteitsmotor of schrappen. Zolang dat open is rekent de FTE-motor er
   nog mee als er rijen in de masterdata staan; de werkbank toont ze niet.
3. Eventueel een vast bedrag als strafkost per combinatie (nieuw veld +
   engine); pas als een klant daarom vraagt.

## 6. Tests

`tests/browser/test_fte_inspector.py`: paneel openen/sluiten en tabel
compact/volledig; effectieve doorzet in rij en paneel gelijk aan
`/api/machines`; doorzet toepassen schaalt de OEE en "terug naar origineel"
herstelt uren en OEE; tarief opslaan vanuit het paneel ververst de werkbank;
combineren: kiesmodus, bandbreedte-hint, aanmaken en aanzetten, combinatierij
met "—", uitzetten, verwijderen; installatieparameters openen in het paneel
en de editor keert terug naar Config. De bestaande `test_fte_overzicht.py` en
`test_fte_workbench.py` zijn aangepast aan de verdwenen elementen.
