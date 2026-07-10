# HUMAN VERIFICATION — TESTS H & I

**Aanvulling op Tests A–G**
QA Sign-off Sheet | Vul in na voltooiing van elke stap

---

## Instructies

1. Tests H en I zijn **solo** (één tester, sequentieel).
2. Test H gebruikt één sessie en richt zich op de **nieuwe editable lines** (L4 starting stock + L7/L9/L11/L12) inclusief cascade, reset en restart.
3. Test I richt zich op **chart-rendering en export-integriteit** na de matplotlib PNG-overgang en de nieuwe data-labels / starting-stock visualisatie.
4. Markeer elk checkpoint ☑ PASS of ✗ FAIL en voeg opmerkingen/screenshots toe.
5. Beide tests veronderstellen een fixture met L4-materialen én een machinegroep met meerdere machines (bv. `SOP_GOLDEN_FIXTURE.xlsm`).

---

## PASS-CRITERIA (aanvullend op de algemene criteria op het COVER-tabblad)

- ✔ Edits op L4/L7/L9/L11/L12 cascaderen volgens de matrix in Test H stap 20
- ✔ Na reset, restart en sessie-wissel komen de pending edits exact terug op de juiste sessie
- ✔ Charts in de UI tonen dezelfde getallen als de bijbehorende tabellen, zonder NaN of negatieve afwijkingen
- ✔ Geëxporteerde Excel bevat ingebedde PNG-grafieken (matplotlib) en de cijfers matchen de UI op het moment van export

---

## TEST H — Editable lines: cascade, reset, restart en isolatie

**Tester:** Solo
**Geschatte tijdsduur:** 45 min
**Tabbladen nodig:** Planning, Machines, Values Planning, Dashboard

> **Doel:** Verifiëren dat de vijf nieuwe editable lijnen (L4 starting stock, L7 capacity utilization, L9 available capacity, L11 shift availability, L12 FTE requirements) correct cascaderen, persisteren over restart, niet bleed naar andere sessies, en exact replay-baar zijn vanuit `sessions_store.json`.

