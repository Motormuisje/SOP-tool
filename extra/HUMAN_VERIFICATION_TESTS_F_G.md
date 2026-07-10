# HUMAN VERIFICATION — TESTS F & G

**Aanvulling op Tests A–E**
QA Sign-off Sheet | Vul in na voltooiing van elke stap

---

## Instructies

1. Tests F en G zijn **solo** (één tester, sequentieel).
2. Test F vereist twee aparte planning-sessies — maak ze aan vóór je begint.
3. Test G voer je uit in één sessie met een combinatie van edits, gevolgd door een export.
4. Markeer elk checkpoint ☑ PASS of ✗ FAIL en voeg opmerkingen/screenshots toe.

---

## PASS-CRITERIA (aanvullend op de algemene criteria op het COVER-tabblad)

- ✔ Wisselen tussen sessies toont nooit waarden van de andere sessie
- ✔ Na server-herstart zijn alle planning-edits exact herstelbaar
- ✔ Geëxporteerde Excel-waarden komen byte-voor-byte overeen met de UI-waarden op dat moment

---

## TEST F — Multi-sessie isolatie & state-herstel na server-herstart

**Tester:** Solo
**Geschat tijdsduur:** 30 min
**Tabbladen nodig:** Planning, Machines, Dashboard

| Stap | Tabblad | Actie | Verify Checkpoints | Status | Notities | Screenshot |
|------|---------|-------|--------------------|--------|----------|------------|
| 1 | — | Start de applicatie. Maak **Sessie 1** aan (upload MS_RECONC, voer Calculate uit). Noteer het sessie-ID. | ☐ Sessie 1 zichtbaar in de sessielijst | | | |
| 2 | Planning (Sessie 1) | Edit in Sessie 1: verhoog het productieplan van material **600004440** P1 met **+500**. | ☐ L06 herberekend in Sessie 1 | | | |
| 3 | Machines (Sessie 1) | Edit in Sessie 1: verlaag OEE van **PBA11** naar **55%**. | ☐ Utilization PBA11 gestegen in Sessie 1 | | | |
| 4 | — | Maak **Sessie 2** aan via opslaan als instantie. Wissel naar Sessie 2. | ☐ Sessie 2 geladen zonder foutmelding ☐ alle edits aanwezig | | | |
| 5 | Planning (Sessie 2) | Controleer in Sessie 2 de waarden voor material 600004440 P1. | ☐ L01/L06 tonen de **originele** waarden na reset van een aparte sessie ☐ Geen spill-over van aparte sessie | | | |
| 6 | export alle fotos en excels | Controleer de kwalliteit | ☐ OEE staat op de **aangepaste** waarde (niet 55% uit Sessie 1) ☐ geen nummerieke verschillen met excel financial consolidation | | | |
| 7 | Machines (Sessie 2) | Edit in Sessie 2: verlaag OEE van **PM06** naar **60%** (andere machine dan Sessie 1). | ☐ PM06 utilization gestegen in Sessie 2 | | | |
| 8 | — | Wissel terug naar **Sessie 1**. | ☐ Sessie 1 actief (header toont Sessie 1) | | | |
| 9 | Machines (Sessie 1) | Controleer PBA11 en PM06 in Sessie 1. | ☐ PBA11 OEE nog steeds **55%** (persisteert) ☐ PM06 OEE op de **originele** waarde (edit was in Sessie 2) | | | |
| 10 | Planning (Sessie 1) | Controleer de vraagprognose van 600004440 P1 in Sessie 1. | ☐ L01 toont nog steeds **+500** boven origineel ☐ L06 herberekend met gecombineerde edits (demand +500 én OEE 55%) | | | |
| 11 | — | **Stop de server** (Ctrl+C in de terminal). Herstart de server (`python main.py`). Open de applicatie in de browser. | ☐ Applicatie start zonder foutmelding ☐ Sessie 1 én Sessie 2 zijn zichtbaar in de sessielijst | | | |
| 12 | Planning (Sessie 1) | Wissel naar Sessie 1 na herstart. Klik Calculate indien nodig. | ☐ Vraagprognose 600004440 P1 toont nog steeds **+500** ☐ L06 correct herberekend | | | |
| 13 | Machines (Sessie 1) | Controleer PBA11 OEE in Sessie 1 na herstart. | ☐ PBA11 OEE is **55%** (hersteld uit sessions_store.json) ☐ Utilization overeenkomstig correct | | | |
| 14 | Machines (Sessie 2) | Wissel naar Sessie 2 na herstart. | ☐ PM06 OEE is **60%** (hersteld) ☐ PBA11 OEE is originele waarde (geen bleed van Sessie 1) | | | |
| 15 | Machines (Sessie 1) | Klik **Reset** in Sessie 1. Controleer Sessie 2. | ☐ Sessie 1: alle OEE/availability terug naar origineel ☐ Sessie 2: PM06 OEE **nog steeds 60%** (reset is sessie-specifiek) | | | |

