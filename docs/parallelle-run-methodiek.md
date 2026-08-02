# Parallelle-run-methodiek — app-rekenkern vs klant-Excel

Hoe de validatie de app naast het klant-Excel-model bewijst, welke edits
1-op-1 spiegelbaar zijn, en de volledige dekkingsmatrix per edit-test.

## Aanpak

Bronbestand: `test 1705 sequentieel alle functies.xlsm`. De Planning sheet en de
Values_Planning sheet daarin zijn **formule-gedreven** (o.a. `SOMMEN.ALS`,
`=IFERROR(tarief × Planning!volume,0)`). Dat maakt twee dingen mogelijk:

1. **Baseline-parallel:** de Excel-waarden worden via Excel-COM uitgelezen en
   cel-voor-cel vergeleken met de live app-API (`/api/results`,
   `/api/value_results`). Zelfde bronbestand → twee onafhankelijke engines → Δ.
2. **Gespiegelde edit (mirror):** dezelfde edit wordt in ZOWEL de app als de
   klant-Excel doorgevoerd (Excel: inputcel wijzigen + `CalculateFull`), en de
   productabel én de financiële consolidatie worden in beide vergeleken.

Bewijs per check = app-UI-screenshot + **echte schermafdruk van het Excel-
programma** (via `PrintWindow`, met formulebalk zichtbaar) + Δ-tabel. Δ=0 =
onbetwistbaar gelijk.

> **Uitlijning:** de app-sessie draait met planning-maand 2026-07, de Excel met
> 2026-05 (2 maanden verschoven). Uitlijnen op planningsperiode: app-periode *i*
> ↔ Excel-kolom 12+*i*. De berekende reeks is identiek.

## Mirrorbaarheid per edit-type

| Edit-type | Mirrorbaar? | Mechanisme |
|---|---|---|
| Volume (L01 forecast, L03, L05 target, L06 productie) | **Ja** | Planning-cel wijzigen → cascade (L03/L06/waarde/consolidatie) herrekent via formules |
| Prijs (verkoopprijs) | **Ja** | Values_Planning "01"-tarief (kol I) × factor → omzet/TURNOVER |
| Grondstofkost | **Ja** | Values_Planning "03"-tarief (kol I) × factor → RAW |
| L06 purchase receipt (ingekocht materiaal) | **Nee (onzuiver)** | App herrekent inkoopbehoefte anders dan een directe Excel-celoverschrijving |
| Machine (OEE, beschikbaarheid, shift) | **Nee (Δ≠0)** | Een macro-rerun herrekent de machine-/FTE-laag wél, maar de app-logica wijkt bewust af van de ruwe VBA (zie FTE-bevinding) → geen Δ=0 |
| Valuatieparameters | **Nee** | Aparte Excel-sheet, niet formule-gekoppeld aan de consolidatie |
| Product toevoegen | **Nee** | Nieuw product bestaat niet in de Excel |

## Dekkingsmatrix — edit-tests

**Gespiegelde mirror (12, Δ=0):**
A5 (prijs ×2), A12 (grondstofkost ×4), C1 (forecast), C3 (cascade naar kind-
component), C4 (combi L01+L06), C5 (bulk 3 maanden), C10 (L05 multi-maand),
C11 (L01), E8 (L01), E12 (L01), F16 (L01 onder groep), H2 (L01 → export).

**Eerlijke toelichting (niet 1-op-1 mirrorbaar):**
- Machine: A9, G1, G2, G4, G5, G7, G9, G11, G12, G13, G14 (Excel-machinelaag statisch).
- A11 (valuatieparameter), A10 (veiligheidsvoorraad → cascade bewezen via C10),
  C6 (startvoorraad → cascade bewezen via I9), C12 (purchase receipt).

**Andere edit-achtige checks** (rename/undo/redo/reset/verwijderen/comment/config/
product-add: A2/A4/A6/A8/B3/B8/B9/B10/C2/C7/C8/C9/D*/F13-F20/H3/H9) zijn geen
"consolidatie + productabel"-cijferedits; die hebben hun eigen bewijs. A8
(deactiveren) heeft een aparte Excel-parallel.

## Bevindingen uit de parallelle run

Twee component-verschillen die elkaar bijna opheffen (**EBIT +0,8%**) — in beide
gevallen is de **app correct**; zie `bevinding-parallelle-run-grondstofkost.md`:
1. **RAW MATERIAL COST +1,07M/jaar** — twee Excel-fouten: PAP-formulebug
   `(1-2)` i.p.v. `(1-0,2)` (600003822) en een leeg tarief (150000483).
2. **DIRECT FTE COST −1,11M/jaar** — definitieverschil: app scoopt de directe
   FTE-kost op productie-FTE; Excel uniform op alle FTE-groepen.

De 2 Excel-bugs corrigeren in het klant-Excel; de FTE-definitie met de klant
bevestigen. De app-cijfers zelf zijn correct.

## Reproduceren

Scripts (scratchpad): `parallel.py` (baseline-panelen), `run_volume_mirrors.py` /
`run_extra_mirrors.py` / `run_financial_mirrors.py` (mirrors), `excel_shots.py`
(echte Excel-screenshots), `finding_card.py` (bevindingskaart), `round2_verify.py`
(numerieke herverificatie). Vereist: draaiende app (localhost:5000), Excel +
pywin32, het bronbestand op het gedocumenteerde pad.
