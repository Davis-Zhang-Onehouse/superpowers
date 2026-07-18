# Profile-driven CHARTER + SEED — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the effort-specific child CHARTER body and interactive SEED out of `dispatch-todo.sh` into a selectable profile directory, so the toolkit is reusable across efforts without editing the script.

**Architecture:** A profile is a directory (`charter.md` + `seed.txt` + optional `handoff.md`) of `{{VAR}}`-templated text. `dispatch-todo.sh` gains a required `--profile <name|path>` selector (with `$DISPATCH_PROFILE` / pool-default fallbacks, but no silent default), resolves + validates the profile, and renders its templates via a python3 substitution helper in place of today's inline heredocs. Today's ANSI content ships as the `ansi` profile.

**Tech Stack:** bash, python3 (both already required), tmux, git.

## Global Constraints

- Zero external deps: bash + git + tmux + coreutils + python3 only. No rsync/scp/curl/ssh.
- Path-independent: scripts resolve their own dir via `$HERE`; no machine-specific paths in code (effort paths live in profile *content*).
- Tests are hermetic (temp dirs + stubs) and print `PASS`/`FAIL`.
- No silent default profile: if none is selected, error and list shipped profiles.
- Preserve all orchestration (claim → duplicate → fork → record → launch → rollback) unchanged.

## Baseline note

`tests/dispatch-smoke.sh` is **already red** before this change: line 85 greps `'Spark-Java = GOLD'` (spaces) which does not exist in the CHARTER (`Spark-Java=GOLD`, no spaces), and the `grep -c ... || echo 0` idiom double-counts to `0\n0` on no-match. Task 2 fixes this by hardening the grep assertions to `grep -q`.

## File structure

```
skills/dispatchInstants/
  profiles/ansi/charter.md   NEW  child CHARTER template (verbatim ANSI content, {{VAR}} placeholders)
  profiles/ansi/seed.txt     NEW  interactive kickoff template (verbatim ANSI SEED, {{VAR}} placeholders)
  dispatch-todo.sh           MOD  +--profile, resolver, render_template(), drop 2 heredocs, neutralize HANDOFF line
  tests/dispatch-smoke.sh    MOD  +--profile ansi on existing cases; harden greps; +profile cases
  SKILL.md                   MOD  document --profile + profiles
bin/pdispatch                MOD  document --profile in the `todo` overview
```

## Variable mapping (for the verbatim lift in Task 1)

When copying the current inline content into the profile files, replace each shell interpolation with its placeholder:

| Inline (`dispatch-todo.sh`) | Profile placeholder |
|---|---|
| `${TITLE}`       | `{{TITLE}}` |
| `${CHILD_NAME}`  | `{{CHILD_NAME}}` |
| `${CHILD}`       | `{{CHILD}}` |
| `${TODAY}`       | `{{TODAY}}` |
| `${BASE_NAME}`   | `{{BASE_NAME}}` |
| `${BASE_CURR}`   | `{{BASE_CURR}}` |
| `${WS}`          | `{{WS}}` |
| `${CLAIMED_SLOT}`| `{{SLOT}}` |
| `${GOLDEN}`      | `{{GOLDEN}}` |
| `${BRIEF_TEXT}`  | `{{BRIEF}}` |
| `${EVI_MD}`      | `{{EVIDENCE}}` |

The literal `/home/ubuntu/davis_root/spark` in the SEED stays literal text in `seed.txt` (it is profile content, not a script variable).

---

### Task 1: Extract the ANSI content into `profiles/ansi/`

**Files:**
- Create: `skills/dispatchInstants/profiles/ansi/charter.md`
- Create: `skills/dispatchInstants/profiles/ansi/seed.txt`

**Interfaces:**
- Produces: two template files consumed by Task 2's `render_template`. Placeholders drawn only from the mapping table above.

- [ ] **Step 1: Write `charter.md`** — copy the current CHARTER heredoc body (`dispatch-todo.sh:172-242`, i.e. everything between `<<EOF` and the closing `EOF`) into the file, applying the variable mapping. No `${...}` may remain.