| Stap | Tabblad | Actie | Verify Checkpoints | Status | Notities | Screenshot |
|------|---------|-------|--------------------|--------|----------|------------|
| 1 | — | Start de applicatie. Maak **Sessie H1** aan, upload de fixture, draai Calculate. Noteer de baselinewaarden voor L4 (`600003806` starting stock + `2025-12` inventory), L7/L9/L10/L11/L12 voor `ZZZ_PACKGROUP01` / `PBA11`. | ☐ Sessie geladen ☐ baseline genoteerd ☐ geen errors in console | | | |
| 2 | Planning | Edit L4: zet starting stock van `600003806` op **130.0** (was 30.0). | ☐ L4 starting stock = 130.0 ☐ L4 inventory `2025-12` stijgt met +100 ☐ L7/L10/L12 ongewijzigd | | | |
| 3 | Planning | Edit L7: zet `ZZZ_PACKGROUP01` capacity utilization `2025-12` op **700.0** (was 598.62). | ☐ L7 = 700.0 ☐ L10 PBA11 stijgt naar ~28.14% ☐ L12 stijgt naar ~5.63 ☐ L9 ongewijzigd | | | |
| 4 | Planning | Edit L9: zet `PBA11 / Z_MACH01` available capacity `2025-12` op **0.75** (was 1.0). | ☐ L9 = 0.75 ☐ L10 PBA11 stijgt naar ~37.52% ☐ L12 **ongewijzigd** (5.63) | | | |
| 5 | Planning | Edit L11: zet `ZZZ_PACKGROUP01` shift availability `2025-12` op **400.0** (was 520.0). | ☐ L11 = 400.0 ☐ L10 PBA11 stijgt naar ~48.78% ☐ L12 **ongewijzigd** (5.63) | | | |
| 6 | Planning | Edit L12: zet `ZZZ_PACKGROUP01` FTE requirements `2025-12` op **6.5** (was 5.63). | ☐ L12 = 6.5 ☐ L7/L9/L10/L11 ongewijzigd ☐ Values Planning direct FTE cost stijgt | | | |
| 7 | Machines | Open Machines tab, controleer heatmap en grafieken voor `PBA11`. | ☐ Utilization-curve `PBA11` toont piek in `2025-12` ☐ FTE-grafiek `ZZZ_PACKGROUP01` toont 6.5 in `2025-12` ☐ geen lege canvas | | | |
| 8 | Values Planning | Open Values Planning, controleer L12 direct FTE cost `2025-12`. | ☐ Direct FTE cost ≈ 41,962.61 ☐ Consolidation FTE cost ≈ 202,790.61 ☐ andere periodes ongewijzigd | | | |
| 9 | Dashboard | Ga naar Dashboard. | ☐ FTE KPI gestegen ☐ utilisation KPI gestegen ☐ geen NaN of `--` ☐ grafieken tonen actuele waarden | | | |
| 10 | Planning | Klik **Reset** in Sessie H1. | ☐ alle vijf edits weg ☐ baseline-waarden uit stap 1 zijn terug ☐ pending edits panel leeg | | | |
| 11 | Planning | Voer dezelfde vijf edits opnieuw in (stap 2–6, in dezelfde volgorde). | ☐ eindwaarden identiek aan stap 6 ☐ replay-volgorde maakt geen verschil | | | |
| 12 | — | Maak **Sessie H2** aan via "Opslaan als nieuwe instantie" vanuit H1. | ☐ H2 geladen ☐ alle vijf edits zichtbaar in H2 ☐ H2 toont identieke L4/L7/L9/L11/L12 als H1 | | | |
| 13 | Planning (H2) | In H2: zet L12 `ZZZ_PACKGROUP01` `2025-12` op **8.0**. Wissel naar H1. | ☐ H1 toont L12 = **6.5** (geen bleed uit H2) ☐ H1 Values cost ≈ 41,962.61 (niet H2-waarde) | | | |
| 14 | — | **Stop de server** (Ctrl+C). Herstart met `python main.py`. Open de browser. | ☐ Beide sessies (H1 + H2) zichtbaar ☐ geen exception bij start ☐ `sessions_store.json` aanwezig in app data dir | | | |
| 15 | Planning (H1) | Wissel naar H1 na restart. Klik Calculate indien nodig. | ☐ L4 starting stock = 130.0 ☐ L7 = 700.0 ☐ L9 = 0.75 ☐ L11 = 400.0 ☐ L12 = 6.5 ☐ pending edits panel toont alle vijf entries | | | |
| 16 | Planning (H2) | Wissel naar H2 na restart. | ☐ L12 = 8.0 (H2-specifiek) ☐ overige vier edits identiek aan H1 ☐ Values Planning H2 ≠ H1 | | | |
| 17 | Planning (H1) | In H1: edit L1 demand voor `600003806` `2025-12` met **+200**. Verifieer dat L4 én L7/L8 reageren. | ☐ L1 = +200 ☐ L4 inventory daalt ☐ L8 req_hours stijgt ☐ L10/L12 cascaderen mee | | | |
| 18 | Planning (H1) | Klik **Undo** op de L1 edit (volume undo). | ☐ L1 terug naar baseline ☐ L4 inventory teruggesprongen (130 + originele waarde) ☐ overige vier edits **blijven actief** | | | |
| 19 | Planning (H1) | Klik **Reset** in H1. Wissel naar H2. | ☐ H1 volledig leeg (geen pending edits) ☐ H2: L12 = 8.0 nog steeds aanwezig (reset is sessie-specifiek) | | | |
| 20 | — | Eindcontrole: vergelijk L10/L12 cascade-matrix. | ☐ L7 verandert → L10 én L12 reageren ☐ L9 verandert → alleen L10 reageert ☐ L11 verandert → alleen L10 reageert ☐ L12 leaf-edit → alleen Values Planning reageert ☐ L4 starting stock → alleen L4 inventory reageert | | | |

**Tester:** \_\_\_\_\_\_\_\_\_\_\_ **Datum:** \_\_\_\_\_\_\_\_\_\_\_ **Eindresultaat:** ☐ PASS ☐ FAIL

---

## TEST I — Charts en export-integriteit

**Tester:** Solo
**Geschatte tijdsduur:** 35 min
**Tabbladen nodig:** Dashboard, Inventory Quality, Machines, Values Planning, Export-functie

> **Doel:** Verifiëren dat (a) de inventory quality chart correct understock/overstock toont na de Math.abs/categorisatie fix, (b) de financial projection chart starting stock toont, (c) data-labels op de Actual stock-lijn correct zijn, en (d) de matplotlib PNG-embed in de Excel-export overeenkomt met de UI.

