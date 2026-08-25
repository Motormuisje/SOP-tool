# Validatiestrategie — handmatige validatie tegen een ground truth

**Status:** vastgesteld 25-08-2026 · geldt voor de hoofdrepo én de site-uitgaven (Winterswijk NLK1, Ankerkade NLU1)
**Eigenaar:** Apex Strategies · **Instrument:** `tools/ground_truth_diff.py`

> Kern in één zin: **we bewijzen de app niet met de app.** Elk cijfer dat de
> tool oplevert wordt vergeleken met een bron die onafhankelijk van de
> Python-code tot stand kwam — het klant-Excel, een handberekening of een
> wiskundige invariant — en elke afwijking krijgt een naam, een oorzaak en een
> besluit voordat we verder gaan.

---

## 1. Doel, scope en principes

**Doel.** Aantoonbaar maken, met bewijs dat een derde kan nalopen, dat de
planningscijfers (volumes L01–L12), de financiële cijfers (Values_Planning en
de consolidatie) en de FTE-cijfers van Apex Rainier gelijk zijn aan de ground
truth — of dat een verschil verklaard, gedocumenteerd en door de juiste persoon
goedgekeurd is.

**Scope.** De rekenkern (single-file-flow: werkboek in → export uit), de
interactieve laag (edits, cascade, undo/reset, herstart) en de site-uitgaven.
Buiten scope: opmaak van exports, prestaties, browserdetails — daar zijn de
bestaande geautomatiseerde suites voor (`docs/validatielijst-fase3.md`).

**Principes.**

1. **Δ = 0 is de norm.** Een afwijking binnen tolerantie is "gelijk"; alles
   daarbuiten is een bevinding. Toleranties worden nooit opgerekt om een ronde
   te laten slagen (§4).
2. **De app is niet automatisch fout — en het Excel ook niet.** De parallelle
   run van juli 2026 vond twee Excel-fouten (PAP-formule `(1-2)` i.p.v.
   `(1-0,2)`; een leeg tarief) waarbij de app gelijk had. Daarom bestaat er een
   *errata*-lijst per ground truth (§3) en een classificatie waarin "ground
   truth fout" een geldige uitkomst is (§6).
3. **Handmatig betekent: een mens beoordeelt, een instrument telt.** Het
   vergelijken van 25.000 cellen doet het script; het *oordeel* over elke
   afwijking, de steekproef door de hele keten en de handtekening zijn
   mensenwerk.
4. **Nooit stilzwijgend een formule wijzigen** (ontwikkelhandleiding, regel 4).
   Een bevinding leidt tot een besluit, dat besluit tot een wijziging — nooit
   andersom.
5. **Bewijs is reproduceerbaar.** Bij elke ronde horen de exacte bestanden
   (met hash), de commit, de parameters en het rapport van het instrument.

---

## 2. Ground-truth-bronnen — de hiërarchie

Er is niet één ground truth, maar vijf soorten, elk met een eigen bewijskracht.
Een ronde combineert ze; geen enkele bron alleen is voldoende.

| Code | Bron | Bewijst | Bewijst NIET | Eigenaar |
|---|---|---|---|---|
| **GT-A** | **Klant-Excel (MS_RECONC `.xlsm` na volledige VBA-macrorun)** | Dat de app het bestaande klantmodel reproduceert, cel voor cel, over alle materialen en periodes | Dat het klantmodel zelf juist is | Klant (modelbeheer) |
| **GT-B** | **Onafhankelijke handberekening** — een kleine set materialen die een validator met de hand (rekenmachine of formulevrij werkblad) door L01→L12 en de consolidatie haalt, uitgaand van de *functionele beschrijving* (procedurebestand, LOR), niet van de VBA-code | Dat de rekenregels inhoudelijk kloppen; toetst app én Excel | Volledigheid over alle materialen | Apex (validator) |
| **GT-C** | **Gespiegelde edit (mirror)** — dezelfde wijziging in de app én in het Excel; vergelijk de doorwerking | Dat de cascade (edits, BOM, capaciteit, financieel) identiek reageert | Edits die het Excel niet kent (machine-overrides, valuatieparameters, nieuwe producten) | Apex |
| **GT-D** | **Invarianten (behoudswetten)** — identiteiten die altijd moeten gelden, onafhankelijk van welke bron dan ook (§5.4) | Interne consistentie, ook op echte maandextracts waar geen Excel-run van bestaat | Dat de invoer of de formulekeuze juist is | Apex |
| **GT-E** | **Bevroren golden baseline** (`golden_baseline.json`, `tests/test_golden_pipeline.py`) | Dat de kern sinds de laatste vrijgave *niet veranderd* is | Correctheid — het is een regressiebewaker, geen waarheid | Apex (ontwikkeling) |