- [ ] **Step 2: Write `seed.txt`** — copy the current SEED string (`dispatch-todo.sh:313`, the value assigned to `SEED=`) into the file as a single line, applying the variable mapping (`${CHILD}`→`{{CHILD}}`, `${WS}`→`{{WS}}`). Keep the literal spark path.

- [ ] **Step 3: Verify no stray shell interpolation + key placeholders present**

Run:
```bash
cd skills/dispatchInstants
! grep -R '\${' profiles/ansi/ && echo "NO_SHELL_VARS_OK"
grep -q '{{TITLE}}' profiles/ansi/charter.md && grep -q '{{BRIEF}}' profiles/ansi/charter.md && grep -q '{{EVIDENCE}}' profiles/ansi/charter.md && echo "CHARTER_PLACEHOLDERS_OK"
grep -q '{{CHILD}}' profiles/ansi/seed.txt && grep -q '{{WS}}' profiles/ansi/seed.txt && echo "SEED_PLACEHOLDERS_OK"
grep -q 'RCA-FIRST' profiles/ansi/charter.md && echo "RCA_CONTENT_OK"
```
Expected: `NO_SHELL_VARS_OK`, `CHARTER_PLACEHOLDERS_OK`, `SEED_PLACEHOLDERS_OK`, `RCA_CONTENT_OK` all print.

- [ ] **Step 4: Commit**

```bash
git add skills/dispatchInstants/profiles/ansi/charter.md skills/dispatchInstants/profiles/ansi/seed.txt
git commit -m "feat(dispatchInstants): add ansi profile (charter.md + seed.txt)"
```

---

### Task 2: Wire `dispatch-todo.sh` to the profile (required) + fix the smoke test

**Files:**
- Modify: `skills/dispatchInstants/dispatch-todo.sh`
- Modify: `skills/dispatchInstants/tests/dispatch-smoke.sh`

**Interfaces:**
- Consumes: `profiles/ansi/charter.md`, `profiles/ansi/seed.txt` from Task 1.
- Produces: `--profile <name|path>` CLI; `render_template <file>` (stdout) using `TPL_*` env vars; profile resolution honoring `$DISPATCH_PROFILE` and `${POOL_DIR:-~/.claude-ws-pool}/profile`.

- [ ] **Step 1: Add `--profile` arg + `PROFILE` var**

In the args block (`dispatch-todo.sh:49-64`): add `PROFILE=""` to the init line and a case arm:
```bash
    --profile)     PROFILE="$2"; shift 2;;
```

- [ ] **Step 2: Add profile resolution + validation (fail-fast, before claiming a slot)**

Immediately after the golden validation block (after `dispatch-todo.sh:81`), add:
```bash
# ---- resolve profile (required; no silent default) --------------------------
PROFILES_DIR="$HERE/profiles"
PROFILE_SEL="$PROFILE"
[ -n "$PROFILE_SEL" ] || PROFILE_SEL="${DISPATCH_PROFILE:-}"
if [ -z "$PROFILE_SEL" ]; then
  pf="${POOL_DIR:-$HOME/.claude-ws-pool}/profile"
  [ -f "$pf" ] && PROFILE_SEL="$(head -1 "$pf")"
fi
if [ -z "$PROFILE_SEL" ]; then
  err "no profile selected. Pass --profile <name|path>, set \$DISPATCH_PROFILE, or write a name/path to ${POOL_DIR:-$HOME/.claude-ws-pool}/profile"
  { echo "available shipped profiles:"; ls "$PROFILES_DIR" 2>/dev/null | sed 's/^/  - /'; } >&2
  exit 2
fi
case "$PROFILE_SEL" in
  */*|.*) PROFILE_DIR="$(realpath -m -- "$PROFILE_SEL")";;   # path
  *)      PROFILE_DIR="$PROFILES_DIR/$PROFILE_SEL";;          # bare name
esac
[ -d "$PROFILE_DIR" ]              || { err "profile dir not found: $PROFILE_DIR"; exit 2; }
[ -f "$PROFILE_DIR/charter.md" ]  || { err "profile missing charter.md: $PROFILE_DIR"; exit 2; }
[ -f "$PROFILE_DIR/seed.txt" ]    || { err "profile missing seed.txt: $PROFILE_DIR"; exit 2; }
```

