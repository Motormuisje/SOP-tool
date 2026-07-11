# Ontwerpnota Fase 3 — Dynamische producten & integratie

Versie 0.9 (concept) — 2026-07-11
Status: **ontwerp-eerst**. Geen bouw vóór (a) antwoord op klantvragen 5 & 6 en
(b) GO op de proof-of-concept (PoC-acceptatiecriteria onderaan).

Deze nota hoort bij [implementatieplan-sibelco.md](implementatieplan-sibelco.md)
Fase 3 en bij het bugregister [../BUGS.md](../BUGS.md).

---

## 1. Waarom ontwerp-eerst

Fase 1 en 2 waren additief: elke feature staat naast de rekenkern en de
*golden parity* (zelfde input → byte-voor-byte zelfde output) bleef intact.
Dynamische producten raken juist de **kern**: de gedeelde datastructuren en de
stuklijst-volgorde waar forecast → productie/inkoop → capaciteit → financieel →
export allemaal op steunen. docs/ontwikkelhandleiding.md waarschuwt expliciet: het doorbreken van
de BOM-topologische volgorde geeft geen foutmelding maar **stil verkeerde
getallen**. Daarom eerst ontwerp + PoC, dan pas bouw.

## 2. Open klantvragen (blokkerend)

- **Vraag 6 — dynamische producten:** harde wens op korte termijn, of vooral
  richtingvraag? Bepaalt of we naar productie bouwen of enkel een PoC leveren.
- **Vraag 5 — integratiegradatie:** (a) master sheet vervangen door beheer in
  Python/config, (b) gedeeltelijke koppeling, of (c) volledige directe pipeline
  met het bronsysteem. Bepaalt de scope van §5.

## 3. Huidige datamodel (waar producten vandaan komen)

Ingelezen door `modules/data_loader.py` (`DataLoader.load_all`), gebruikt als
gedeelde bron door alle engines:

| Structuur | Bron (sheet/extract) | Sleutel | Consumenten |
|---|---|---|---|
| `materials: {mat: Material}` | Material master | `material_number` | alle engines |
| `bom: [BOMItem]` | BOM extract | (parent, component) | `BOMEngine`, inventory |
| `routing` | Routing extract | material → work centers | `CapacityEngine` |
| `machines`, `machine_groups` | OEE/routing | machine code | `CapacityEngine` |
| `forecasts: {mat: {period: val}}` | Forecast sheet | `material_number` | `ForecastEngine` |
| `stock_levels`, `safety_stock` | Stock extract | `material_number` | `InventoryEngine` |
| `purchased_and_produced` | config | `material_number` | inkoop/productie-split |

`BOMEngine.assign()` kent elk materiaal een **level** toe (0 = eindproduct);
`PlanningEngine.run()` verwerkt daarna strikt level-voor-level, zodat de
productieplannen van een parent de afhankelijke vraag van de child worden.

## 4. Dynamische producten — voorgestelde aanpak

### 4.1 Kernprincipe: additieve overlay, workbook blijft bron van waarheid

Net als de forecast-defaultvolumes (Fase 1.3) stellen we een **product-overlay**
voor: een set toegevoegde producten die ná het inlezen van het workbook, maar
vóór de engines, in de gedeelde datastructuren wordt geïnjecteerd. Voordelen:

- Bestaande materialen blijven ongewijzigd → golden parity voor het niet-
  gewijzigde deel blijft toetsbaar (PoC-criterium TP3-02).
- Geen wijziging aan de VBA-pariteit van de rekenformules.
- De overlay is data, geen code — serialiseerbaar en per-sessie/-config te beheren.

### 4.2 Wat een "toegevoegd product" minimaal bevat

```
AddedProduct = {
  material_number, name, product_family, spc_product, product_cluster,
  product_type,                        # bulk/packaged/raw/... (stuurt engine-gedrag)
  forecast: {period: value}?,          # optioneel (anders 0 of default-overlay)
  stock_level, safety_stock?,          # optioneel
  bom_as_parent: [{component, qty_per}]?,   # dit product gebruikt componenten
  bom_as_child:  [{parent, qty_per}]?,      # dit product is component van parents
  routing: [{work_center, base_qty, std_time}]?,  # capaciteitsbeslag
  purchased_and_produced_fraction?     # inkoop/productie-split
}
```

### 4.3 Injectiepunt en volgorde-impact

Injectie in een nieuwe stap **STEP 1c** in `PlanningEngine.run()`, direct na
`DataLoader.load_all()` en vóór STEP 2:

1. `materials[mat] = Material(...)` — nieuw materiaal registreren.
2. `bom` uitbreiden met de nieuwe (parent, component)-randen.
3. `routing`/`machines` uitbreiden waar nodig.
4. `forecasts`, `stock_levels`, `safety_stock` aanvullen.
5. **BOM-levels volledig herberekenen** (`BOMEngine.assign()` opnieuw) — dit is
   de kritieke stap: een nieuw product als parent of child verschuift levels.
6. Cyclusdetectie toevoegen (zie risico R1).

