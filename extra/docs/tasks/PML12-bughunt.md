# PML12 Bughunt

## Gerapporteerde symptomen

1. **Samenvatting delta verdwijnt**: Als je een machinewaarde aanpast in sessie 1, een andere in sessie 2, en dan reset — verdwijnt de samenvatting delta van sessie 1 ook.
2. **PML12 toont altijd 123.3% -16.7pp**: Terwijl het 140% zou moeten zijn.

---

## Architectuur die relevant is

### Server-side state (per sessie)
- `sess['reset_baseline']['machines']` — snapshot van OEE/availability op het moment van eerste edit of Calculate
- `sess['machine_overrides']` — huidige afwijkingen t.o.v. baseline
- `sess['machine_undo']` / `sess['machine_redo']` — undo/redo stacks

### Client-side state (JS, verdwijnt bij page reload)
- `state.machineDeltaSummary` — actieve delta samenvatting
- `state.machineDeltaSummaries` — per sessie-ID opgeslagen delta samenvattingen (in-memory alleen!)

---

## Bug 1: Samenvatting delta verdwijnt

### Mechanisme

De delta samenvatting werkt volledig client-side:

```javascript
// index.html:3776-3793
function _rememberMachineDeltaSummaryForSession(sessionId = state.activeSessionId) {
    if (!sessionId) return;
    if (state.machineDeltaSummary) state.machineDeltaSummaries[sessionId] = state.machineDeltaSummary;
    else delete state.machineDeltaSummaries[sessionId];  // ← VERWIJDERT de entry!
}
function _setMachineDeltaSummary(summary) {
    state.machineDeltaSummary = summary || null;
    _rememberMachineDeltaSummaryForSession();
    renderMachineDeltaSummary();
}
```

### Probleem na Reset

Na reset roept de JS `_buildMachineDeltaSummary(before, out, [resetEvent])` aan (index.html:7152). Die functie:
1. Berekent cascadeRows = diff(voor-reset, na-reset) → dit zijn de NEGATIEVE deltas van alle vorige edits
2. Mergt met de history: alle vorige events + reset event
3. Na merging: alle cascadeRows heffen elkaar op → resultaat ≈ leeg
4. Roept `_setMachineDeltaSummary({ history, directChanges: ['Alle machines/reset'], cascadeRows: [], ... })` aan
5. Die roept `_rememberMachineDeltaSummaryForSession()` aan → slaat dit lege resultaat op voor de HUIDIGE sessie

### Verdachte code paden die de delta van sessie 1 kunnen wissen

**`_setMachineDeltaSummary(null)` wordt aangeroepen op 4 plaatsen:**
- index.html:2234 — bij start van `calculate()`
- index.html:5261 — bij laden van extract files
- index.html:7610 — bij laden van raw data
- index.html:7879 — bij laden van extract files
- index.html:7950 — in `clearActiveSessionUi()`

**Bij `_setMachineDeltaSummary(null)` terwijl `state.activeSessionId = sessie1`:**
→ `_rememberMachineDeltaSummaryForSession()` doet `delete state.machineDeltaSummaries[sessie1]` → delta van sessie 1 weg.

### Meest waarschijnlijke oorzaak Bug 1

`_buildMachineDeltaSummary` na reset produceert een summary waarbij de cumulatieve delta ≈ 0 is (omdat de reset alle vorige changes ongedaan maakt). De history bevat nog wel de events, maar alle cascadeRows zijn geneutraliseerd. De samenvatting is dus "leeg" qua data maar niet `null`.

**Als sessie 1 vervolgens een Calculate uitvoert** (of als de page reload):  
→ `_setMachineDeltaSummary(null)` wist `machineDeltaSummaries[sess1]`.

**Als sessie 2 reset terwijl de JS sessie 2 actief heeft**, dan wordt de lege samenvatting voor sessie 2 opgeslagen. Bij terugswitch naar sessie 1 wordt `machineDeltaSummaries[sess1]` hersteld. Dit zou correct moeten werken — **tenzij** er een Calculate of file load tussenin zit die `_setMachineDeltaSummary(null)` aanroept met `state.activeSessionId = sess1`.

### Nog te onderzoeken

- Wordt `calculate()` automatisch aangeroepen bij sessie-switch als de engine nog niet geladen is?  
  → Ja! In `switch_session` (sessions.py:200-214) wordt de engine synchroon herbouwd als hij er nog niet is. Dit triggert geen client-side calculate(), maar de warmup thread doet `_build_and_install_session_engine` die geen JS aanraakt.
