# dispatch profiles

A **profile** is the charter + seed template `dispatch-todo.sh` uses to bootstrap a child instant. It sets the
worker's acceptance criteria and framing. Pick the one that matches the *kind of work*, because the profile —
not the `--brief` — determines what the worker is told to deliver. **Choosing the wrong profile silently gives
the worker the wrong ACs.**

| Profile | Use when the TODO is to… | Acceptance shape | Touches product code? |
|---------|--------------------------|------------------|-----------------------|
| `ansi`        | **FIX** one ANSI gap (make a failing ANSI test go green) | LOCAL REPRO → RCA → **FIX** → CI red→green + catalog | **Yes** — offload/translate/deny |
| `ansi-expose` | **EXPOSE / PROVE COMPLETENESS** — prove no ANSI fallback survives + no gap is hidden, and classify the full gap surface | removal-integrity → masking-audit → fallback-census → coverage-proof → needs-RCA → one "0 hidden gaps" catalog | **No** — exposure only (instrumentation to *observe* fallback is the sole exception) |

## Selecting a profile
`--profile <name>` (a bare name resolves under this `profiles/` dir; a path with a slash is used verbatim).
Resolution order if `--profile` is omitted: `$DISPATCH_PROFILE`, then `~/.claude-ws-pool/profile`.

> ⚠️ **Footgun:** the machine default (`~/.claude-ws-pool/profile`) is `ansi` (fix) because fixing is the common
> MR case. An **exposure/audit** dispatch MUST pass `--profile ansi-expose` explicitly, or the worker will be
> handed the fix-a-gap pipeline (LOCAL REPRO → FIX → red→green) — which directly contradicts an exposure goal.

## Keep `--brief` short
Both profiles' charters are **self-contained** (the ACs carry the substance). `--brief` is injected as a short
*context* section, not the spec — pass 1–3 sentences of run-specific framing plus `--evidence` pointers. A giant
brief that restates the ACs produces a duplicated, self-contradicting charter.

## Anatomy of a profile
```
profiles/<name>/
  charter.md   # rendered to the child CHARTER.md; {{TITLE}} {{CHILD_NAME}} {{TODAY}} {{BASE_NAME}}
               # {{BASE_CURR}} {{WS}} {{SLOT}} {{GOLDEN}} {{BRIEF}} {{EVIDENCE}} placeholders
  seed.txt     # the interactive prompt sent to the launched claude session
  handoff.md   # (optional) rendered to the child HANDOFF.md
```
Regression coverage: `tests/profile-ansi-expose-smoke.sh` asserts the exposure profile renders exposure ACs,
carries no fix-pipeline language, and does not duplicate the brief.
