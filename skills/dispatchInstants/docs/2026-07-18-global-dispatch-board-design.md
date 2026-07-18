# Global Dispatch Board — Design Spec

Updated: 2026-07-18 | Status: DURABLE (supersedes the per-base `dispatch/` board of
`2026-07-16-dispatch-instants-design.md` §2b/§5)

## 1. Problem

`pdispatch board` today requires a base-instant path and reads/writes the board under
that base's own `dispatch/` directory (`<base>/dispatch/*.json` + `<base>/dispatch/REGISTRY.md`).
This is asymmetric with `pdispatch pool`, whose state lives in a single machine-global,
well-known folder (`~/.claude-ws-pool/`) and whose `list` needs no path argument.

Goal: make the dispatch board work exactly like the pool — one machine-global store, and
`pdispatch board` with **no arguments** renders the whole fleet. Every existing consumer of
the dispatch metadata must keep working, and the two currently-active boards must be migrated
with zero interruption to the live worker sessions.

## 2. Consumers of the dispatch metadata (must all stay correct)

Only three scripts read or write dispatch records; each keys on `DISPATCH_DIR="$BASE/dispatch"`:

| Script | Role | Touch point |
|---|---|---|
| `dispatch-todo.sh` | writer | `RECORD="$DISPATCH_DIR/${TODO_ID}.json"` (line ~147) |
| `dispatch-adopt.sh` | writer | `RECORD="$DISPATCH_DIR/${TODO_ID}.json"` (line ~91) |
| `dispatch-board.sh` | reader | globs `$DISPATCH_DIR/*.json`, writes `$DISPATCH_DIR/REGISTRY.md` (line ~26) |

Not metadata, must NOT move: the `dispatch/` dir also holds hand-authored briefs and reports
(`MR0-brief.md`, `MR1-brief.md`, `MR0-REPORT.md`). A record's `brief` field points at such a
file by **absolute path**, so those files stay exactly where they are.

Independent, unaffected: the ws lease (`~/.claude-ws-pool/leases/<slot>/meta`) that the board
joins against by slot name via `wspool status`. The pool is untouched by this change.

## 3. On-disk contract (new)

Machine-global board store, parallel to the pool. `BOARD_DIR` overridable via env (default
`~/.claude-dispatch-board`) for hermetic tests — same pattern as `POOL_DIR`.

```
~/.claude-dispatch-board/
  records/
    <todo_id>.json      # IMMUTABLE dispatch record (moved here from <base>/dispatch/)
  REGISTRY.md           # DERIVED global dashboard, ALL bases (never hand-edited)
```

The record JSON schema is unchanged. It already carries `base_instant`, which becomes the
grouping key in the rendered board. `todo_id` already ends in a `-MMDDHHMM` stamp, so it is
unique enough to be the flat filename across all bases.

## 4. Behavior

### 4a. Writers (`dispatch-todo.sh`, `dispatch-adopt.sh`)

Single change each: resolve the record path against the global store instead of the base.

```sh
BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
RECORDS_DIR="$BOARD_DIR/records"
RECORD="$RECORDS_DIR/${TODO_ID}.json"
...
mkdir -p "$RECORDS_DIR"          # replaces `mkdir -p "$DISPATCH_DIR"`
```

Everything else is untouched: the JSON body (still writes `base_instant`), the rollback
(`RECORD_MADE` cleanup now removes the global path), and all brief handling. The scripts no
longer create or reference `<base>/dispatch/` at all.

### 4b. Reader (`dispatch-board.sh`) — no arguments

`dispatch-board.sh` accepts **zero positional arguments**. The old base-path form is fully
deprecated:

- Any argument → hard error, exit 2:
  `pdispatch board no longer takes a base path — records are global; run 'pdispatch board' with no arguments`

Record collection:

1. Read every `$RECORDS_DIR/*.json` (the authoritative global set).
2. **Fallback legacy read**, driven entirely by the global store: for each distinct
   `base_instant` value found among the global records, also glob that base's
   `<base_instant>/dispatch/*.json`; include any record whose `todo_id` is not already present
   (global wins on collision). This self-heals a stray/late legacy record without ever needing
   a base argument. (Consequence: a legacy base with zero migrated records is undiscoverable —
   acceptable; the migration in §6 moves every active record into the store.)

Rendering:

- Group rows **by `base_instant`**, one sub-header per base (`basename` of the base), followed
  by the existing per-TODO table columns (`TODO | Status | WS (lease) | Attach | Child instant`).
