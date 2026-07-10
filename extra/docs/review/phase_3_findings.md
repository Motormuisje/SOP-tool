# Phase 3 — State-Sync Wiring Review

Code review of Phase 3 changes that thread `inventory_overrides` and
`capacity_overrides` through the six state-sync points. Files in scope:
`ui/app.py`, `ui/state_snapshot.py`, `ui/replay.py`, `ui/session_store.py`,
`ui/engine_rebuild.py`, plus the small docstring update in
`ui/config_store.py`.

### 1. `install_clean_engine_baseline` clears two stores via assignment, not deepcopy
- **Severity**: low
- **Location**: `ui/engine_rebuild.py:75-92`.
- **Observation**: The new lines `sess['inventory_overrides'] = {}` and
  `sess['capacity_overrides'] = {}` create fresh empty dicts. That is fine
  for a clean baseline, but note the asymmetry with `machine_overrides`:
  `clear_machine_overrides=False` is sometimes passed (e.g.
  `_build_and_install_session_engine` and `_autorun_sessions` to preserve
  user machine tweaks across a session warmup). The new override stores
  are unconditionally cleared regardless of `clear_machine_overrides`.
- **Suggestion**: Confirm this is intentional. Replay re-populates them
  from `pending_edits` immediately after the install, so the net effect
  is correct on the warmup path. But if a future code path calls
  `install_clean_engine_baseline` *without* a follow-up replay, the user's
  L4/L7/L9/L11/L12 edits would be lost. Consider gating with a similar
  flag or moving the clear into `replay_pending_edits` only.
- **Action**: defer (current callers all replay after install).

### 2. Snapshot path is via `install_clean_engine_baseline`, not
`snapshot_engine_state`
- **Severity**: low
- **Location**: `ui/state_snapshot.py:110-149` vs.
  `ui/engine_rebuild.py:84-92`.