De bestaande site-tabbladen die niet in de klant-Excel bestaan (FTE-werkbank,
machine-inzet) kunnen alleen via GT-B en GT-D gevalideerd worden; op de
site-uitgaven zijn ze bewust niet beschikbaar.

---

## 3. Het ground-truth-register

Een ground truth is pas een ground truth als hij **bevroren** is. Voor elke GT-A
of GT-B bron leggen we vast:

| Veld | Inhoud |
|---|---|
| GT-ID | `GT-<site>-<jjjjmm>-<volgnr>`, bv. `GT-NLX1-202512-01` |
| Bestand | bestandsnaam + SHA-256 (PowerShell: `Get-FileHash -Algorithm SHA256`) |
| Soort | GT-A (Excel na macro) / GT-B (handberekening) |
| Planningsmaand · actuals-maanden · site | uit de `Config`-sheet (`InitialDate`, `ForecastMonths`, `ForecastActualsMonths`, `Site`) |
| Modelversie | VBA-versie of datum van het klantmodel; voor GT-B: versie van de functionele beschrijving |
| Bevroren door / op | naam + datum; daarna **nooit meer wijzigen** (nieuwe versie = nieuw ID) |
| Errata | bekende fouten in de bron met verwijzing naar de bevinding (bv. PAP-formule 600003822, leeg tarief 150000483) |
| Opslag | `%LOCALAPPDATA%\SOPPlanningEngine\ground_truth\<GT-ID>\` — **nooit in de repo** (klantdata, `.gitignore`) |

Regels:
- Een GT-A wordt gemaakt door het klant-Excel te openen, de volledige
  macro-run te doen (`CalculateFull`), op te slaan als kopie en te hashen.
  De kopie die de app als invoer krijgt is *dezelfde* bytes.
- Zonder registerregel geen validatieronde: het rapport verwijst altijd naar
  een GT-ID.
- Errata maken een bron niet ongeldig; ze maken de betreffende cellen
  *verwacht afwijkend* (classificatie B in §6) en het rapport telt ze apart.

**Eerste drie registerregels (te maken, §9):**
`GT-NLX1-202512-01` (golden fixture na macro-run), `GT-NLK1-…` (Winterswijk,
eerste echte maandextract), `GT-NLU1-…` (Ankerkade).

---

## 4. Vergelijkingsobjecten en toleranties

Het instrument matcht rijen op `(materiaal, lijntype, aux, aux 2)` en valt
terug op een kortere sleutel wanneer alleen een numerieke aux-kolom verschilt
(die is een *waarde*, geen identificatie — de app rondt hem op 2 decimalen af,
Excel niet). Vergeleken worden de periodekolommen en `Starting stock`.

| Object | Sheet | Lijnen | Eenheid | Tolerantie (absoluut **of** relatief) | Motivering |
|---|---|---|---|---:|---|
| Volumes | Planning sheet | L01, L02, L03, L05, L06 (productie & inkoop), L07 inkoopplan, L08 | ton / stuks | 1e-6 · 1e-9 | pure rekenkunde op dezelfde invoer: exact |
| Voorraad | Planning sheet | L04 (incl. `Starting stock`) | ton / stuks | 1e-6 · 1e-9 | idem |
| Capaciteit | Planning sheet | L07 bezetting (uren), L09 beschikbaar, L11 ploegen | uren | 1e-6 · 1e-9 | idem; **eerst controleren dat OEE/doorzet in beide bronnen met dezelfde precisie staan** (§7, bevinding 4) |
| Bezettingsgraad | Planning sheet | L10 | fractie (0–1) | 1e-6 · 1e-9 | **eenheid vaststellen**: fractie vs. procent (§7, bevinding 3) |
| FTE | Planning sheet | L12 | FTE | 1e-3 | ploegafronding in de bron |
| Financieel | Values_Planning sheet | alle lijnen | € | 0,01 | centen |
| Consolidatie | Values_Planning sheet | `13. Consolidation` (20 regels) | € | 0,01 | centen |
| Aux-kolommen | beide | — | divers | **niet normatief** (`--compare-aux` alleen ter informatie) | tarieven/uren/parameters, verschillend gedefinieerd per schrijver |
| Lege cel vs. 0 | beide | — | — | gelijk (`--no-blank-is-zero` om dit uit te zetten) | Excel schrijft lege cellen waar de app 0 schrijft |

Aanroep (standaardtoleranties zijn de strengste; verruim per object met
`--abs`/`--rel` en **documenteer waarom** in het rapport):

```powershell
python tools/ground_truth_diff.py "<GT-A>.xlsm" "<app-export>.xlsx" --md rapport.md --out afwijkingen.xlsx
python tools/ground_truth_diff.py "<GT-A>.xlsm" "<app-export>.xlsx" --sheet "Values_Planning sheet" --abs 0.01
```

Exitcode 0 = alles binnen tolerantie; 1 = bevindingen; 2 = niet vergelijkbaar.

---

## 5. De validatieronde — zeven stappen

Een volledige ronde duurt ± 1 dag (R1–R4 en R7) tot 2 dagen (met R5 en R6).
R1, R2 en R4 zijn verplicht bij **elke** vrijgave; R3, R5, R6 volgens de cadans
in §8.

### R0 — Voorbereiding
1. Kies de GT-ID's (register §3); controleer de hash van de bronbestanden.
2. Noteer de app-commit (`git rev-parse --short HEAD`) en de site
   (`start.cmd` van WSK/ANK of `python main.py` voor de hoofdrepo).
3. Maak de bewijsmap: `validatie/<jjjj-mm-dd>_<commit>_<GT-ID>/` (buiten de
   repo) met submappen `invoer/`, `exports/`, `rapporten/`, `screenshots/`.
4. Lege sessie: start de app met een schone `SOP_APP_DATA_DIR` zodat geen
   oude edits of masterdata-overrides meerekenen.

### R1 — Baseline-pariteit (GT-A, volledig)
1. Upload het GT-A-werkboek, Calculate met de Config-parameters uit het
   werkboek, exporteer het planningswerkboek → `exports/`.
2. Draai het instrument op Planning sheet én Values_Planning sheet met de
   standaardtoleranties; sla `rapport.md` en `afwijkingen.xlsx` op.
3. **Beoordeel elke afwijkingsklasse** (niet elke cel): het rapport groepeert
   per lijntype; open in `afwijkingen.xlsx` per lijntype de grootste en een
   willekeurige afwijking en classificeer volgens §6.
4. Verwacht resultaat: Planning sheet Δ=0 op alle lijnen; Values Δ=0 op alle
   lijnen behalve de errata-cellen van de GT.

### R2 — Handmatige steekproef door de hele keten (GT-B)
Doel: bewijzen dat de *regels* kloppen, niet alleen dat twee programma's het
eens zijn. Per ronde minimaal deze vijf ketens, elk met een ingevuld
**rekenvoorbeeld-formulier** (§10.2):

| # | Keten | Waarom deze |
|---|---|---|
| K1 | Eén **ingekocht grondstofmateriaal** met MOQ en levertijd | inkoopplan, MOQ-afronding, levertijdverschuiving (L03→L04→L06 inkoop→L07 inkoopplan) |
| K2 | Eén **bulkproduct** met BOM naar K1 | afhankelijke vraag ouder→kind (L06 ouder → L08 ouder → L02 kind), veiligheids-/doelvoorraad (L04/L05) |
| K3 | Eén **verpakt product** met BOM naar K2 en verpakkingsgoed | twee BOM-niveaus, topologische volgorde |
| K4 | Eén **machinegroep met ≥ 2 machines** waar K2 of K3 doorheen loopt | uren = volume ÷ doorzet, groep = MAX van zijn machines (molens), beschikbaarheid, OEE, L10, L11 |
| K5 | Eén **FTE-regel** (groep + truck/controlekamer) en de **20 consolidatieregels** voor één maand | L12, omzet = prijs × volume, grondstof-/machinekost, brutomarge → EBITDA → EBIT → cashflow |

Werkwijze: de validator schrijft per lijn de formule op **uit de functionele
beschrijving** (procedurebestand / LOR, niet uit de VBA en niet uit de
Python), vult de invoer in uit de bronsheets van het werkboek (Forecast, BOM,
Routing, Stock level, Safety stock, OEE, prijzen, kosten), rekent de verwachte
waarde uit, en zet daarnaast de waarde uit de app én uit het Excel. Drie
kolommen, drie bronnen; elke ongelijkheid is een bevinding — óók als app en
Excel het met elkaar eens zijn.

Wissel de gekozen materialen per ronde (rouleren), zodat na een jaar alle
producttypen, alle machinegroepen en alle randgevallen (MOQ > vraag, OEE = 0,
onbeperkte capaciteit, negatieve voorraad) aan bod zijn geweest.

### R3 — Gespiegelde edits (GT-C)
Uit `docs/parallelle-run-methodiek.md` de twaalf 1-op-1 spiegelbare edits
(prijs ×2, grondstofkost ×4, forecast-edit, cascade naar kindcomponent,
combinatie L01+L06, bulk 3 maanden, L05 multi-maand, …). Per edit:
1. Voer de edit in de app uit; exporteer.
2. Voer *dezelfde* edit in een **kopie** van het GT-A-werkboek uit (inputcel
   wijzigen + `CalculateFull`); sla op als `GT-…-mirror-<edit>.xlsm`.
3. Draai het instrument op het paar; verwacht Δ=0 op de productabel en de
   consolidatie.
4. Herstel de app-sessie (Reset) en controleer dat het instrument tegen het
   oorspronkelijke GT-A weer Δ=0 geeft — dat bewijst dat Reset volledig is.

Niet-spiegelbare edits (machine-overrides, valuatieparameters, nieuwe
producten, purchase receipt) worden **niet** overgeslagen maar via R2
(handberekening van de verwachte doorwerking) en R4 bewezen.

### R4 — Invarianten (GT-D) — altijd, ook op echte maandextracts
Controleer op de app-export, per materiaal/machine en per periode (steekproef
van ≥ 10 materialen en álle machines; het is toegestaan dit in een werkblad
met formules te doen, zolang die formules niet uit de app komen):

| Invariant | Identiteit |
|---|---|
| I1 Vraagopbouw | `L03 Total demand = L01 Demand forecast + Σ L02 Dependent demand` |
| I2 Ouder–kind-spiegel | `L02 (kind, aux = ouder) = L08 (ouder, aux = kind)` — cel voor cel |
| I3 Voorraadbalans | `L04[t] = L04[t−1] + L06 Productie[t] + L06 Inkoopontvangst[t] − L03[t]` (met `L04[0] = Starting stock`) |
| I4 Doelvoorraad | waar de vraag het toelaat: `L04[t] ≥ L05[t]`; een productie-/inkooporder ontstaat precies wanneer de balans zonder order onder L05 zou zakken |
| I5 MOQ | elke inkooporder ≥ MOQ; elke productieorder ≥ lotgrootte (indien ingesteld) |
| I6 Bezettingsgraad | `L10 = L07 bezetting ÷ L09 beschikbaar` (eenheid: fractie) |
| I7 Groepsregel | molengroep: `L07 groep = MAX(L07 machines in de groep)`; andere groepen: som — leg per groep vast welke regel geldt en toets die |
| I8 Omzet | `Values L01 = prijs × Planning L01` per materiaal/periode |
| I9 Consolidatie-keten | `Brutomarge = Omzet − Kostprijs` ; `EBITDA = Brutomarge − vaste kosten` ; `EBIT = EBITDA − afschrijving` — de twee laatste verschillen zijn **constant per maand** |
| I10 Geen ongeldige getallen | geen NaN/∞/lege cel waar een getal hoort; geen negatieve L06/L07 |
| I11 Lijnvolledigheid | alle verwachte lijntypen aanwezig voor elk actief materiaal (`EXPECTED_LINE_TYPES`) |

### R5 — Site-uitgaven (WSK, ANK)
Per site dezelfde R1 + R4 met het **eigen** maandextract en GT-A, gestart via
`start.cmd` (eigen poort en data-map). Extra controles:
- de tabbladen "Capaciteit & FTE" en "Machine-inzet" ontbreken; de zeven
  werkbank-tabellen staan niet onder Config;
- `Site` in de export = `NLK1` resp. `NLU1`;
- sessies van de ene site verschijnen niet in de andere (aparte data-map).

### R6 — Persistentie en herstart
Uit `docs/checklist-manuele-validatie.md`: B5, B6, C4 (combinatie-edit +
herstart), F11, G6, H8. Aangevuld met het instrument: exporteer vóór en ná de
herstart en vergelijk beide exports met elkaar (`ground_truth_diff.py` met de
pre-restart-export als "ground truth") — verwacht Δ=0.

### R7 — Beoordeling en aftekening
1. Vul het afwijkingenregister (§10.3): elke bevinding heeft classificatie,
   ernst, besluit, besluitnemer, datum.
2. Toets de vrijgaveregels (§6.3).
3. Onderteken het sign-off-formulier (§10.4); archiveer de bewijsmap.

---

## 6. Afwijkingsclassificatie en besluitregels

### 6.1 Klassen

| Klasse | Naam | Betekenis | Actie | Besluit door |
|---|---|---|---|---|
| **A** | App-fout | de app wijkt af van GT en de GT is juist (bevestigd via GT-B of I1–I11) | bevinding → herstel in de hoofdrepo → nieuwe ronde | Apex ontwikkeling |
| **B** | Ground-truth-fout | het klantmodel of de handberekening bevat een fout; de app is juist | erratum in het register; melding aan de klant; **app niet aanpassen** | Klant (modelbeheer) |
| **C** | Definitieverschil | beide bronnen zijn intern consistent maar hanteren een andere definitie (bv. directe FTE-kost gescoopt op productie-FTE vs. alle FTE) | beslisnotitie; de klant kiest; daarna wordt de gekozen definitie de norm in beide | Klant, geadviseerd door Apex |
| **D** | Presentatie / afronding | zelfde onderliggende waarde, andere weergave (leeg vs 0, fractie vs %, 2 decimalen, aux-kolommen, ontbrekende nul-rij) | documenteren; eventueel export aanpassen — nooit de rekenkern | Apex |
| **E** | Uitlijning / timing | periodeverschuiving (planningsmaand, actuals-maanden, levertijd-offset) tussen de twee runs | parameters gelijktrekken en opnieuw draaien; blijft het: verder onderzoeken als A/B/C | Apex validator |
| **F** | Testartefact | een van beide kanten bevat edits, overrides of masterdata-wijzigingen die de andere niet heeft | geen bevinding; paar afkeuren, schone bronnen maken | Apex validator |

### 6.2 Ernst

- **Blokkerend** — raakt L01–L08, L04-balans, omzet/kostprijs of een
  consolidatieregel met |Δ| > tolerantie op meer dan één materiaal.
- **Groot** — capaciteit/FTE (L07–L12) of één materiaal; of een D/E-klasse
  die een gebruiker op het verkeerde been zet (eenheid, ontbrekende rij).
- **Klein** — aux-kolommen, weergave, documentatie.

### 6.3 Vrijgaveregels

Een versie mag naar de klant wanneer:
1. R1 op ≥ 1 GT-A per site: **0 open A-bevindingen**, alle overige cellen Δ=0
   of gedekt door een erratum (B) of een genomen besluit (C);
2. R2: vijf ketens ingevuld, alle drie kolommen gelijk of de ongelijkheid is
   geclassificeerd en besloten;
3. R4: I1–I11 zonder open afwijkingen;
4. `python main.py --test` en `pytest tests --ignore=tests/browser` groen op de
   vrijgegeven commit (GT-E: bewaker dat er tussen validatie en vrijgave niets
   verschoof);
5. sign-off door validator én ontwikkelaar; bij C-besluiten ook door de klant.

Wat we **niet** doen: toleranties oprekken tot het past; de golden baseline
blind hergenereren; het klant-Excel corrigeren zonder de klant; een bevinding
"klein" noemen omdat het er maar één is.

---

## 7. Nulmeting — 25-08-2026, bestaande testparen

Het instrument is voor het eerst gedraaid op de twee bewaarde paren uit de
handmatige tests van juli (map *officieel test documenten sop*): `test a + b`
en `test c + d`, elk Excel (`.xlsm`) versus app-export (`.xlsx`). **Let op:**
dit zijn *eindtoestanden ná de tests A/B resp. C/D*, inclusief de edits die
tijdens die tests zijn gedaan — geen bevroren GT-A-paren. De nulmeting toont
dus wat het instrument ziet, niet het eindoordeel over de app.

| Paar | Sheet | Cellen | Gelijk | Afwijkingen | Waarvan te onderzoeken |
|---|---|---:|---:|---:|---|
| a+b | Planning sheet | 25 649 | 25 585 (99,75 %) | 64 | één BOM-paar (400000455 ↔ 600007751): 196,47 verschuift van dec-2025 naar jan-2026 en trekt L03/L04/L06/L07 van dat paar mee |
| a+b | Values_Planning | 7 501 | 7 217 (96,2 %) | 284 | zie hieronder |
| c+d | Planning sheet | 25 649 | 25 522 (99,50 %) | 127 | machine Z_MACH20 (L09/L10), ZZ_GROUP03/Z_MACH14–16 op 0,02–0,03 % |
| c+d | Values_Planning | 7 501 | 7 130 (95,1 %) | 371 | zie hieronder |

Rijmatching: 1 973/1 973 rijen gematcht op Planning; 577/578 op Values (één
rij `Z_MACH18 · 07. Capacity utilization` staat alleen in het Excel, met
aux 0 — vermoedelijk een nul-rij die de app niet schrijft).

**Kandidaat-bevindingen** (nog *ongeclassificeerd* — de eerste ronde R1 op een
schoon GT-A-paar moet ze bevestigen of wegverklaren):

| # | Waarneming | Waarschijnlijke klasse | Eerste vraag |
|---|---|---|---|
| 1 | Values `01. Demand forecast`: **216 cellen** afwijkend in *beide* paren (18 materialen × 12 periodes) | C of A — systematisch | welk tarief/volume gebruikt de omzetregel voor deze 18 materialen? (prijsbron, PAP-verdeling) |
| 2 | `ZZZZZZ_INVENTORY VALUE · Starting stock`: Excel 5 246 842,02 — app 0 | D (export vult startvoorraad van de consolidatierij niet) | is de startwaarde elders in de app zichtbaar? |
| 3 | `Z_MACH20 · 10. Utilization rate`: Excel 22,04 — app 0,2204 (×100) en `09. Available capacity` leeg vs 1 in okt–dec 2026 | D (eenheid) + E/A (laatste drie maanden) | eenheid van L10 vastleggen; waarom heeft de Excel geen beschikbaarheid in okt–dec? |
| 4 | `ZZ_GROUP03`, `Z_MACH14/15/16 · 07. Capacity utilization`: 0,02–0,03 % lager in de app | D (precisie van OEE/doorzet in de bron: 76,45 vs 76,4499…) | met welke precisie leest de app de OEE-sheet? |
| 5 | a+b: BOM-paar 400000455/600007751: bedrag 196,47 wisselt van maand | E of F (levertijd-offset of test-edit in één van beide) | staat er een edit op dit paar in `Edits Summary`? |
| 6 | `13. Consolidation` (a+b: 50 cellen, c+d: 91 cellen) volgt uit 1–5 | afgeleid | vervalt zodra 1–5 verklaard zijn |

Bevinding 1 is de belangrijkste: hij is systematisch, financieel en aanwezig
in beide paren. Hij krijgt prioriteit in de eerste ronde (§9).

---

## 8. Rollen, cadans en bewijsdossier

| Rol | Doet | Tekent |
|---|---|---|
| **Validator** (Apex, niet de ontwikkelaar van de betrokken wijziging) | R0–R7, GT-B-handberekeningen, classificatie, register | sign-off |
| **Ontwikkelaar** (Apex) | levert commit, `--test`/pytest-bewijs, herstelt A-bevindingen | sign-off |
| **Modelbeheer klant** | levert GT-A (macro-run), beoordeelt B-errata, beslist C | C-besluiten |
| **Reviewer** (tweede paar ogen bij vrijgave) | leest het dossier; steekproef van 3 bevindingen naloopt | paraaf |

| Moment | Ronde |
|---|---|
| **Elke vrijgave** (hoofdrepo → sites) | R0, R1, R2, R4, R6, R7; R3 als er iets aan cascade/edits veranderde; R5 per site die de vrijgave krijgt |
| **Elke maandcyclus bij de klant** (nieuw SAP-extract) | R4 op de echte export + steekproef van 3 materialen door de keten (R2-light) + aantallen per dataset ↔ extract; geen Excel-parallel nodig |
| **Na wijziging in `modules/`** | minimaal R1 + R4, plus R2 op de betrokken keten(s) |
| **Jaarlijks** | volledige ronde met **nieuwe** GT-B-ketens (rouleren) en herijking van de errata |

Bewijsdossier per ronde (buiten de repo, wél bewaard):

```
validatie/2026-09-05_82f7643_GT-NLX1-202512-01/
├── invoer/        GT-A.xlsm + hash.txt, config-parameters
├── exports/       app-export(s), mirror-werkboeken
├── rapporten/     rapport.md, afwijkingen.xlsx (instrument), invarianten.xlsx
├── rekenvoorbeelden/  K1..K5 ingevulde formulieren (+ bronscreens)
├── screenshots/   volgens docs/screenshot-richtlijnen.md
└── register.md    afwijkingenregister + sign-off
```

---

## 9. Eerste drie rondes (plan)

1. **Ronde 1 — schoon GT-A-paar op het golden fixture** (`GT-NLX1-202512-01`):
   macro-run op `golden_MS_RECONC.xlsm`, bevriezen, R1 draaien. Doel:
   kandidaat-bevindingen 1–6 uit §7 classificeren; errata-lijst starten (PAP
   600003822, tarief 150000483). Daarna GT-B-ketens K1–K5 voor dit werkboek.
2. **Ronde 2 — Winterswijk** (`GT-NLK1-…`): eerste echte maandextract, R1 + R4
   + R5; hidden-tabs-controle.
3. **Ronde 3 — Ankerkade** (`GT-NLU1-…`): idem.

Pas na ronde 1 met 0 open A-bevindingen worden de toleranties uit §4
definitief; tot die tijd zijn ze de *strengste* (1e-6) en is elke verruiming
een expliciete beslissing in het register.

---

## 10. Formulieren

### 10.1 Ground-truth-register

| GT-ID | Bestand | SHA-256 | Soort | Planningsmaand | Actuals | Site | Modelversie | Bevroren door/op | Errata | Opslag |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

### 10.2 Rekenvoorbeeld-formulier (één per keten K1–K5)

**Ronde:** … **GT-ID:** … **Commit:** … **Validator:** … **Materiaal/machine:** … **Periode(s):** …

| Lijn | Formule (uit functionele beschrijving, met bronverwijzing) | Invoer (waarde + bronsheet/cel) | Verwacht (handberekening) | App | Excel | Gelijk? | Bevinding-nr |
|---|---|---|---|---|---|---|---|
| L01 | | | | | | | |
| L02 | | | | | | | |
| L03 | | | | | | | |
| L04 | | | | | | | |
| L05 | | | | | | | |
| L06 | | | | | | | |
| L07 | | | | | | | |
| L08 | | | | | | | |
| L09 | | | | | | | |
| L10 | | | | | | | |
| L11 | | | | | | | |
| L12 | | | | | | | |
| Values L01 (omzet) | | | | | | | |
| Consolidatie (20 regels, één maand) | | | | | | | |

### 10.3 Afwijkingenregister

| Nr | Ronde | Sheet · materiaal · lijn · periode | GT | App | Δ | Klasse (A–F) | Ernst | Analyse (oorzaak) | Besluit | Besluitnemer | Datum | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | |

### 10.4 Sign-off

**Versie/commit:** … **Site(s):** … **GT-ID's:** … **Ronde-map:** …

| Stap | Uitgevoerd | Resultaat | Opmerking |
|---|---|---|---|
| R1 baseline-pariteit | ☐ | Δ=0 / bevindingen: … | |
| R2 rekenvoorbeelden K1–K5 | ☐ | | |
| R3 gespiegelde edits (n = …) | ☐ | | |
| R4 invarianten I1–I11 | ☐ | | |
| R5 site-uitgaven | ☐ | | |
| R6 persistentie/herstart | ☐ | | |
| `main.py --test` + pytest (GT-E) | ☐ | | |

**Open A-bevindingen:** 0 / … **Open C-besluiten:** … **Errata (B):** …

**Eindoordeel:** ☐ vrijgeven ☐ vrijgeven met besluiten ☐ niet vrijgeven

Validator: ______ Ontwikkelaar: ______ Reviewer: ______ Klant (bij C): ______

---

## 11. Verhouding tot bestaande documenten

- `docs/checklist-manuele-validatie.md` — de UI-/gedragschecklist (A–I);
  blijft de bron voor R6 en voor functionele acceptatie. Deze strategie voegt
  het cijferbewijs toe, geen vervanging.
- `docs/parallelle-run-methodiek.md` — de methode en dekkingsmatrix voor R3;
  de scripts uit de scratchpad zijn vervangen door `tools/ground_truth_diff.py`.
- `docs/bevinding-parallelle-run-grondstofkost.md` — eerste errata (B) en
  eerste definitieverschil (C); de sjablonen in §10 zijn daarop gebaseerd.
- `docs/validatielijst-fase3.md`, `tests/README.md` — de geautomatiseerde
  bewaking (GT-E); vrijgaveregel 4.
- `docs/ontwikkelhandleiding.md` — regel 4 (nooit stilzwijgend een formule
  wijzigen) en de zes syncpunten die R6 raakt.
