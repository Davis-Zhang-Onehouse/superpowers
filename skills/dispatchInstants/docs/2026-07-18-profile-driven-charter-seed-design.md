# Profile-driven CHARTER + SEED for `dispatch-todo.sh`

Date: 2026-07-18
Status: DESIGN (approved) — ready for implementation plan
Affects: `skills/dispatchInstants/dispatch-todo.sh`, `tests/dispatch-smoke.sh`, `SKILL.md`, `bin/pdispatch`

## Problem

`dispatch-todo.sh` hardcodes the entire effort-specific payload for one effort
(Gluten-Velox ANSI gaps):

- the generated child **CHARTER body** — `dispatch-todo.sh:171-243` — carries the
  AC-1…AC-4 acceptance pipeline, the "ANSI DESIGN PHILOSOPHY" block, the
  Spark-Java=gold vs Gluten-Velox=actual framing, and the literal gold-source path
  `/home/ubuntu/davis_root/spark`;
- the interactive **SEED** kickoff prompt — `dispatch-todo.sh:313` — is a
  one-paragraph restatement of that same CHARTER.

Anyone reusing the toolkit for a different effort must edit the script itself (in
two places). The content that varies per effort should be **external input**, not
source code, so the toolkit is reusable checkout-and-go.

## Goal

Move the effort-specific CHARTER body and SEED out of the script into an
externally-supplied **profile**, keeping all orchestration unchanged, and shipping
today's ANSI content as a selectable profile (not a silent default).

Non-goals: changing orchestration (claim/duplicate/fork/record/launch/rollback);
templating the generic maintain-workspace stub files; changing `dispatch-adopt.sh`
(already parameterized via `--seed`).

## Design

### 1. Profile = a directory of templates

A **profile** is a directory holding the effort-specific templates:

```
profiles/ansi/
  charter.md     # template for the child CHARTER.md            (required)
  seed.txt       # template for the interactive kickoff prompt  (required)
  handoff.md     # OPTIONAL override for the child HANDOFF.md
```

Shipped profiles live in `skills/dispatchInstants/profiles/`. The directory name is
`profiles/` (matching the `--profile` flag), not `templates/`.

Today's inline ANSI CHARTER (`:171-243`) and SEED (`:313`) move **verbatim** into
`profiles/ansi/charter.md` and `profiles/ansi/seed.txt`, with their shell `${VAR}`
interpolations replaced by `{{VAR}}` placeholders (see §3). The hardcoded
`/home/ubuntu/davis_root/spark` gold path becomes ordinary text inside those files
— no script variable needed; a different effort's profile writes its own reference
(or none).

### 2. Selection & resolution (`--profile <name|path>`)

New flag `--profile <name|path>` on `dispatch-todo.sh`:

- A value containing `/` (or starting with `~` or `.`) is treated as a **path** to a
  profile directory.
- A bare word is treated as a **name**, resolved to `<skill>/profiles/<name>/`.

When `--profile` is absent, resolve in this order:

1. `DISPATCH_PROFILE` environment variable (name or path)
2. pool default file `~/.claude-ws-pool/profile` — a single line holding a name or
   path (honors `POOL_DIR` override for hermetic tests)

If **none** of flag / env / pool-default is set → **hard error** (no silent ANSI
fallback), with a message that lists the shipped profiles under `profiles/` and
shows how to set a default.

Validation: the resolved directory must exist and contain both `charter.md` and
`seed.txt`, else error.

### 3. Variable substitution

Templates use `{{VAR}}` placeholders. The script computes the same values it
interpolates today and substitutes them. Substitution is done with **python3**
(already a hard dependency of this toolkit) rather than sed, because the brief and
evidence values are multi-line and paths contain `/` and other regex-significant
characters — python3 string replacement avoids escaping hazards.

Available variables:

| Placeholder        | Value |
|--------------------|-------|
| `{{TITLE}}`        | `--title` |
| `{{TODO_ID}}`      | derived id (`<camelTitle>-<MMDDHHMM>`) |
| `{{CHILD}}`        | full child instant path |
| `{{CHILD_NAME}}`   | child instant folder basename |
| `{{WS}}`           | leased workspace path |
| `{{SLOT}}`         | slot basename |
| `{{GOLDEN}}`       | golden source path |
| `{{BASE_NAME}}`    | base instant folder basename |
| `{{BASE_CURR}}`    | base `curr_instant` field |
| `{{TMUX_SESSION}}` | tmux session name (`dt-<id>`) |
| `{{TODAY}}`        | `date +%Y-%m-%d` |
| `{{BRIEF}}`        | brief text (file or stdin), multi-line |
| `{{EVIDENCE}}`     | pre-rendered markdown bullet list of `--evidence` pointers |

Contract: unknown `{{...}}` placeholders are left untouched (forgiving — no error).
Substitution runs over `charter.md`, `seed.txt`, and `handoff.md` when present.

### 4. What stays inline (unchanged)

- All orchestration: claim → duplicate → fork dirs → dispatch record → tmux launch
  → rollback trap. Untouched.
- The generic maintain-workspace **stub files** (STATE, RUNBOOK, DECISIONS, ISSUES,
  ASSUMPTIONS, evidence/INDEX) stay inline — they are structural invariants, not
  effort-specific.
- HANDOFF stays inline-generated, with its one ANSI-flavored line neutralized
  ("run the RCA-first mandate (see CHARTER AC-1)" → "follow the CHARTER acceptance
  criteria"). A profile's optional `handoff.md` fully overrides the inline version
  when present.
- The SEED launch path is unchanged: the substituted `seed.txt` text is stored in
  `$SEED` and passed to `tmux send-keys` via `printf %q` exactly as today (handles
  multi-line seeds as a single argument).

### 5. Scope boundaries

- `dispatch-adopt.sh` is **unchanged** — it already accepts `--seed <file|-|text>`
  for its fresh-seed path. A future `--profile` alignment is possible but out of
  scope here.
- `bin/pdispatch` overview and `SKILL.md` get documentation updates for `--profile`
  and a short "profiles" section.

## Backward compatibility & tests

Because a profile is now required (no silent default), existing callers must name a
profile:

- `tests/dispatch-smoke.sh`: add `--profile ansi` to its dispatch invocations. All
  existing assertions still hold — `RCA-FIRST`, `Spark-Java = GOLD`, evidence
  pointers, and the brief text live in the ansi profile and the per-dispatch
  variables are still substituted.
- New test cases:
  - (a) no `--profile` and no default set → non-zero exit (error);
  - (b) unknown profile name → non-zero exit (error);
  - (c) a custom throwaway profile dir → the generated CHARTER/SEED contain that
    profile's content with `{{TITLE}}`, `{{WS}}`, and `{{BRIEF}}` correctly
    substituted.

## Files

New:
- `skills/dispatchInstants/profiles/ansi/charter.md`
- `skills/dispatchInstants/profiles/ansi/seed.txt`

Changed:
- `skills/dispatchInstants/dispatch-todo.sh` — add `--profile` arg; profile
  resolver; python3 substitution helper; replace the CHARTER and SEED heredocs with
  read-template → substitute → write; neutralize the one HANDOFF line + honor an
  optional `handoff.md`.
- `skills/dispatchInstants/tests/dispatch-smoke.sh` — add `--profile ansi`; new
  cases (a)/(b)/(c).
- `skills/dispatchInstants/SKILL.md` — document `--profile` + profiles.
- `bin/pdispatch` — document `--profile` in the `todo` overview line.
