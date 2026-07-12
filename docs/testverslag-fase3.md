# Testverslag — Apex Rainier Planning Tool, functionaliteitsronde 2026-07

**Versie:** 1.0 · **Datum:** 12 juli 2026 · **Branch:** `fase-3` (tag `milestone-fase-3`)
**Doel:** onderbouwing van de kwaliteitsgarantie voor de opgeleverde functionaliteit
(bugfixronde Fase 0, features Fase 1–2, dynamische producten, grafiek-analyse,
materiaalgroepen, master-config-vervanging).

---

## 1. Samenvatting

| Verificatie | Resultaat |
|---|---|
| Backend-testsuite (unit, route, golden, integratie) | **677 geslaagd**, 1 overgeslagen*, 0 gefaald |
| Browser-end-to-end-suite (Playwright, echte server) | **68 geslaagd**, 0 gefaald — **tweemaal volledig gedraaid** ter uitsluiting van toevalstreffers |
| Golden parity (cel-voor-cel exportvergelijking) | **"all cells identical"** — byte-voor-byte gelijk aan de gevalideerde basislijn |
| `python main.py --test` (rooksuite met assertions) | geslaagd |
| Echte herstart-tests (proces gedood en herstart) | geslaagd — alle sessietoestand komt aantoonbaar terug |
| Performance | overlay/analyse voegen < 1% rekentijd toe (steady-state, interleaved gemeten) |

\* De overgeslagen test vereist een omgevingsvariabele die alleen op de
CI-referentiemachine gezet wordt; hij is geen onderdeel van de garantie-scope.

**Kern van de garantie:** elke nieuwe functie is *additief en opt-in* gebouwd.
De rekenkern (VBA-pariteit) is in geen enkele oplevering gewijzigd, en dat is
geen belofte maar een geautomatiseerde controle: zolang geen nieuwe functie
wordt gebruikt, is de Excel-export **cel-voor-cel identiek** aan de basislijn
van vóór deze ronde.

## 2. Testmethodologie (vijf lagen)

1. **Unit-tests (synthetisch, fixture-vrij)** — pure logica met handgemaakte
   data: validatieregels (incl. Nederlandstalige foutmeldingen), cyclusdetectie,
   scoping-wiskunde, serialisatie-round-trips. Snel en deterministisch; draaien
   bij elke wijziging.
2. **Golden-fixture-tests** — de volledige rekenpijplijn op een representatief
   klantwerkboek. Twee soorten borging:
   - *Pariteit*: resultaat-dataframes en exports worden vergeleken met een
     bevroren basislijn (`assert_frame_equal`, cel-diff van de export).
   - *Gedrag*: nieuwe functies worden op echte data doorgerekend en exact
     geasserteerd (bijv. omzet = prijs × volume per periode, dependent demand
     = productieplan × stuklijstfactor).
3. **Route-tests** — elk API-endpoint met nepafhankelijkheden: foutpaden,
   validatie, rollback bij geweigerde rebuilds, opruimen van afgeleide staat.
4. **Integratietests met echt serverproces** — een aparte server per
   testmodule: sessies aanmaken, wisselen, instantie-snapshots, **echte
   procesherstart** (kill + reboot op dezelfde datamap), werkboek-vrije
   berekeningen. Deze laag ving de sessiewissel-bug en bewaakt de
   persistentiegaranties.
5. **Browser-end-to-end (Playwright)** — de echte UI tegen een echte server:
   formulieren, modals, grafieken, filters, dialogen. Elke test eindigt met
   `assert page.js_errors == []` — geen enkele consolefout wordt getolereerd.

## 3. Structurele garanties (afgedwongen, niet beloofd)

- **Golden parity.** Basislijn = export van de gevalideerde versie. Elke
  oplevering draait de volledige berekening en vergelijkt de export
  cel-voor-cel. Resultaat deze ronde: *identiek*, met alle nieuwe code aan
  boord.
- **Replay is de waarheid.** Bewerkingen worden opgeslagen als replaybare
  stappen; tests bewijzen dat live-gedrag en na-herstart-replay hetzelfde
  resultaat geven (o.a. voor bewerkingen op dynamisch toegevoegde producten).
