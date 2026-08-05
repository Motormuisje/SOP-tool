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

## Bewust niet meegenomen

- testbestanden en test-output
- build-, dist- en exe-bestanden
- zip releases
- oude uploads en exports
- audit-, debug- en clientrapporten
- Python cachebestanden
