# HUMAN VERIFICATION - TEST K

**Aanvulling op Tests A-I**
QA Sign-off Sheet | Vul in na voltooiing van elke stap

---

## Instructies

1. Test K is een solo test en richt zich specifiek op **MoM**.
2. Gebruik dezelfde golden fixture als Tests H en I, met planningmaand `2025-12`.
3. Markeer elk checkpoint met PASS of FAIL en voeg notities/screenshots toe.
4. Maak screenshots van de MoM-tab, de MoM-detailtabel, de scatterplot en de Excel-export.
5. Stop bij een foutmelding of lege MoM-output waar data verwacht wordt; noteer de exacte stap.

---

## PASS-CRITERIA

- MoM-tab laadt zonder JavaScript- of backendfouten.
- MoM toont perioden, KPI's, top movers, scatterplot en detailtabel.
- Sorteren en filteren in de MoM-detailtabel werken en veranderen de zichtbare rijen correct.
- De MoM-cijfers in de UI komen overeen met de onderliggende inventory-waarden.
- Aanpassingen in de Planning sheet worden doorgerekend naar downstream planning, inventory en MoM.
- Excel-export bevat een bruikbare `MoM Comparison` sheet wanneer een previous-cycle snapshot beschikbaar is.
- MoM blijft beschikbaar en correct na een nieuwe Calculate-run.

---

## TEST K - MoM verificatie, UI-controle en export

**Tester:** Solo
**Geschatte tijdsduur:** 35 min
**Tabbladen nodig:** Dashboard, Planning, Inventory, MoM, Export-functie

> **Doel:** Verifieren dat de Month-over-Month analyse zichtbaar, inhoudelijk correct en exporteerbaar is. Deze test kijkt expliciet naar de MoM-tab in de applicatie en naar de MoM-output in Excel.

| Stap | Tabblad | Actie | Verify Checkpoints | Status | Notities | Screenshot |
|------|---------|-------|--------------------|--------|----------|------------|
| 1 | - | Start de applicatie. Upload de golden fixture en draai Calculate met planningmaand `2025-12`. | Sessie geladen; Dashboard toont data; geen error toast; console is schoon | | | |
| 2 | MoM | Open de MoM-tab. | MoM-tab is zichtbaar; banner verdwijnt of toont een zinvolle status; geen lege of kapotte layout | | | |
| 3 | MoM | Controleer de MoM KPI-blokken. | Materials count > 0; Up/Down counts zichtbaar; Average delta toont een percentage; geen `NaN`, `undefined` of `--` waar data hoort te staan | | | |
| 4 | MoM | Controleer de scatterplot. | Punten zijn zichtbaar; assen tonen from/to-perioden; kleuren/markers zijn leesbaar; geen lege canvas | | | |
| 5 | MoM | Controleer de Top Movers lijst. | Lijst bevat materialen; grootste absolute delta's staan bovenaan; materiaalnamen/nummers zijn leesbaar | | | |
| 6 | MoM | Controleer de detailtabel. | Tabel bevat materiaalnummer, materiaalnaam, from/to-perioden, delta en delta%; eerste rijen hebben numerieke waarden | | | |
| 7 | MoM | Sorteer de detailtabel op delta% oplopend en daarna aflopend. | Volgorde verandert; hoogste en laagste movers wisselen logisch; geen rijen verdwijnen onterecht | | | |
| 8 | MoM | Zoek/filter op een materiaalnummer dat zichtbaar is in de tabel. | Alleen matching rijen blijven zichtbaar; wissen van de zoekterm herstelt alle rijen | | | |
| 9 | Inventory | Kies een materiaal uit de MoM-detailtabel. Noteer de inventory-waarden van twee opeenvolgende perioden. | Genoteerde perioden bestaan in Inventory; waarden zijn numeriek | | | |
| 10 | MoM | Vergelijk hetzelfde materiaal in MoM. | `from` waarde = Inventory vorige periode; `to` waarde = Inventory huidige periode; delta = `to - from`; delta% klopt binnen afronding | | | |
| 11 | MoM | Wijzig `Months to compare` naar 1 en refresh MoM. | MoM toont 1 transitie; perioden en tabel passen zich aan; geen oude rijen uit vorige instelling blijven hangen | | | |
| 12 | MoM | Wijzig `Months to compare` naar 6 en refresh MoM. | Meerdere transities zichtbaar; scatter en top movers vernieuwen; material count blijft consistent | | | |
| 13 | Planning | Doe een duidelijke aanpassing in de Planning sheet, bijvoorbeeld een L1 demand edit voor een zichtbaar materiaal in de eerste forecastperiode. Noteer de originele en nieuwe waarde. | Planning accepteert edit; aangepaste cel toont de nieuwe waarde; edit-indicator/pending edit is zichtbaar; geen foutmelding | | | |
| 14 | Planning + Inventory | Controleer dat de aanpassing wordt doorgerekend. Bekijk voor hetzelfde materiaal de downstream planningregels en Inventory. | Afhankelijke planningwaarden veranderen logisch; inventory verandert in de juiste richting; er blijven geen oude/stale waarden zichtbaar | | | |
| 15 | MoM | Open of refresh MoM opnieuw. | Het geedite materiaal verandert in de MoM-output; from/to/delta worden opnieuw berekend; delta richting klopt met de inventory-impact | | | |
| 16 | - | Draai Calculate opnieuw zodat een previous-cycle snapshot beschikbaar is voor export. | Calculate voltooit; sessie blijft actief; geen snapshot-warning in de UI of serverlog | | | |
| 17 | Export | Klik Export en open de gedownloade Excel. | Export start zonder fout; bestand opent; standaard planning sheets zijn aanwezig | | | |
| 18 | Excel | Controleer dat de Planning sheet in Excel de aangepaste waarde en doorgerekende downstream waarden bevat. | Geedite cel matcht de UI; afhankelijke planning/inventory waarden matchen de UI; geen NaN of lege cellen waar data hoort te staan | | | |
| 19 | Excel | Zoek de sheet `MoM Comparison`. | Sheet bestaat wanneer previous-cycle data beschikbaar is; kolommen bevatten materiaal, perioden, delta en delta%; sheet is niet leeg | | | |
| 20 | Excel | Controleer de MoM scatter/chart output in de export indien aanwezig. | Scatter/chart is zichtbaar of de scatter-data staat in de workbook; geen kapotte afbeelding of lege sheet | | | |
| 21 | MoM + Excel | Vergelijk het geedite materiaal uit de UI met dezelfde rij in `MoM Comparison`. | Materiaalnummer matcht; from/to/delta/delta% komen overeen binnen afronding; export gebruikt de doorgerekende waarden na de Planning sheet aanpassing | | | |
| 22 | Planning | Reset de edit uit stap 13. Refresh MoM. | Edit-impact verdwijnt; MoM keert terug naar baselineverschillen; geen stale waarden zichtbaar | | | |

**Tester:** __________________ **Datum:** __________________ **Eindresultaat:** PASS / FAIL

---

## Evidence checklist

- Screenshot MoM-tab met KPI's.
- Screenshot MoM scatterplot.
- Screenshot MoM-detailtabel na sorteren.
- Screenshot MoM-detailtabel na filteren.
- Screenshot van de aangepaste Planning sheet cel en de doorgerekende downstream rij(en).
- Excel-export met zichtbare `MoM Comparison` sheet.
- Notitie van minimaal een handmatig gecontroleerde delta: `from`, `to`, `delta`, `delta%`.

---

*Aangemaakt als aanvulling op HUMAN_VERIFICATION_TESTS_H_I - Tests H & I. Versie 1.0, 2026-05-13.*