- **De zes synchronisatiepunten.** Elke nieuwe sessietoestand (opmerkingen,
  producten, groepen, masterdata-verwijzing) is expliciet getest op: reset,
  sessiewissel, rebuild, replay, herberekening en schijfpersistentie.
- **Sessie-isolatie.** Getest: een verse upload erft niets van de vorige
  sessie; instantie-snapshots zijn onafhankelijke kopieën; wisselen lekt geen
  configuratie (de historische spiegel-bug is gefixt én geborgd met tests die
  op de oude code aantoonbaar faalden).
- **Eerlijkheidsregels.** Cijfers die niet exact toerekenbaar zijn worden
  nooit benaderd: vaste kosten/EBIT/ROCE verdwijnen uit groepsweergaven
  (met uitleg), bezetting wordt als *aandeel* getoond, FTE blijft
  fabrieksbreed gelabeld. Deze regels zijn per stuk getest.
- **Validatie door hydratie (masterdata).** Een bewerking wordt alleen
  geaccepteerd als het volledige masterbestand er daarna nog mee ingelezen
  kan worden — er bestaat geen tweede regelset die kan afwijken.

## 4. Dekking per opgeleverde functie

| Functie | Belangrijkste geautomatiseerde bewijzen |
|---|---|
| **Dynamische producten** | 40 unit- (validatie/cycli/normalisatie) + 23 golden-tests: pariteit bestaande rijen, standalone- én geïntegreerde producten, dependent demand beide richtingen, verwervingsmatrix (aangekocht/geproduceerd/mix incl. bewust foute combinaties), exacte financiële doorwerking t/m geconsolideerde omzet, export-smoke, herstart/replay; 5 browser-E2E's; sessiewissel-/snapshot-/herstart-integratie (4 ketentests, eigen server) |
| **Opmerkingen** | route-tests (upsert/verwijderen/persistentie), export-blad, browser-test ezelsoortje + popover |
| **Grafiek-analyse** | 15 browser-E2E's: reconciliatie som-bijdragen ↔ grafiekbeweging, componentsplitsing, exacte ROCE-ratio-identiteit, twee-punten-selectie, paneel-in-kaart-regressie, machine-drill, planning-doorsteek, Excel-export (3 backend-tests op het exportendpoint) |
| **Materiaalgroepen** | 17 route-tests (CRUD/activeren/prune), 7 scoping-unit-tests (exacte sommen, aandeel ≤ vol, bijdragemarge-wiskunde), 6 golden-endpointtests (o.a. payload byte-gelijk na deactiveren), herstart-integratie, 3 browser-E2E's incl. de oorspronkelijke filterbug als regressietest |
| **Master-config vervanging** | golden round-trip (élke masterstructuur identiek aan de Excel-lezer), volledige engine-run zonder enig werkboek, store-persistentie met versie/quarantaine, 6 route-tests (import/confirm-diff/PATCH-hydratie), werkboek-vrije upload+berekening via de echte routes, rebuild-vangnet, browser-E2E import + bewerken |
| **Fase 0-bugfixes & infrastructuur** | elke fix draagt een eigen regressietest (o.a. reset-herstel, undo/override-consistentie, atomaire config-writes, padtraversal, threadveiligheid, rebuild-vergrendeling met overlap-detectie) |

## 5. Herhaalbaarheid (hoe dit verslag te reproduceren)

```powershell
# vereist: SOP_GOLDEN_FIXTURE wijst naar het referentiewerkboek
python -m pytest tests -q --ignore=tests/browser --ignore=tests/performance   # backend
python -m pytest tests/browser -q                                             # browser-E2E
python main.py --test                                                         # rooksuite
```

De golden-parity-celvergelijking draait via het diff-script op de export van
`--test` tegen de bevroren basislijn-export.

## 6. Bekende, bewuste begrenzingen (geen defecten)

1. Maand-over-maand-vergelijking tussen cycli toont dynamisch toegevoegde
   producten niet (bestaande koppelingsbeperking, gedocumenteerd).