- Is er een pad waarbij de sessie-switch client-side `calculate()` aanroept?  
  → index.html:8096: `switchSession(sessionId)` wordt opnieuw aangeroepen bij `restore_status === 'warming'`. Dit roept geen `calculate()` aan.

**Hypothese**: De delta verdwijnt als na de sessie-switch naar sessie 1, de `loadResults()` call (index.html:8102) iets aanroept dat `_setMachineDeltaSummary` wist. `loadResults` doet dit NIET direct, maar `loadCapacityData()` → `loadMachinesData()` → `renderMachineDeltaSummary()` herschrijft alleen de DOM, niet state. Dus dit pad is schoon.

**Alternatieve hypothese**: De delta verdwijnt pas na een page reload (F5), omdat `state.machineDeltaSummaries = {}` bij elke page load gereset wordt. De server heeft `machine_overrides` wél persistent, maar de JS delta history is puur in-memory en wordt nooit naar de server gestuurd of hersteld. Na reload is de history dus weg, en kan de delta summary niet worden hersteld.

→ **Dit is de meest waarschijnlijke root cause van bug 1:** `machineDeltaSummaries` wordt niet gepersisteert (niet in localStorage, niet op de server). Na elke page reload of tab-refresh is de history weg.

---

## Bug 2: PML12 altijd 123.3% -16.7pp (zou 140% moeten zijn)

### Wat het display betekent

De `-16.7pp` chip in de OEE-tabel komt uit `edit_meta` (machines.py:48-98). Die vergelijkt de HUIDIGE machinewaarden met `sess['reset_baseline']['machines']`. Als PML12's baseline ≠ huidige waarde, verschijnt de chip.

Kandidaten:
- `edit_meta['oee']`: baseline OEE = 1.40 (140%), huidig = 1.233 (123.3%) → delta = -16.7pp
- `edit_meta['availability']`: baseline availability gemiddeld = 140%, huidig = 123.3%

### Waar komt 140% baseline vandaan?

`reset_baseline` wordt gezet door:
1. `install_clean_engine_baseline` bij Calculate — snapshot van de SCHONE engine → OEE/availability rechtstreeks uit Excel
2. `ensure_reset_baseline` bij eerste machine-edit — snapshot van de engine VOOR de edit

Als PML12 in de Excel een OEE van 1.40 heeft, dan is 140% de baseline. Maar huidig is 123.3%.

**Vraag**: Wordt PML12's OEE ergens op 123.3% gezet zonder expliciete gebruikersactie?

### Multi-sessie contaminatie hypothese

`machine_overrides` worden opgeslagen in `sessions_store.json` en gereplayd via `replay_pending_edits` (replay.py:75-76):
```python
if machine_overrides_present and apply_machine_overrides(engine, sess.get('machine_overrides') or {}):
    recalculate_capacity_and_values(engine, sess)
```

Als sessie 1's `machine_overrides` door een bug ook PML12 bevat (bijv. omdat de undo-stack of override-tracking iets verkeerd koppelt), dan wordt PML12 altijd op 123.3% gezet bij replay.

### `machine_overrides_from_engine` als bron

`machine_overrides_from_engine` (state_snapshot.py:152-199) vergelijkt de engine met de baseline. Als de baseline voor PML12 incorrectly opgeslagen is (bijv. na een sessie-switch waarbij `install_clean_engine_baseline` de VERKEERDE baseline opslaat), dan detecteert de functie een "override" die er eigenlijk niet is.

**Verdachte code in `switch_session` (sessions.py:216-226):**
```python
if sess.get('engine') is not None and (
    sess.get('reset_baseline') is None or snapshot_has_manual_edits(sess.get('reset_baseline'))
):
    clean_engine = build_clean_engine_for_session(sess)
    if clean_engine is not None:
        install_clean_engine_baseline(sess, clean_engine, clear_machine_overrides=False)
```

Als `snapshot_has_manual_edits(sess.reset_baseline)` True is (bijv. sessie 1 heeft demand edits), dan wordt bij ELKE sessie-switch naar sessie 1 een nieuwe `clean_engine` gebouwd en als baseline geïnstalleerd. Die clean engine gebruikt `get_session_config_overrides(sess, global_config)`. `global_config` is op dat moment gesynchroniseerd met de VORIGE sessie (sessie 2). Als er een config-override is die PML12's gedrag beïnvloedt... maar dit pad raakt alleen `valuation_params` en `purchased_and_produced`, niet machines.