**Tester:** \_\_\_\_\_\_\_\_\_\_\_ **Datum:** \_\_\_\_\_\_\_\_\_\_\_ **Eindresultaat:** ☐ PASS ☐ FAIL

---

## TEST G — Value planning verificatie & export-integriteit

**Tester:** Solo
**Geschat tijdsduur:** 25 min
**Tabbladen nodig:** Planning, Dashboard, Export-functie

> **Doel:** Testen of waardelijnen (L07–L12: revenue, cost, ROCE) correct meeschalen met vraag- én prijswijzigingen, en of de geëxporteerde Excel exact overeenkomt met de UI-waarden op het moment van export. Dit is niet gedekt in Tests A–E (A/B testen alleen de isolatie van prijsedits op machines; C/D/E verifiëren L07–L12 niet inhoudelijk).

| Stap | Tabblad | Actie | Verify Checkpoints | Status | Notities | Screenshot |
|------|---------|-------|--------------------|--------|----------|------------|
| 1 | Planning | Noteer de **huidige** waarden (baseline): L01, L06, L07 (revenue) en L12 (ROCE of kostentotaal) voor material **600004440**, periodes P1–P3. | ☐ Baseline genoteerd | | | |
| 2 | Planning | Edit prijs (value aux) voor material 600004440: stel in op **2× de huidige waarde**. | ☐ Revenue-rij (L07) verdubbeld voor alle periodes ☐ L06 (productieplanning) ongewijzigd ☐ L01 (vraag) ongewijzigd | | | |
| 3 | Planning | Verhoog de vraagprognose van hetzelfde material P2 met **+1000**. | ☐ L01 P2 verhoogd ☐ L06 P2 herberekend ☐ L07 P2 = nieuw volume × dubbele prijs (gecombineerd effect) | | | |
| 4 | Dashboard | Ga naar Dashboard. | ☐ Totale revenue KPI verhoogd (prijs × volume beide veranderd) ☐ Avg Utilisation KPI ongewijzigd (prijs heeft geen effect op capaciteit) ☐ ROCE-indicator (indien aanwezig) gereflecteerd | | | |
| 5 | Planning | Undo de vraagwijziging (Volume Undo). | ☐ L01 P2 terug naar origineel ☐ L07 P2 = origineel volume × dubbele prijs ☐ L06 P2 terug naar baseline | | | |
| 6 | Planning | Controleer L12 (FTE of kostentotaal) na de prijswijziging alleen. | ☐ L12 **ongewijzigd** (prijs beïnvloedt geen capaciteit/FTE) ☐ Machines tab: alle utilizations ongewijzigd | | | |
| 7 | — | **Exporteer** de planning (klik op de Export-knop, download de Excel). | ☐ Export-bestand wordt gedownload zonder foutmelding ☐ Bestandsnaam bevat planningmaand | | | |
| 8 | Excel | Open het geëxporteerde bestand. Ga naar het revenue/waarde-tabblad of de betreffende rijen. | ☐ L07 (revenue) voor 600004440 in de Excel = UI-waarden uit stap 2 ☐ L01 in Excel = originele baseline (Undo was uitgevoerd) ☐ L06 in Excel = baseline ☐ Geen lege cellen of NaN-waarden in de waardelijnen | | | |
| 9 | Excel | Controleer de kapaciteitsrijen in de export (L08–L11: req_hours, utilization, FTE). | ☐ L08 req_hours in Excel overeenkomstig met Machines tab in UI ☐ L12 FTE-totalen in Excel = Machines tab FTE-kolom ☐ Alle perioden aanwezig (geen ontbrekende kolommen) | | | |
| 10 | Planning | Maak nóg een prijswijziging: reset prijs terug naar origineel (of gebruik Undo). Exporteer opnieuw. | ☐ Tweede export: L07 terug naar originele waarden ☐ Twee exports naast elkaar: enige verschil is de revenue-rij (alle andere rijen identiek) ☐ UI en Excel in sync | | | |

**Tester:** \_\_\_\_\_\_\_\_\_\_\_ **Datum:** \_\_\_\_\_\_\_\_\_\_\_ **Eindresultaat:** ☐ PASS ☐ FAIL

---

*Aangemaakt als aanvulling op HUMAN_VERIFICATION_10DOF — Tests A t/m E. Versie 1.0, 2026-05-01.*