- [ ] **Step 3: Add the `render_template` helper**

After the color/log helpers (after `dispatch-todo.sh:46`), add:
```bash
# render_template <template-file>  ->  stdout, with {{VAR}} placeholders filled.
# Unknown {{...}} placeholders are left literal. python3 (already a dep) avoids
# sed-escaping hazards for multi-line brief/evidence and slash-heavy paths.
render_template() {
  local tpl="$1"
  TPL_TITLE="$TITLE" TPL_TODO_ID="$TODO_ID" TPL_CHILD="$CHILD" \
  TPL_CHILD_NAME="$CHILD_NAME" TPL_WS="$WS" TPL_SLOT="$CLAIMED_SLOT" \
  TPL_GOLDEN="$GOLDEN" TPL_BASE_NAME="$BASE_NAME" TPL_BASE_CURR="$BASE_CURR" \
  TPL_TMUX_SESSION="$TMUX_SESSION" TPL_TODAY="$TODAY" \
  TPL_BRIEF="$BRIEF_TEXT" TPL_EVIDENCE="$EVI_MD" \
  python3 - "$tpl" <<'PY'
import os, re, sys
tpl = open(sys.argv[1]).read()
vars = {k[4:]: v for k, v in os.environ.items() if k.startswith("TPL_")}
sys.stdout.write(re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: vars.get(m.group(1), m.group(0)), tpl))
PY
}
```
Note: `CHILD_NAME` is set at `:99`, `CLAIMED_SLOT`/`WS` after the claim, `BRIEF_TEXT`/`EVI_MD` in the fork step — all defined before any `render_template` call below.

- [ ] **Step 4: Replace the CHARTER heredoc with a render call**

Replace the whole `cat > "$CHILD/CHARTER.md" <<EOF ... EOF` block (`dispatch-todo.sh:171-243`) with:
```bash
render_template "$PROFILE_DIR/charter.md" > "$CHILD/CHARTER.md"
```

- [ ] **Step 5: Replace the HANDOFF heredoc (neutralize the ANSI line; honor optional `handoff.md`)**

Replace the `cat > "$CHILD/HANDOFF.md" <<EOF ... EOF` block (`dispatch-todo.sh:245-278`) with:
```bash
if [ -f "$PROFILE_DIR/handoff.md" ]; then
  render_template "$PROFILE_DIR/handoff.md" > "$CHILD/HANDOFF.md"
else
  cat > "$CHILD/HANDOFF.md" <<EOF
Updated: ${TODAY} | Status: LIVE SNAPSHOT (rots)

# ${TITLE} — HANDOFF   (read me first)

## Resume here
- Instant: ${CHILD}
- Workspace (code checked out here): ${WS}   (slot ${CLAIMED_SLOT})
- Resume: \`cd ${WS} && claude --resume <uuid>\`   (record the uuid in the session log below once known)
- Dispatched: ${TODAY} from base ${BASE_NAME} (tmux session: ${TMUX_SESSION})

## Where we are (one paragraph)
Freshly dispatched. Nothing done yet. Next: follow the CHARTER acceptance criteria.

## Next action
1. Read CHARTER.md and begin at its first acceptance criterion.
2. Keep this instant maintained per superpowers:maintain-workspace.

## Parked decision (for the operator — empty unless I need you)
<none>

## Live snapshot (volatile — dated)
- In flight: not started.

## Session log
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| ${TODAY} | ${WS} | (dispatched) | Instant forked + workspace leased by parallelDispatch; awaiting first session action. |

## Index
- Scope / acceptance / brief → CHARTER.md
- Decisions → DECISIONS.md · Issues → ISSUES.md · Assumptions → ASSUMPTIONS.md
- RCA / deep dives → investigations/  · Proof → evidence/INDEX.md
EOF
fi
```

- [ ] **Step 6: Replace the SEED assignment with a render call**

Replace the `SEED="You are a dispatched GlutenMain worker ... state when done."` assignment (`dispatch-todo.sh:313`) with:
```bash
SEED="$(render_template "$PROFILE_DIR/seed.txt")"
```

