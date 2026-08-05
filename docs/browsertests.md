# Browsertests (Playwright) — hoe je ze draait

De browsertests starten een **echte** app-instantie, uploaden een echt werkboek,
laten de planning doorrekenen en bedienen daarna de UI met een echte Chromium.
Er wordt niets gemockt. Dat is traag (de volledige suite duurt ~5–12 minuten)
maar het is de enige laag die aantoont dat de cijfers die de klant op zijn
scherm ziet kloppen met wat de engines berekend hebben.

---

## 1. Eenmalige installatie

```powershell
pip install -r requirements.txt          # bevat playwright + pytest-playwright
python -m playwright install chromium    # haalt de browser zelf op (~120 MB)
```

`python -m playwright install chromium` is een aparte stap: pip installeert de
Python-bindings, niet de browser. Sla je die over, dan falen álle browsertests
met `Executable doesn't exist at ...\chrome.exe`.

## 2. De gouden fixture aanwijzen

Elke browsertest heeft een echt MS_RECONC-werkboek nodig. Dat is **klantdata en
staat dus niet in de repo** (`.xlsm` staat in `.gitignore`). Je wijst het aan met
de omgevingsvariabele `SOP_GOLDEN_FIXTURE`:

```powershell
$env:SOP_GOLDEN_FIXTURE = "C:\Users\<jij>\AppData\Local\SOPPlanningEngine\uploads\03_2025_December_SOP consolidation_MS_RECONC.xlsm"
```

```bash
# Git Bash
export SOP_GOLDEN_FIXTURE="/c/Users/<jij>/AppData/Local/SOPPlanningEngine/uploads/03_2025_December_SOP consolidation_MS_RECONC.xlsm"
```

Is de variabele niet gezet of bestaat het bestand niet, dan **skippen** alle
browsertests met een duidelijke melding. Ze falen niet — zo blijft de suite
bruikbaar op een machine zonder klantdata.

> Het werkboek moet de planningmaand **2025-12** kunnen dragen: de fixture
> uploadt met `planning_month=2025-12`, 11 maanden actuals en 12 maanden
> forecast. Een ander werkboek werkt, maar dan kloppen de vastgepinde getallen
> in sommige tests niet meer.

## 3. Draaien

```powershell
# alles
python -m pytest tests/browser -q

# één module
python -m pytest tests/browser/test_pw_planning.py -q

# één test
python -m pytest tests/browser/test_pw_planning.py::test_cel_bewerken_zet_dirty_balk -q

# zichtbare browser meekijken (debuggen)
python -m pytest tests/browser/test_pw_planning.py --headed --slowmo 300 -q

# eerste fout stopt de run, met volledige traceback
python -m pytest tests/browser -x --tb=long
```

Nuttige vlaggen:

| Vlag | Waarvoor |
|---|---|
| `--headed` | browser zichtbaar; zonder deze vlag draait Chromium headless |
| `--slowmo 300` | 300 ms tussen handelingen, zodat je het kunt volgen |
| `--video on` / `--screenshot only-on-failure` | artefacten in `test-results/` |
| `-k dashboard` | selecteer op naam |
| `--tb=long` | volledige traceback in plaats van de korte |

**Over parallel draaien:** `pytest-xdist` staat niet in `requirements.txt` en is
hier niet geïnstalleerd, dus `-n auto` werkt niet zonder `pip install
pytest-xdist`. Het kán wel: elke worker start zijn eigen server op een eigen
vrije poort en eigen datamap. Maar elke worker doet ook een volledige upload +
doorrekening (~40 s), en die CPU-piek maakt de trage tests schokkerig. Voor een
betrouwbare uitslag: serieel draaien.

De volgorde ligt vast (`pytest-randomly` is niet geïnstalleerd), dus twee runs
achter elkaar draaien dezelfde tests in dezelfde volgorde. Dat betekent ook dat
volgorde-afhankelijkheid tússen modules niet vanzelf aan het licht komt — vandaar
de `own_server`-regel hieronder.

## 4. Wat de fixtures voor je doen

Alles staat in [tests/browser/conftest.py](../tests/browser/conftest.py).

| Fixture | Scope | Wat je krijgt |
|---|---|---|
| `server` | session | één draaiende app voor de hele run: `{base_url, session_id, expected_periods, startup_seconds, app_data_dir}` |
| `own_server` | module | een **verse** app voor één testmodule |
| `browser_page` | function | een Playwright `page` die al op de app staat, plus `page.js_errors`, `page.console_errors` en `page.server` |
| `golden_fixture_path` | session | het pad uit `SOP_GOLDEN_FIXTURE`, skipt als het ontbreekt |

De opstartroutine (`_running_server`) doet per server:

1. een tijdelijke datamap aanmaken (`SOP_APP_DATA_DIR`) — **nooit de echte
   datamap van de gebruiker**, dus je sessies raken niet vervuild;
2. `main.py` starten op een vrije poort met `SOP_DISABLE_AUTORUN=1` en
   `SOP_NO_BROWSER=1`;