| Stap | Tabblad | Actie | Verify Checkpoints | Status | Notities | Screenshot |
|------|---------|-------|--------------------|--------|----------|------------|
| 1 | — | Start de applicatie, gebruik dezelfde fixture als Test H. Draai Calculate. | ☐ Sessie geladen ☐ Dashboard rendert ☐ geen console-errors | | | |
| 2 | Dashboard | Open de **Inventory Quality** chart. | ☐ Bars getekend ☐ understock-bars (negatief) staan **onder** de nullijn (geen Math.abs flip) ☐ overstock-bars **boven** de nullijn ☐ legenda toont beide categorieën | | | |
| 3 | Dashboard | Hover over een understock-maand. | ☐ Tooltip toont negatieve waarde of "shortage" ☐ kleur = understock-kleur (rood/oranje) ☐ overeenkomstig met cijfer in tabel onder de chart | | | |
| 4 | Dashboard | Hover over een overstock-maand. | ☐ Tooltip toont positieve waarde ☐ kleur = overstock-kleur (groen/blauw) ☐ getal matcht tabel | | | |
| 5 | Dashboard | Controleer de **Actual stock**-lijn op de inventory chart. | ☐ Data labels boven elke datapunt zichtbaar ☐ labels tonen afgeronde voorraadwaarde ☐ geen overlap met as-labels ☐ starting stock (eerste punt) is correct gecategoriseerd | | | |
| 6 | Dashboard | Open de **Projected Financial** chart. | ☐ Starting stock-balk/-lijn aanwezig vóór de eerste planningsperiode ☐ starting stock waarde matcht L4 baseline ☐ revenue-curve start na starting stock | | | |
| 7 | Planning | Edit L4 `600003806` starting stock naar **300.0**. Ga terug naar Dashboard. | ☐ Inventory chart starting-stock punt verhoogd ☐ Financial chart starting stock balk verhoogd ☐ Actual stock data label `2025-12` toont nieuwe waarde (was +270 t.o.v. baseline) | | | |
| 8 | Dashboard | Cache-check: druk **Ctrl+F5** (hard reload) op Dashboard. | ☐ Charts opnieuw getekend met L4 = 300 ☐ geen oude (gecachte) curve zichtbaar ☐ KPI's actueel | | | |
| 9 | Inventory Quality | Open de Inventory Quality tab volledig. | ☐ Alle materialen tonen consistente understock/overstock-classificatie ☐ totaal-rij overeen met som van bars op Dashboard | | | |
| 10 | Planning | Edit L1 demand `600003806` `2025-12` met **+5000** (forceer understock). | ☐ Inventory chart toont negatieve bar in `2025-12` ☐ data label op Actual stock-lijn `2025-12` is negatief of 0 ☐ Inventory Quality tab markeert deze maand als shortage | | | |
| 11 | Machines | Open Machines tab, controleer utilization heatmap. | ☐ Heatmap rendert ☐ kleurschaal consistent ☐ tooltips tonen percentages ☐ geen lege cellen waar data is | | | |
| 12 | Machines | Controleer FTE-grafiek `ZZZ_PACKGROUP01`. | ☐ Lijn rendert voor alle periodes ☐ eindwaarde matcht L12 in Planning tab | | | |
| 13 | — | Klik **Export** (Excel-export-knop). | ☐ Download start ☐ bestandsnaam bevat planningmaand ☐ geen foutmelding | | | |
| 14 | Excel | Open het bestand. Zoek het tabblad met de inventory quality grafiek. | ☐ Grafiek aanwezig als **ingebedde PNG** (geen native Excel-chart) ☐ understock/overstock visueel identiek aan UI ☐ geen openpyxl chart-fragment of `chart1.xml` foutmelding | | | |
| 15 | Excel | Vergelijk de PNG met een UI-screenshot van dezelfde chart. | ☐ Pixels visueel gelijk (zelfde bars, kleuren, labels) ☐ assen-labels leesbaar ☐ legenda compleet | | | |
| 16 | Excel | Zoek het tabblad met de financial projection. | ☐ Starting stock-element aanwezig in PNG ☐ revenue-projectie correct ☐ titel/bijschrift matcht UI | | | |
| 17 | Excel | Controleer de cijfertabbladen (L01, L04, L07, L12). | ☐ L04 starting stock = 300 voor `600003806` ☐ L12 `ZZZ_PACKGROUP01` `2025-12` matcht UI op het moment van export ☐ geen NaN/lege cellen waar UI cijfers toonde | | | |
| 18 | Excel | Vergelijk Actual stock data labels in PNG met L04-tabblad. | ☐ Data labels in PNG = waarden in L04-rij voor `600003806` ☐ alle periodes aanwezig | | | |
| 19 | Planning | Reset alle edits in de UI. Exporteer opnieuw. | ☐ Tweede export start zonder error ☐ inventory chart PNG verschilt van eerste export (terug naar baseline) ☐ L4 starting stock in tweede export = 30 (baseline) | | | |
| 20 | — | Eindcontrole: open beide exports naast elkaar. | ☐ Verschillen zitten alleen in de bewerkte rijen/charts ☐ niet-bewerkte rijen byte-identiek ☐ PNG-grafieken in beide exports renderen zonder kapotte plaatjes | | | |

**Tester:** \_\_\_\_\_\_\_\_\_\_\_ **Datum:** \_\_\_\_\_\_\_\_\_\_\_ **Eindresultaat:** ☐ PASS ☐ FAIL

---

*Aangemaakt als aanvulling op HUMAN_VERIFICATION_TESTS_F_G — Tests F & G. Versie 1.0, 2026-05-10.*