- [ ] **Step 7: Update existing smoke-test cases to pass `--profile ansi` + harden the grep assertions**

In `tests/dispatch-smoke.sh`:
- Add `--profile ansi` to the Test-1 dispatch (`:70-71`), the Test-2 dispatch (`:109`), the Test-3 dispatch (`:120`), and the Test-4 dispatch (`:133`).
- Replace the fragile `grep -c ... || echo 0` assertions (`:83-90`) with `grep -q` form, and fix the gold-framing pattern to one that exists:
```bash
grep -q 'RCA-FIRST'      "$CHILD/CHARTER.md" && echo "  ok: CHARTER carries RCA-FIRST mandate" || { echo "  XX: CHARTER lacks RCA-FIRST"; FAILED=1; }
grep -q 'Spark-Java=GOLD' "$CHILD/CHARTER.md" && echo "  ok: CHARTER frames gold-vs-actual" || { echo "  XX: CHARTER missing gold framing"; FAILED=1; }
grep -q 'RANKING.md#1'   "$CHILD/CHARTER.md" && echo "  ok: CHARTER carries evidence pointers" || { echo "  XX: evidence pointers missing"; FAILED=1; }
grep -q 'int4 overflow'  "$CHILD/CHARTER.md" && echo "  ok: CHARTER carries the brief" || { echo "  XX: brief missing"; FAILED=1; }
```

- [ ] **Step 8: Run the smoke test — expect PASS**

Run: `bash skills/dispatchInstants/tests/dispatch-smoke.sh 2>&1 | tail -5`
Expected: ends with `PASS: dispatch-todo AC-2 ...` (all `ok:`, no `XX:`).

- [ ] **Step 9: Commit**

```bash
git add skills/dispatchInstants/dispatch-todo.sh skills/dispatchInstants/tests/dispatch-smoke.sh
git commit -m "feat(dispatchInstants): profile-driven CHARTER+SEED in dispatch-todo (required --profile); fix smoke greps"
```

---

### Task 3: Add profile-behavior test cases

**Files:**
- Modify: `skills/dispatchInstants/tests/dispatch-smoke.sh`

**Interfaces:**
- Consumes: the `--profile` CLI + resolution from Task 2.

- [ ] **Step 1: Add Test 5/6/7 before the final PASS/FAIL block (`:137`)**

```bash
echo "== Test 5: no profile selected (no flag/env/pool file) => error =="
prc=0
DISPATCH_PROFILE= "$DISPATCH" --base "$BASE" --title "no profile" --brief - --golden "$GOLDEN" --no-launch <<<"b" >/dev/null 2>&1 || prc=$?
check "dispatch errors when no profile is selected" "$([ $prc -ne 0 ] && echo yes || echo no)" "yes"

echo "== Test 6: unknown profile name => error =="
urc=0
"$DISPATCH" --base "$BASE" --title "bad profile" --brief - --golden "$GOLDEN" --profile doesNotExist --no-launch <<<"b" >/dev/null 2>&1 || urc=$?
check "dispatch errors on unknown profile name" "$([ $urc -ne 0 ] && echo yes || echo no)" "yes"

echo "== Test 7: custom profile dir => content + substitution =="
CUSTOM="$ROOT/customProfile"; mkdir -p "$CUSTOM"
printf 'CUSTOM CHARTER for {{TITLE}} in {{WS}}\nBRIEF: {{BRIEF}}\n' > "$CUSTOM/charter.md"
printf 'custom seed for {{TITLE}}\n' > "$CUSTOM/seed.txt"
BRIEF7="$ROOT/brief7.md"; printf 'my custom brief body\n' > "$BRIEF7"
out7="$("$DISPATCH" --base "$BASE" --title "Custom Effort X" --brief "$BRIEF7" --golden "$GOLDEN" --profile "$CUSTOM" --no-launch 2>&1)" || { echo "$out7"; echo "  XX: custom-profile dispatch errored"; FAILED=1; }
CHILD7="$(printf '%s\n' "$out7" | sed -n 's/.*instant   : //p' | head -1)"
grep -q 'CUSTOM CHARTER for Custom Effort X' "$CHILD7/CHARTER.md" && echo "  ok: custom CHARTER title substituted" || { echo "  XX: custom CHARTER not rendered"; FAILED=1; }
grep -q 'my custom brief body' "$CHILD7/CHARTER.md" && echo "  ok: custom CHARTER brief substituted" || { echo "  XX: brief not substituted"; FAILED=1; }
! grep -q '{{TITLE}}' "$CHILD7/CHARTER.md" && echo "  ok: no unrendered placeholders left" || { echo "  XX: placeholders left unrendered"; FAILED=1; }
```
Note: Test 7 leases a second slot (`wsB`) and does not release it; that is fine — the final PASS/FAIL block does not assert a global lease count.