- One aggregate summary line across all bases (`▶ running · 🅿 parked · ✅ complete · ✖ abort`,
  plus `⚠ gone` when non-zero).
- Per-row derivation is unchanged: current child folder located by the dashless-instantName
  glob, status from folder state + `## Parked decision`, lease from `wspool status <slot>`.

Output — two renderings from one derivation:

- **`$BOARD_DIR/REGISTRY.md`**: the persisted MARKDOWN artifact (grouped tables, full absolute
  paths) — renders well in editors / on GitHub and is what other readers `cat`. Always the
  complete board; never a per-base `REGISTRY.md`.
- **stdout**: a terminal-friendly, stacked-block view — one `▌ <base>` header per group, then
  per TODO a status-tag line (`🅿 PARKED` / `▶ running` / `✅ done` / `✖ abort` / `⚠ gone`) + the
  title, and an indented detail line (`<slot> <LEASE> · <attach>`). ANSI colors are emitted only
  when stdout is a TTY (`[ -t 1 ]`), so piping/redirecting yields clean plain text. Long absolute
  paths are dropped from the terminal view (kept in the markdown file) to stay readable at ~80
  columns.

There is no filter argument, so there is no partial render that could truncate the markdown file.

### 4c. `pdispatch` umbrella

- Overview: `pdispatch board` — "global fleet dashboard (no path); records live in
  `~/.claude-dispatch-board/`". Remove the `<base-instant>` argument from the synopsis.
- End-to-end use case step 2: `pdispatch board <base-instant>` → `pdispatch board`.

## 5. Docs to update

- `docs/2026-07-16-dispatch-instants-design.md` §1 table (Instant registry → global board),
  §2b (replace per-base dispatch dir contract with the §3 store; note briefs/reports stay
  per-base), §5 (board is argument-less + global).
- `SKILL.md`: board usage + the on-disk map.
- Record the decision inline as **D-11: the dispatch board is machine-global
  (`~/.claude-dispatch-board/`), argument-less, and the old per-base-path form errors out.**

## 6. Migration — one atomic sweep (before any new dispatch)

Live sessions in ws3/ws4/ws5 never write records and only read briefs (which do not move), so
the sweep does not interrupt them. Order:

1. `mkdir -p ~/.claude-dispatch-board/records`.
2. Move the 3 live records into the store (they are immutable; a plain `mv`):
   - `…/07171903-07182132-complete-append-m1CatalogFactRevision/dispatch/m11AnsiFullExposureCompleteness-07182241.json`
   - `…/main-07182103-inflight-append-glutenMainAnsiReworkOrch/dispatch/glutenmainMr0RebaseOffM1RatifyDispositions-07182230.json`
   - `…/main-07182103-inflight-append-glutenMainAnsiReworkOrch/dispatch/glutenmainMr1AnsiErrorTranslatorFresh17Native-07182245.json`
3. Delete the 2 now-stale per-base `REGISTRY.md` files. Leave `MR*-brief.md` / `MR0-REPORT.md`.
4. Deploy all three script changes + `pdispatch`/docs in the same sweep so writers and reader
   agree on the store.
5. Regenerate: `pdispatch board`. Verify all 3 TODOs render, grouped by their two bases, with
   correct status and live lease state (ws4/ws5 LEASED to their TODOs; the completed/parked
   states derived from each child instant's folder + HANDOFF).

The fallback read (§4b) means that even if a `board` render races the move, nothing is lost.

## 7. Testing

Update `skills/dispatchInstants/tests/` to drive `BOARD_DIR` (alongside `POOL_DIR`), and cover:

- **no-arg global render**: two records under two different `base_instant`s → board groups both,
  writes `$BOARD_DIR/REGISTRY.md`, prints both groups.
- **deprecation**: `dispatch-board.sh <anything>` exits 2 with the deprecation message.
- **fallback legacy read**: one record in the global store plus a sibling legacy
  `<base>/dispatch/*.json` for that same base → both appear, deduped by `todo_id` (global wins
  on a `todo_id` collision).
- **writer store**: `dispatch-todo.sh --no-launch` writes its record to `$RECORDS_DIR/…json` and
  creates nothing under `<base>/dispatch/`; forced-failure rollback removes the global record.

Each test prints a final `PASS`/`FAIL` and sets its exit code, consistent with the existing
evidence scripts.
