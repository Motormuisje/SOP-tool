# Bevindingen — parallelle run: 2 component-verschillen (die elkaar bijna opheffen)

**Datum:** 2026-07-14 · **Bron-Excel:** `test 1705 sequentieel alle functies.xlsm`
· **Golden-parity-smoke (`python main.py --test`):** geslaagd.

## Samenvatting

De app-rekenkern is **parallel** naast het klant-Excel-model gedraaid op hetzelfde
bronbestand (formule-model, uitgelezen via Excel-COM; cel-voor-cel vergeleken met
de live app-API). **Omzet, machinekost, alle volumes, de voorraadketen en de FTE-
aantallen matchen byte-identiek.** De consolidatie legde **twee** component-
verschillen bloot die elkaar **grotendeels compenseren**:

| Consolidatie-regel | App (Σ12) | Klant-Excel (Σ12) | Δ /jaar |
|---|---|---|---|
| **RAW MATERIAL COST** | 20 047 771 | 18 978 818 | **+1 068 953** |
| **DIRECT FTE COST** | 961 498 | 2 069 076 | **−1 107 578** |
| Netto op **EBIT** | 4 760 334 | 4 721 710 | **+38 624 (+0,8%)** |

**De bottom line (EBIT/marge) sluit dus binnen ~0,8% aan.** De twee verschillen
zitten op componentniveau en verdienen bevestiging van de klant; ze zijn géén
reken- of datafout van de rekenkern (golden parity blijft byte-identiek).

## 1 — RAW MATERIAL COST (+1,07 M/jaar) — Excel-formulebug, app correct

Het volledige verschil komt van **twee** materialen; in beide gevallen is de
**app correct** en heeft de klant-Excel een fout:

- **600003822** — Dolomite DS19 PO (purchased-and-produced, ratio 0,2):
  **Excel-formulebug.** De waarderingsformule in Values_Planning is
  `=IFERROR(I241 * 'Planning sheet'!L825 * (1 - 2), 0)` — de PAP-ratio staat als
  **`(1 - 2)` = −1** i.p.v. **`(1 - 0,2)` = 0,8**. De productieratio 0,2 is als
  "2" ingevoerd, waardoor de grondstofwaarde negatief wordt (−35 203 p0). De app
  rekent correct `+vraag × kost × (1 − 0,2)` = +28 162 (p0). *(Bevestigd door de
  klant; de fractie wordt handmatig gecorrigeerd.)*
- **150000483** — CHALK: de kost **17,71 €/eenheid** staat in de Excel-mastersheet
  `Cost raw material` én in de app-masterdata, maar de Excel-**tariefcel** in de
  Values_Planning "03. Total demand"-rij is **leeg** → Excel waardeert op 0. De
  app past de kost wél toe (+29 240 p0). **App aantoonbaar juister**
  (waarderingsgat in het Excel-model).

## 2 — DIRECT FTE COST (−1,11 M/jaar)

De app past het directe FTE-tarief (6 455,79 €/maand, identiek aan de Excel-
`Valuation parameters`-sheet) toe op een **andere FTE-basis** dan de Excel:

- **Excel:** `DIRECT FTE COST = SUMIFS(alle "12. FTE requirements"-rijen × tarief)`
  — dus **alle 16 groepen**, inclusief `ZZZZ_TRUCK01/02`, `ZZZZZ_CONTROLROOM` en
  de `ZZZ_PACKGROUP`-groepen, allemaal tegen het directe tarief.
- **App:** past speciale truck-/control-room-logica toe (`TruckOperationsFormulas`,
  cf. ontwikkelhandleiding `product_type_raw`) en scoopt het directe FTE-tarief op de
  productie-FTE. Resultaat ≈ 46% van de Excel-basis.

Dit is een genuanceerd definitieverschil (de app verfijnt de VBA-behandeling van
trucks/control room). De **FTE-aantallen zelf matchen** (het verschil zit in
welke groepen het *directe* tarief krijgen).

## Interpretatie & advies

1. De **app is correct**; de twee kostenverschillen komen uit een Excel-fout en
   een definitieverschil, niet uit de rekenkern (golden parity byte-identiek;
   omzet, machinekost, volumes en voorraad matchen exact; EBIT binnen 0,8%).
2. **600003822 (PAP):** **Excel-formulebug** `(1 - 2)` i.p.v. `(1 - 0,2)` —
   corrigeren in het klant-Excel. De app is juist.
3. **150000483 (CHALK):** **leeg tarief** in de Excel-waardering (datagat) —
   nalopen in het klant-Excel. De app is juist.
4. **DIRECT FTE-basis:** **definitieverschil.** De app scoopt het directe
   FTE-tarief op de productie-FTE (met truck-/control-room-logica); de Excel past
   het uniform toe op alle FTE-groepen. De app-benadering is verdedigbaar; met de
   klant bevestigen welke definitie geldt.
5. **Nooit stilzwijgend een numerieke formule wijzigen** (ontwikkelhandleiding) — pas aan ná
   bevestiging.

> **NB — macro-reruns.** De klant-VBA is opnieuw draaibaar (masterdata wijzigen →
> `CreateVolumePlanningSheet` + `GenerateValuesSheet`). Bij elke rerun keert de
> PAP-formulebug `(1 - 2)` terug; die moet naar `(1 - 0,2)` gecorrigeerd worden
> (en de productiefractie in de mastersheet) vóór de cijfers kloppen.

## Bewijsmateriaal

- `exports/screenshots_raw/_composite/P_FINDING.png` — gecombineerde bevindingskaart
  (beide verschillen + netto EBIT), ingebed bij **F7** en **I12**.
- `exports/screenshots_raw/_composite/P_F7.png` — componenten (omzet/machine Δ=0,
  grondstof afwijkend).
- `exports/screenshots_raw/_composite/P_I12.png` — golden parity per lijn (Δ=0).