- [ ] **Step 2: Run the smoke test — expect PASS**

Run: `bash skills/dispatchInstants/tests/dispatch-smoke.sh 2>&1 | tail -8`
Expected: Tests 5/6/7 print `ok:` lines; ends with `PASS: dispatch-todo AC-2 ...`.

- [ ] **Step 3: Commit**

```bash
git add skills/dispatchInstants/tests/dispatch-smoke.sh
git commit -m "test(dispatchInstants): cover required/unknown/custom profile behavior"
```

---

### Task 4: Document `--profile` in SKILL.md and pdispatch

**Files:**
- Modify: `skills/dispatchInstants/SKILL.md`
- Modify: `bin/pdispatch`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the SKILL.md dispatch example** — in the "Dispatching a TODO" fenced block (`SKILL.md:43-50`), add a `--profile` line, e.g. after `--base`:
```
  --profile ansi                                   # which CHARTER+SEED profile (skills/dispatchInstants/profiles/<name>/ or a path); REQUIRED
```

- [ ] **Step 2: Add a "Profiles" subsection to SKILL.md** — after the "Dispatching a TODO" section, add:
```markdown
## Profiles (the CHARTER + SEED content)
Each worker's CHARTER.md and interactive kickoff SEED come from a **profile** — a
directory `profiles/<name>/` (or any path) holding `charter.md` + `seed.txt` (+ an
optional `handoff.md`), templated with `{{TITLE}} {{WS}} {{BRIEF}} {{EVIDENCE}} …`.
Select one with `--profile <name|path>`; a profile is REQUIRED (no silent default) —
you can also set `$DISPATCH_PROFILE` or write a name/path to `~/.claude-ws-pool/profile`.
The shipped `ansi` profile carries the Gluten-Velox ANSI-gap pipeline; copy it to make
your own effort's profile.
```

- [ ] **Step 3: Update `bin/pdispatch` overview** — in the `pdispatch todo` line (`bin/pdispatch:34`) mention `--profile`, e.g. change the usage hint to `--base <instant> --profile <name> --title .. --brief ..`.

- [ ] **Step 4: Verify docs render + help runs**

Run:
```bash
grep -q '\-\-profile' skills/dispatchInstants/SKILL.md && echo SKILL_OK
bin/pdispatch help >/dev/null && echo PDISPATCH_OK
```
Expected: `SKILL_OK` and `PDISPATCH_OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/dispatchInstants/SKILL.md bin/pdispatch
git commit -m "docs(dispatchInstants): document --profile + profiles"
```

---

## Self-review

- **Spec coverage:** §1 profile dir → Task 1; §2 selection/resolution/no-silent-default → Task 2 Step 2 + Task 3 Tests 5/6; §3 substitution → Task 2 Step 3 + Task 3 Test 7; §4 stays-inline (stubs untouched, HANDOFF neutralized + optional override) → Task 2 Steps 5; §5 docs → Task 4; §6 tests/back-compat → Task 2 Step 7 + Task 3. All covered.
- **Placeholder scan:** all steps carry concrete code/commands; the verbatim lift in Task 1 is specified by an explicit mapping table + exact source line ranges (mechanical, unambiguous).
- **Type consistency:** `render_template`, `PROFILE_DIR`, `PROFILE_SEL`, `PROFILES_DIR`, `TPL_*` names used consistently across Task 2 steps; test var names (`CHILD7`, `CUSTOM`) self-contained in Task 3.