- **Observation**: `snapshot_engine_state` does not capture
  `inventory_overrides` or `capacity_overrides` because those live on
  `sess`, not on `engine`. Reset is implemented as
  `restore_engine_state` (engine state) + explicit `sess['pending_edits']
  = {}` + `sess['value_aux_overrides'] = {}` in `routes/edits.py:369-374`,
  followed by `install_clean_engine_baseline` which now also clears the
  two new stores. The path works, but the policy ("baseline = empty edit
  state") is split across two modules.
- **Suggestion**: Document in `state_snapshot.py` that the override
  stores are intentionally not part of the engine snapshot — they are
  reset separately by `install_clean_engine_baseline`.
- **Action**: defer (cosmetic).

### 3. `routes/edits.py` reset_edits doesn't explicitly clear the new
stores
- **Severity**: low
- **Location**: `ui/routes/edits.py:348-374`.
- **Observation**: `reset_edits` clears `pending_edits` and
  `value_aux_overrides` in-line, then calls
  `install_clean_engine_baseline` which now also clears
  `inventory_overrides`/`capacity_overrides`. So the reset is correct,
  but the route-level code reads asymmetrically: pending_edits is cleared
  twice (once explicitly, once implicitly via baseline-install of an
  empty dict — wait, no, `install_clean_engine_baseline` does NOT touch
  pending_edits; only the route does). The new stores are cleared only
  by the baseline-install side-effect.
- **Suggestion**: Either make `reset_edits` clear all four stores
  explicitly for symmetry, or move all four into
  `install_clean_engine_baseline`. Pick one source of truth.
- **Action**: defer.

### 4. `sync_global_config_from_engine` "deliberately not synced" comment
is good but easy to miss
- **Severity**: low
- **Location**: `ui/config_store.py:27-37`.
- **Observation**: The new docstring spells out that
  `inventory_overrides`/`capacity_overrides` are per-session and not
  copied to `_global_config`. Future contributors adding new
  per-session edit stores need to remember the same rule — it is not
  enforced anywhere.
- **Suggestion**: Add a unit test that asserts these two keys never
  appear in `global_config` after `sync_global_config_from_engine`.
- **Action**: defer.

### 5. Replay pre-clear is in the wrong order vs. early-return
- **Severity**: med
- **Location**: `ui/replay.py:38-58`.
- **Observation**: The pre-clear `sess['inventory_overrides'] = {}` /
  `sess['capacity_overrides'] = {}` runs unconditionally at function
  entry, including on the `if not pending: return` short-circuit path
  (when the early return only handles `value_aux_overrides` and
  `machine_overrides`). That is the correct behaviour — an empty
  `pending_edits` means no L4/L7/L9/L11/L12 edits, so the stores
  *should* be empty. But it is subtle: a future contributor who reads
  the early-return branch in isolation might wonder why those two
  stores are wiped even when "we are not replaying anything".
- **Suggestion**: Add a one-line comment on the early-return that the
  pre-clear above already covered the no-edits case.
- **Action**: fix-now (trivial doc change).

### 6. `session_store.load_sessions_from_disk` uses `or {}` which collapses
empty dicts back to {} (no-op) but also collapses None
- **Severity**: low
- **Location**: `ui/session_store.py:91-94`.
- **Observation**: `data.get('inventory_overrides') or {}` returns `{}`
  for both missing-key and empty-dict — fine. But if a future field
  with a meaningful falsy value (e.g. `0`, `False`) is added the same
  way, it would be silently coerced. Pattern is safe today.
- **Suggestion**: Consider `data.get('inventory_overrides', {})` for
  semantic clarity ("default if missing") and rely on save-side
  invariant that the value is always a dict.
- **Action**: defer (current code is robust against legacy nulls).

### 7. `save_sessions_to_disk` reads from `sess` directly, not via a
"current state" helper
- **Severity**: low
- **Location**: `ui/session_store.py:46-57`.
- **Observation**: `pending_edits`, `value_aux_overrides`,
  `inventory_overrides`, and `capacity_overrides` are all serialized
  with `sess.get(...)`. This is correct because `apply_volume_change`
  writes them on every edit. But `machine_overrides` uses
  `machine_overrides_from_engine(sess, engine)` because the live engine
  state can drift from `sess['machine_overrides']` between edits. If a
  future bug path lets `inventory_overrides` drift from engine-applied
  state, save-time will silently capture the stale value.
- **Suggestion**: For now, document that the contract is "write-through
  from `apply_volume_change`". Add a debug-build assertion that
  cross-checks the override store against the engine after each
  recalc.
- **Action**: defer.

### 8. Replay pre-clear uses assignment, not `dict.clear()`
- **Severity**: low
- **Location**: `ui/replay.py:42-43`.
- **Observation**: We rebind `sess['inventory_overrides']` and
  `sess['capacity_overrides']` to fresh dicts. If any other code path
  holds a stored reference to the *old* dict (e.g. a closure captured
  the dict before replay started), it will keep mutating the orphaned
  object. Quick scan of `ui/volume_change.py` shows all reads use
  `sess.get('capacity_overrides', {})` at call time — no captured
  references — so this is safe today.
- **Suggestion**: Note the invariant in the override store contract
  comment in `volume_change.py`'s module docstring.
- **Action**: defer.

### 9. No symmetric override for the "scenarios" load path
- **Severity**: med
- **Location**: `ui/routes/scenarios.py:197-...` (not modified in
  Phase 3); compare with replay flow.
- **Observation**: Scenario load paths use
  `_build_pending_edits_from_results_snapshot` to derive
  `pending_edits` from a saved scenario, then go through the same
  replay path. Phase 3's pre-clear in `replay_pending_edits` ensures the
  override stores are empty before scenario-replay runs, so this works
  out. But there is no test covering "load a Phase-2-era scenario that
  contains L4 starting-stock edits". Such a scenario would have the
  edits in `pending_edits` (via the snapshot derivation) but no
  matching `inventory_overrides` entry until replay finishes.
- **Suggestion**: Add a Phase 3 integration test exercising
  scenarios save → load → assert L4/L7 round-trip.
- **Action**: defer (broader scenarios coverage).

### 10. `install_clean_engine_baseline` signature unchanged but semantics
expanded
- **Severity**: low
- **Location**: `ui/engine_rebuild.py:75-92`.
- **Observation**: We added behavior (clearing two new fields) without
  changing the function signature or name. The `clear_machine_overrides`
  flag now governs only `machine_overrides`; the two new stores are
  always cleared. A reader of the call sites (e.g.
  `_build_and_install_session_engine` passing
  `clear_machine_overrides=False`) might wrongly assume edit stores in
  general are preserved.
- **Suggestion**: Rename to `install_clean_engine_baseline(...,
  clear_volume_edit_stores: bool = True)` and gate all three (or four)
  override stores together; or document the asymmetry in the
  docstring.
- **Action**: fix-now (small doc update).

## Summary

The six sync points are now wired:

1. Snapshot for reset — handled via `install_clean_engine_baseline`
   side-effect (cleared, not snapshotted; replay restores).
2. `_global_config` — deliberately not synced (per-session). Documented.
3. Engine-rebuild apply — handled via Phase 2 replay pathway
   (`apply_volume_change` re-populates).
4. Replay pre-clear — added in `replay.py`.
5. Recalc on change — Phase 2 already wired.
6. Persist + restore — added in `session_store.py` (save + load).

Strongest follow-up is finding #1/#10: the asymmetry between
`clear_machine_overrides` (flag-gated) and the new clears
(unconditional). Today's call sites all replay after install, so the
behaviour is correct, but a future caller could trip on it.
