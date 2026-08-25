# SOP Clean Programma

Deze map bevat alleen de bestanden die nodig zijn om de applicatie als Python-programma te draaien.

## Starten

```powershell
pip install -r requirements.txt
python main.py
```

Daarna opent de app normaal op:

```text
http://localhost:5000
```

## Runtime data

Uploads, exports, sessies en configuratie worden standaard niet in deze map bewaard, maar in:

```text
%LOCALAPPDATA%\SOPPlanningEngine
```

Wil je dat tijdelijk ergens anders zetten, start dan met:

```powershell
$env:SOP_APP_DATA_DIR = "C:\pad\naar\data"
python main.py
```

## Tests

```powershell
python -m pytest tests -q --ignore=tests/browser   # snelle suite (incl. golden)
python main.py --test                              # zelftest van de app
python -m pytest tests/browser -q                  # browsertests (Playwright)
```

De gouden baseline staat naast het werkboek, niet in de repo. Ontbreekt hij,
dan faalt `test_baseline_exists`; aanmaken met `python tests/generate_baseline.py`.

De browsertests starten een echte app en bedienen die met Chromium. Ze hebben
een echt werkboek nodig via `SOP_GOLDEN_FIXTURE` en skippen zonder. Installatie,
fixtures en foutzoeken staan in [docs/browsertests.md](docs/browsertests.md).

## Documentatie

- [docs/ontwikkelhandleiding.md](docs/ontwikkelhandleiding.md) — architectuur,
  contracten (`PlanningRow`, `LineType`), het state-model met de zes
  syncpunten en het wijzigingsprotocol. Lezen vóór je code aanraakt.
- [docs/validatiestrategie.md](docs/validatiestrategie.md) — handmatige
  validatie tegen een ground truth (klant-Excel, handberekening,
  invarianten), classificatie van afwijkingen, vrijgaveregels en formulieren.
- `tools/ground_truth_diff.py` — vergelijkt een app-export cel-voor-cel met het
  klant-Excel en schrijft een rapport (Markdown/xlsx).
- [docs/validatie/Apex_Rainier_Validation_Test_Workbook.xlsx](docs/validatie/Apex_Rainier_Validation_Test_Workbook.xlsx)
  — het Engelse test- en validatiewerkboek voor de handmatige rondes (ground-truth-
  register, rekenketens, invarianten, gespiegelde edits, functionele checks A–I,
  engine-checks, human tests A–K, afwijkingenregister, sign-off). Bevat geen
  klantdata; bewust opgenomen ondanks de `*.xlsx`-regel in `.gitignore`.
- [docs/checklist-manuele-validatie.md](docs/checklist-manuele-validatie.md),
  [docs/validatielijst-fase3.md](docs/validatielijst-fase3.md),
  [docs/browsertests.md](docs/browsertests.md) — functionele checklist,
  geautomatiseerde dekking en browsertests.

## Site-uitgaven

Winterswijk (NLK1) en Ankerkade (NLU1) zijn aparte repo's (`SOP-WSK`,
`SOP-ANK`) met dezelfde rekenkern; alleen huisstijl, poort, data-map en de
zichtbare tabbladen verschillen. Wijzig rekenlogica hier en synchroniseer
daarna naar de sites.

## Bewust niet meegenomen

- testbestanden en test-output
- build-, dist- en exe-bestanden
- zip releases
- oude uploads en exports
- audit-, debug- en clientrapporten
- Python cachebestanden