### Bekende Excel bug (uit test E SS notities)

> "die 1707% komt uit gekende excel bug, laatste 2 rijen van util rate zijn x100"

Dit verwijst naar de `UTILIZATION_RATE` rijen in de capacity engine. Als PML12 toevallig een van de "laatste 2" machines is, kunnen zijn utilization-waarden x100 te groot zijn (opgeslagen als percentage i.p.v. fractie).

In `machines.py:100-101`:
```python
util_rows = current_engine.results.get(LineType.UTILIZATION_RATE.value, [])
util_by_machine = {row.material_name: row.values for row in util_rows}
```

Dan op regel 163:
```python
util_p = {period: round(util_by_machine.get(mc_code, {}).get(period, 0.0) * 100, 1) for period in periods}
```

Als PML12's `util_rate` al als percentage is opgeslagen (bijv. 1.233 i.p.v. 0.01233), dan geeft `* 100` → 123.3%. Maar als het correct een fractie 1.233 is (= 123.3% utilization), dan is `* 100` = 12330% — wat ook fout is.

**Wat klopt**: de `_calculate_utilization_rate` in capacity_engine.py slaat altijd op als FRACTIONS (0.0-2.0 range):
```python
rate_data[period] = used_hours / available if available > 0 else 0.0
```
En de display doet `* 100` → %

Dus 123.3% util is correct ALS `used_hours / available = 1.233`. Dat betekent PML12 heeft 23.3% overcapaciteit, wat legitiem kan zijn.

**Maar dan is de -16.7pp geen utilization delta** — die moet van OEE of availability komen.

### Meest waarschijnlijke oorzaak Bug 2

PML12 heeft in de Excel een OEE of availability die in sessie 1 (of bij replay van sessie 1's machine_overrides) wordt gewijzigd van 140% naar 123.3%. Dit lek zit waarschijnlijk in:

1. **Verkeerde `machine_overrides` in sessie 1**: sessie 1's `machine_overrides` in `sessions_store.json` bevat een entry voor PML12 met een andere waarde dan de baseline. Dit wordt gereplayed bij elke engine rebuild.
2. **Baseline overschreven na sessie-switch**: de `reset_baseline.machines` voor PML12 wordt onbedoeld overschreven, waarna `machine_overrides_from_engine` een "delta" detecteert die er eigenlijk niet is.

---

## Te doen bij vervolg

1. **Check `sessions_store.json`** in `%LOCALAPPDATA%\SOPPlanningEngine\`: bevat sessie 1's `machine_overrides` een entry voor PML12? Zo ja, wat is de waarde?
2. **Check de baseline**: wat is `sess['reset_baseline']['machines']['PML12']` (OEE en availability)?
3. **Reproduceer stap voor stap**:
   - Fresh start (geen sessies)
   - Laad file → Calculate → check PML12 (baseline = ??, geen delta chip verwacht)
   - Edit machine X (niet PML12) in sessie 1 → check PML12 (geen delta chip verwacht)
   - Wissel naar sessie 2 → check PML12 (geen delta chip verwacht)
   - Edit machine Y in sessie 2 → check PML12 (geen delta chip verwacht)
   - Reset sessie 2 → check PML12 (geen delta chip verwacht)
   - Wissel terug naar sessie 1 → **hier verschijnt de chip?**
4. **Samenvatting delta**: check of de chip verschijnt na page reload (F5) — dan is het een puur client-side geheugen-probleem (machineDeltaSummaries wordt niet gepersisteert).

---

## Relevante bestanden

| Bestand | Relevante regels | Onderwerp |
|---------|-----------------|-----------|
| `ui/routes/machines.py` | 29-98, 356-381 | edit_meta berekening, reset endpoint |
| `ui/state_snapshot.py` | 110-149, 152-199, 290-294 | snapshot, machine_overrides_from_engine, ensure_reset_baseline |
| `ui/routes/sessions.py` | 183-231 | switch_session (verdachte baseline-rebuild) |
| `ui/engine_rebuild.py` | 75-85 | install_clean_engine_baseline |
| `ui/replay.py` | 32-79 | replay_pending_edits incl. machine overrides |
| `ui/templates/index.html` | 3776-3793, 7130-7165, 8049-8122 | JS delta summary mechanisme, reset handler, switchSession |