Omdat levels *herberekend* worden, blijft de level-voor-level-verwerking in
STEP 4 correct — mits de overlay vóór de leveltoewijzing wordt toegepast.

### 4.4 State-model (de zes sync-punten)

De product-overlay is **configuratie op instance-niveau**, vergelijkbaar met
`forecast_defaults` (build-time), niet met per-cel `pending_edits`. Voorstel:
een store `added_products` naast `forecast_defaults`:

1. Reset-baseline: overlay hoort in de baseline (het is deel van de "schone"
   berekening van deze instance).
2. `_sync_global_config_from_engine` / `get_session_config_overrides`: overlay
   meenemen als config-override, zodat rebuilds hem toepassen.
3. Rebuild na herstart/parameterwijziging: overlay opnieuw injecteren.
4. Replay: `pending_edits` op toegevoegde producten moeten ná injectie
   replaybaar zijn (de rijen bestaan dan).
5. Herberekening: het toevoegen/wijzigen van een product triggert een volledige
   rebuild (structurele wijziging, zoals site/forecast_months).
6. Persistentie: serialiseren in `sessions_store.json` (of `global_config` als
   het instance-overstijgend beheer wordt — afhankelijk van vraag 5).

### 4.5 Risico's

- **R1 — BOM-cycli:** een nieuw product dat (in)direct zichzelf als component
  krijgt. Bestaat nu al latent (BUGS.md M6: cycli worden niet gedetecteerd).
  Vereist: expliciete cyclusdetectie in `BOMEngine.assign()` met nette fout,
  vóór we gebruikers zelf randen laten toevoegen.
- **R2 — sleutelcollisies / dtype:** material numbers als float `"...0"`
  (BUGS.md M1). Een UI die material numbers accepteert moet normaliseren.
- **R3 — verwijderen/deactiveren:** mag geen wees-rijen of kapotte cascade
  achterlaten (PoC-criterium TP3-05).
- **R4 — export/MoM:** toegevoegde producten moeten correct in de Excel-export
  en (na fix van BUGS.md H3) in de MoM-vergelijking verschijnen.

## 5. Master-sheet-vervanging & integratie (vraag 5)

| Gradatie | Inhoud | Haalbaarheid | Afhankelijkheid |
|---|---|---|---|
| (a) | Master sheet → beheer in Python/config; losse-bestand-afhankelijkheden en dubbele logica weg | Goed haalbaar; bouwt op de config-infrastructuur (`global_config`, extract-loaders) | Geen extern systeem nodig |
| (b) | Gedeeltelijke koppeling (bijv. periodieke export uit bronsysteem inlezen) | Middel; afhankelijk van exportformaat | Stabiel exportformaat van Sibelco |
| (c) | Volledige directe pipeline met bronsysteem (API/DB) | Lastig; sterk systeemafhankelijk | API/DB-toegang + security review |

**Advies:** begin met (a). Het neemt de meeste dubbele logica en
bestand-afhankelijkheden weg met beheersbaar risico, en is een natuurlijke
opstap naar (b)/(c) later. (a) sluit ook aan op de product-overlay: het
"master"-deel wordt dan config die de overlay voedt.

## 6. Voorgesteld traject

1. **Werksessie** met Sibelco: vragen 5 & 6 vastleggen; gradatie (a/b/c) kiezen.
2. **Ontwerp-detaillering** (1–2 dagen): datacontract `AddedProduct` bevriezen;
   cyclusdetectie (R1) als voorwaarde inplannen.
3. **PoC** (~1 week) op een kopie-omgeving: één product toevoegen via UI/config,
   end-to-end door L01–L12, waarde-overlay en export.

## 7. PoC-acceptatiecriteria (GO/NO-GO voor bouw)

Overgenomen uit het implementatieplan (TP-3); alle zes moeten PASS zijn:

| ID | Criterium |
|---|---|
| TP3-01 | Nieuw product met forecast + BOM-koppeling verschijnt correct in L01–L12, waarde-overlay en export |
| TP3-02 | Golden parity voor bestaande materialen: export vóór/na toevoegen verschilt uitsluitend in de regels van het nieuwe product |
| TP3-03 | Nieuw product als child én als parent (dependent demand beide richtingen) |
| TP3-04 | Herstart: dynamisch product overleeft rebuild/replay |
| TP3-05 | Verwijderen/deactiveren laat geen wees-regels of kapotte cascade achter |
| TP3-06 | Performance: laadtijd en edit-cascade binnen 20% van huidige niveau |

**GO:** alle zes PASS → bouwfase inplannen met eigen testprotocol.
**NO-GO:** ontwerp herzien; geen gedeeltelijke integratie van PoC-code in productie.

## 8. Aanbeveling

1. Los eerst BUGS.md **M6 (cyclusdetectie)** en **M1 (material-number dtype)** op
   — het zijn voorwaarden voor veilig gebruikersbeheer van BOM-randen.
2. Kies integratiegradatie **(a)** als startpunt.
3. Bouw de product-overlay als **additieve, opt-in** laag (zoals Fase 1.3), zodat
   golden parity het regressienet blijft.
4. Behandel dynamische producten pas als "productie" na een geslaagde PoC.