3. wachten tot `/` een 200 geeft (max 30 s, faalt boven de 60 s);
4. het werkboek uploaden via `/api/upload` en doorrekenen via `/api/calculate`;
5. na afloop het proces afsluiten en de tijdelijke map opruimen.

### Wanneer `server` en wanneer `own_server`

Gebruik `browser_page` (en dus de gedeelde `server`) voor alles wat **leest**:
een tabblad openen, cijfers vergelijken, filteren, sorteren.

Gebruik `own_server` zodra een test **blijvende toestand** achterlaat: sessies
aanmaken of hernoemen, masterdata opslaan, scenario's laden, instanties
dupliceren. Anders bepaalt de volgorde van de suite de uitkomst. Dat is hier
één keer echt misgegaan — een `xfail` die XPASS'te omdat een eerdere test de
gedeelde server al in de juiste toestand had gezet.

### JS-fouten

`browser_page` verzamelt console-fouten. `page.js_errors` filtert
`Failed to load resource:` eruit (dat is het ontbrekende favicon en soms een
afgebroken fetch bij het afsluiten). **Elke test hoort af te sluiten met**

```python
assert page.js_errors == []
```

Dat vangt stille regressies die geen enkele assert op de UI zou zien.

## 5. Wat er gedekt wordt

De suite is in twee lagen gegroeid. De oudere modules (`test_charts.py`,
`test_edits.py`, `test_machines.py`, …) dekken de functies waarmee de tool
begon. De `test_pw_*`-modules zijn later toegevoegd voor de gebieden die daarin
dun of onbedekt waren.

### De latere modules