2. Excel-export en MoM zijn niet gescoopt op een actieve materiaalgroep (v1).
3. De maandelijkse SAP-extracts blijven de transactionele input; volledige
   Excel-onafhankelijkheid vergt de SAP-koppeling (aparte vervolgstap).
4. Meerdere gelijktijdige gebruikers delen de actieve instantie (bestaande
   architectuurkeuze; rebuilds zijn wel vergrendeld tegen races).

## 7. Handmatige validatieronde (juli 2026) — 92 checks

Bovenop de geautomatiseerde suites is de volledige applicatie handmatig
tegen de live-server gevalideerd via een checklist van **92 controles** in
negen domeinen (A masterdata, B sessies, C bewerkingen/cascade, D dynamische
producten, E grafiek-analyse, F materiaalgroepen, G machines, H exports,
I afsluiting). Elke check is uitgevoerd tegen de draaiende app, waar mogelijk
met API-verificatie van de onderliggende cijfers naast het visuele bewijs;
elke check heeft een screenshot. Zie `docs/checklist-manuele-validatie.md`
en het ingevulde werkboek in `exports/`.

**Resultaat: 91/92 OK, 1 afwijking (gevonden én gefixt tijdens de ronde).**

Enkele diepere verificaties uit deze ronde:
- Totale vraag = forecast + afhankelijke vraag: 360/360 steekproefcellen exact.
- Bijdragemarge = omzet − grondstofkost − machinekost: exact (bevestigd op de
  gescoopte P&L onder een actieve materiaalgroep); FTE/capaciteit blijven
  bewust fabrieksbreed.
- Omzet = prijs × volume voor toegevoegde producten: exact per product.
- Undo van een BOM-parent-edit herstelt het (actieve) kind exact naar baseline.
- Effectieve doorzet schaalt lineair met OEE (basis van de doeldoorzet-functie).
- KPI's byte-identiek voor/na een echte procesherstart.

### Bevindingen en fixes uit deze ronde

1. **Getalparser accepteerde misvormde invoer** (checklist A6). "3000,5,6" werd
   stil 300056; "12abc" werd 12. Oorzaak: groepering werd blind gestript en het
   eindresultaat niet gevalideerd. **Gefixt**: groepering moet echte groepen van
   drie zijn en het hele veld een geldig getal; anders weigering. Regressietest
   met 13 gevallen + het gemelde scenario. (De enige "afwijking" in de checklist
   staat als bewijs bewaard; de fix is geverifieerd.)
2. **Numerieke nul-aux resurrecteerde na herstart.** Een edit op een rij met
   `aux_column = 0` overleefde de undo en dook na herstart weer op, doordat de
   editsleutel met `aux or ''` werd gebouwd (0 is falsy → sleutel-mismatch).
   **Gefixt** met een canonieke aux-normalisatie; regressietests toegevoegd.
3. **Toegevoegd product niet bruikbaar als component.** De materialenlijst
   filterde alle toegevoegde producten weg, waardoor een volgend product er
   niet naar kon verwijzen. **Gefixt**: toegevoegde producten worden getoond
   (gemarkeerd); live geverifieerd dat product B product A als component gebruikt.

Daarnaast bleek een aanvankelijk vermoede "undo-cascade-bug" een **schijnbug**:
het testmateriaal stond nog gedeactiveerd van een eerdere test, waardoor de
volledige build 0 gaf en de incrementele cascade een waarde. Met een actief
materiaal round-trippt de undo exact; de rekenkern is niet gewijzigd.

Alle drie de fixes draaien met groene backend- (683+) en browsersuites (74)
en behouden de golden-parity (`python main.py --test`).

## 8. Conclusie

Alle geautomatiseerde controles slagen, de rekenkern is aantoonbaar ongewijzigd
(byte-identieke export, groene parity-smoke), de persistentie- en isolatie-
garanties zijn met echte procesherstarts bewezen, en de 92-check handmatige
ronde bevestigt de functionaliteit end-to-end met drie onderweg gevonden en
gefixte defecten. Op basis hiervan kan de oplevering met garantie worden
aangeboden, met de expliciete begrenzingen uit §6.