| Module | Gebied | Kern van wat er wordt vastgelegd |
|---|---|---|
| `test_pw_dashboard.py` | Dashboard | KPI-tegels tegen een onafhankelijk opgehaalde `/api/dashboard`; Chart.js-reeksen getalsmatig gelijk aan de API; de 12M-overzichtstabel reproduceert de VBA-aggregatie (inventariswaarde is een **gemiddelde** inclusief 'Starting stock', ROCE is EBIT-som ÷ gemiddeld kapitaal, niet het gemiddelde van maand-ROCE's); `dashboardDirty` stelt renderen uit tot het tabblad opengaat; lege en kapotte payloads |
| `test_pw_planning.py` | Planningtabel | periodekolommen exact gelijk aan `expected_periods`; zoeken/filteren met `#rowCount`; lege-doorsnede-uitweg; sticky header tijdens scrollen; sorteren op 'Start'; starting-stock-edit via de sentinelperiode; undo én redo herstellen het hele materiaalblok; niet-numerieke invoer wordt geweigerd; cascade Line 01 → Line 03 |
| `test_pw_values_inventory.py` | Values + Inventory | alle 20 P&L-regels op volle precisie (`data-fin-full`) tegen `/api/value_results`, inclusief de optelrelaties Gross Margin en EBITDA; KPI-tegels zijn een **maandgemiddelde** (de tolerantie is strak genoeg dat een som er niet doorheen komt); aux-edit cascadeert naar rij, consolidatie en KPI; inventory-statusindeling |
| `test_pw_masterdata.py` | Config → Masterdata | elke datasetknop opent zijn eigen grid met het juiste aantal rijen; filteren op sleutel én celinhoud; een bewerking bumpt de versie met exact 1 en laat de overige rijen byte-identiek; weigering langs beide paden (client-side alert én server-side 400); 409 bij een verouderde versie; "+ rij toevoegen" bij de F2-CF-datasets met select-, csv- en map-kolommen |
| `test_pw_sessies_scenarios.py` | Instanties + scenario's | hernoemen overleeft F5 én staat op schijf; dupliceren geeft cel-voor-cel dezelfde cijfers; wisselen isoleert edits; scenario laden herstelt exact en ruimt latere edits op; vergelijken; tegenproef met 0 verschillen; een scenario van een andere instantie geeft 403 |
| `test_pw_navigatie_mom.py` | Navigatie + MoM | elk tabblad opent met precies één zichtbaar paneel en één actieve knop; het actieve tabblad overleeft een herlaad; een onbruikbare tabvoorkeur valt terug op dashboard; `setBusy` telt geneste taken zonder negatieve diepte |
| `test_pw_bugfixes.py` | Regressie | de vier bugs uit §5a — elk van deze tests faalt aantoonbaar op de code van vóór de fix |

### 5a. Bugs die deze suite heeft gevonden

Deze staan hier omdat ze laten zien wát dit soort tests oplevert dat een
unittest niet oplevert — alle vier zaten in de koppeling tussen UI en engine.

1. **Lead time 0 werd stilzwijgend 1.** `collectMasterDataset` deed
   `if (lead > 0)` bij het opslaan van de inkoopdataset. De loader schrijft 0
   wél weg, dus die materialen verdwenen bij elke opslag uit `lead_times`,
   waarna `get_lead_time()` terugviel op de VBA-default 1 — bedoeld voor
   materialen die *niet in de Purchase sheet staan*. In het gouden werkboek
   trof dit **12 van de 28** materialen. Het inkoopplan schoof een maand op en
   niets in het scherm liet dat zien. Openen en op Opslaan drukken was genoeg.
2. **Het tabblad Capaciteit & FTE werd niet onthouden.** `_VALID_TABS` miste
   `'fte'`, dus na een herlaad viel de gebruiker terug op het dashboard.
3. **`setBusy` liet een verweesde `show` achter.** De `requestAnimationFrame`
   uit `setBusy(true)` werd door `setBusy(false)` niet geannuleerd. Bij een taak
   binnen één frame vuurde hij ná het verbergen, en een onzichtbare overlay met
   `pointer-events: auto` ving ~140 ms lang alle kliks op.
4. **`undefined` glipte langs een `=== null`-controle.** `_masterCellValue`
   geeft `undefined` terug als het invoerveld ontbreekt; dat werd verderop
   `Math.round(undefined)` = NaN, kwam als JSON-`null` bij de server aan en
   blies daar `int(None)` op. Bug 1 maskeerde dit door zulke rijen te laten
   vallen; hij kwam pas boven toen die filter weg was.

> Nummer 4 is een les op zichzelf: het weghalen van een te ruime filter legt
> bloot wat die filter onbedoeld afdekte. Een fix in dit gebied is pas af als de
> suite er daarna nog een keer overheen is gegaan.

## 6. Als een test faalt

1. **Draai hem alleen** (`-k <naam>`). Slaagt hij dan wel, dan is er
   volgorde-afhankelijkheid: de test hoort aan `own_server`.
2. **Kijk mee** met `--headed --slowmo 400`.
3. **Lees het serverlog.** Het staat in de tijdelijke datamap als
   `server.log`, maar die wordt na de run opgeruimd. Wil je hem houden, zet dan
   tijdelijk `ignore_errors=True` → `shutil.rmtree` uit in `conftest.py`, of
   plak het pad uit `server["app_data_dir"]` in een `print`.
4. **`Server did not return 200 within 30s`** betekent meestal dat `main.py`
   zelf niet start. Reproduceer met
   `SOP_DISABLE_AUTORUN=1 SOP_NO_BROWSER=1 python main.py` en lees de traceback.
5. **Timeout op een `wait_for_function`** is bijna altijd een échte regressie:
   de UI bereikt de verwachte toestand niet meer. Controleer eerst of het
   bijbehorende `/api/...`-antwoord nog klopt vóór je de test aanpast.

## 6b. Een test toevoegen

- Wacht op toestand, nooit op tijd. `page.wait_for_function(...)` of
  `expect(locator).to_be_visible()`; geen `time.sleep`.
- Assert op **getallen**, niet op "het element bestaat". Een test die alleen
  kijkt of een tabel rijen heeft, blijft groen terwijl de cijfers verkeerd zijn.
- Vergelijk waar mogelijk met het API-antwoord (`requests.get(base_url + "/api/...")`),
  zodat de test aantoont dat UI en engine hetzelfde zeggen.
- Zet in de docstring **waarom** de test bestaat: welk gedrag zou stukgaan.
- Draai een nieuwe test twee keer achter elkaar voor je hem opneemt.

## 7. Verhouding tot de andere testlagen

| Laag | Commando | Duur |
|---|---|---|
| Snelle unit-suite | `python -m pytest tests -q --ignore=tests/browser` | ~2 min |
| Gouden baseline | `python -m pytest tests/test_golden_pipeline.py -q` | ~5 s |
| Zelftest van de app | `python main.py --test` | ~1 min |
| Browsertests | `python -m pytest tests/browser -q` | ~7 min |

Voor een commit die rekenlogica raakt: alle vier. Voor een commit die alleen de
UI raakt: de snelle suite plus de browsermodules van het gewijzigde gebied.

> **`-m golden` selecteert niets.** `pytest.ini` declareert de marker wel, maar
> geen enkele test draagt hem — de vier gouden tests staan gewoon in
> `tests/test_golden_pipeline.py` en lopen mee in de snelle suite. Selecteer op
> bestandsnaam, niet op marker.

### De gouden baseline ontbreekt bij een verse checkout

`test_baseline_exists` faalt met *"Baseline not found at …"* zolang de baseline
niet is aangemaakt. Dat is opzet: de baseline is afgeleid van klantdata en staat
daarom **naast het werkboek** (`_fixture_dir()`), niet in de repo. Aanmaken:

```powershell
python tests/generate_baseline.py
```

Dat schrijft `golden_baseline.json` in dezelfde map als `SOP_GOLDEN_FIXTURE`.

Let op wat die baseline wel en niet bewijst: hij bevriest het gedrag op het
moment van genereren. Regenereer hem dus **nooit** om een rode test groen te
krijgen — lees eerst de diff. Wil je aantonen dat een wijziging de cijfers niet
heeft geraakt, genereer de baseline dan op de laatste commit en draai de tests
daarna op je werkboom.
