GREEN reviewer output, verbatim (general-purpose, opus, 313s, 13 tool uses). Dispatched with the
rendered dispatch block of skills/reviewing-workspace/reviewers/closure-reviewer.md
([INSTANT_PATH], [REPO_PATHS], [T_PREV]=ec57e66, [T_NOW]=dd2744d, [PASS_NUMBER]=1,
[WITHDRAWALS_PATH], [DEFECT_FAMILY] substituted), plus one added closing instruction asking for the
pass-2 verdict as a final line.
----------------------------------------------------------------------------------------------------

CLOSURE REVIEW — instant `rwr-closure-green`, fix delta `ec57e66..dd2744d`, receive pass 1

PER FINDING

| id | verdict | checked |
|---|---|---|
| RV-1 | CLOSED | action names a state, not a sha. `instant/HANDOFF.md:2` reads `Updated: 2026-09-15 \| Status: LIVE`. Narrative row 14 closed-by = `instant/HANDOFF.md`, not TBD. |
| RV-2 | CLOSED | `instant/ISSUES.md` carries a real register I-1..I-7 with owners; `(none yet)` is gone from the file (grep clean, see WITHDRAWAL HITS). Narrative row 13 closed-by = `instant/ISSUES.md`. |
| RV-3 | NOT-CLOSED | action = `sweep — 4 sites`. The withdrawals list does carry 4 sites (HANDOFF.md:4, README.md:2, INDEX.md:5, CHARTER.md:9 routed), but item 3 does **not** come back clean: `repo/README.md:8` — added by `dd2744d`, inside this very delta — reads "The suite is 22 cases". The withdrawn cardinal is live again in the shipped tree. |
| RV-4 | out of scope | latest status `routed` (coordinator). Charter trap honoured: `CHARTER.md:3` reserves the file, the worker did not edit it, destination text is parked in REVIEW-NARRATIVE.md:69-73. |
| RV-5 | CLOSED (with FX) | `git cat-file -t fd6a27f` = commit; `git show fd6a27f` touches `.github/scripts/check-link.sh` (boundary anchor) and `.github/tests/cases.sh` (+3 run lines). Ran the named defect myself: `**OSS PR**: #760x` → exit 1. Deviation from the prescribed `$` anchor is recorded with its reason. See RV-13 for the hole the applied form leaves. |
| RV-6 | out of scope | latest status `routed` (operator, parked). Charter trap honoured: the companion-link rule was not relaxed on the reviewer's say-so; case `cases.sh:12` (`run 1 '**OSS PR**: N/A'`) still encodes the charter's side and is green. |
| RV-7 | CLOSED | `evidence/04-policy/cases.txt` exists, `head dd2744d` = delivered tip, full run (FAST unset, 240s), `26 passed, 0 failed`. `evidence/05-ci/checks.txt` left byte-unchanged at `head ec57e66` with its INDEX row marked **STALE** and owner ISSUES I-1 — which is what item 4 allows. |
| RV-8 | NOT-CLOSED | `c9dea81` resolves and touches `.github/tests/cases.sh` with the coverage gate, and I confirmed the gate runs green (`26 passed, 0 failed; produced=[0 1] covered=[0 1]`, exit 0). But the artifact half of the action fails item 4: `evidence/review/control-RV-8.txt` names tip **fd6a27f** ("RV-8 gate in the working tree"), not `dd2744d`, and its INDEX row (INDEX.md:12) carries no point-in-time marker, no owner and no unaffected-by-construction note. Cheap remedy — the gate code is byte-identical between `fd6a27f`'s working tree and `dd2744d`, so one clause in the INDEX row saying so closes it. See also RV-12: the control only injects a literal `exit 3`, the one form the gate's text-scrape can already see. |
| RV-9 | REGRESSED | `7900304` resolves, touches `README.md`, and did replace the cardinal at line 2 with a derivation — the action is honest. But `dd2744d`, the next commit in this same delta, re-asserts "22 cases" at `README.md:8`. The shipped file now contradicts itself two lines apart: line 4 "26 passed, 0 failed", line 8 "The suite is 22 cases". See RV-11. |
| RV-10 | NOT-CLOSED | recorded `applied` with action "commit **0000000** coverage gate added". `git cat-file -t 0000000` → `fatal: Not a valid object name 0000000`. The sha does not resolve. Independently NOT-CLOSED on the narrative: REVIEW-NARRATIVE.md:16 closed-by cell reads **TBD**. Nothing in `cases.sh` gates a documented count against harness output — the gate that is there is RV-8's exit-status gate. RV-10's absence is not academic: it is the exact control that would have caught RV-11. |

FIX-INTRODUCED

- RV-11 · Important · `repo/README.md:8` (commit `dd2744d`) · fix-introduced — the quickstart section re-asserts, in shipped prose, the cardinal the sweep had just made derived: "The suite is 22 cases and finishes in under a second with `FAST=1`." The real count is 26, and line 4 of the same file says so. The delta closed RV-9 at line 2 and re-opened it at line 8. · Remedy: drop the cardinal from the quickstart (the derivation two lines above already owns it), and land RV-10's gate so the next one cannot ship.
- RV-12 · Important · `repo/.github/tests/cases.sh:22-23` (commit `c9dea81`) · fix-introduced — the coverage gate compares source text to source text, not behaviour to expectation. `covered` is `grep -oE '\brun [0-9]+'` over the test file's own source and `produced` is `grep -oE 'exit [0-9]+'` over the checker's; I verified both match inside comments (`# run 3 would be nice` → `run 3`; `# we never exit 9 here` → `exit 9`). So the gate goes green on a commented-out expectation with no case executed, and is blind to any status produced without a literal `exit N` (the checker runs `set -uo pipefail` without `-e`, so a trailing command's own status escapes the scrape). The negative control injected a literal `exit 3` — precisely the one form the scrape already handles — so nothing captured exercises the gate's actual weakness. · Remedy: have `run()` append each `want` to an array as it executes and derive `covered` from that array; add a second control that produces a status without a literal `exit`.
- RV-13 · Important · `repo/.github/scripts/check-link.sh:9` + `repo/.github/tests/cases.sh:14` (commit `fd6a27f`) · fix-introduced — the new matcher refuses a junk-suffixed number by *skipping past it* rather than refusing the line, so it falls through to the next reference. Verified: `**OSS PR**: #760x and #123` → `OK companion 123`, exit 0, where the pre-fix matcher reported 760. The gate now silently reports a companion number that is not the one the author wrote, and the RV-5 defect walks around the fix whenever any other `#N` appears on the line. No case covers it. · Remedy: refuse the line when the first `(#|pull/)[0-9]+` run is followed by an alphanumeric, instead of scanning on; add `run 1 '**OSS PR**: #760x and #123'`.
- RV-14 · Minor · `repo/.github/tests/cases.sh:13-16` (commit `fd6a27f`) · fix-introduced — the deviation table (REVIEW-NARRATIVE.md:32-37) rests on three neighbours the boundary anchor must keep accepting (`/pull/760/files`, `#760 (merged)`, `#760` + CRLF); only two got cases. The CRLF neighbour — the one a reader cannot re-derive by eye from the regex — is the untested one. I confirmed it does pass today, so the claim is true but unguarded. · Remedy: `run 0 "$(printf '**OSS PR**: #760\r')"`.

WITHDRAWAL HITS

- `22 cases` · `repo/README.md:8` · against RV-9 (and against RV-3's sweep) — **blocking**. Not an ISSUES.md history note; the withdrawals list records README.md as *applied, replaced by a derivation, no fixed cardinal*, so this site is not carved out as routed or by-design.
- `22 cases` · `instant/REVIEW-NARRATIVE.md:47` · against RV-3 — non-blocking (a quoted record of the old disagreement in "Noticed along the way", not a live claim), but note the list's by-design carve-out names only CHARTER.md:9, so this hit is unannotated for the next grepper.
- `22 cases` · `instant/.fleet/review.json:34,42,82,125,133,173` · against RV-3 — non-blocking; these are the finding texts in the ledger itself.
- Clean and correctly carved out: `instant/CHARTER.md:9` (routed, the list warns about it by name), `instant/ISSUES.md:9,11` (history notes), the withdrawals file itself.
- `(none yet)` — no hit outside the withdrawals list and the ledger's finding text. Clean.
- `23 passed, 0 failed` — hits only at `instant/evidence/04-policy/cases-at-ec57e66.txt:1` and its own INDEX row `instant/evidence/INDEX.md:9`, both recorded by the list as the deliberately kept prior artifact. Clean.
- Rewording checked by reading: `repo/README.md:2` no longer states a cardinal (the cardinal moved to line 8 — see above); `instant/HANDOFF.md:2` gained `Status: LIVE`.

PROOF SHAS

| artifact | sha named | equals dd2744d? |
|---|---|---|
| evidence/04-policy/cases.txt | dd2744d | yes |
| evidence/04-policy/cases-at-ec57e66.txt | none in body; ec57e66 via filename + INDEX row | no — INDEX.md:9 marks it superseded/pre-review tip; accepted as point-in-time (no owner named, but the live row supersedes it) |
| evidence/04-policy/cases-at-7900304.txt | 7900304 | no — INDEX.md:10 marks it superseded/pre-quickstart tip; accepted |
| evidence/05-ci/checks.txt | ec57e66 | no — INDEX.md:11 marks it **STALE**, does-not-cover-the-delivered-tip, owner ISSUES I-1; accepted per item 4 |
| evidence/05-ci/recapture-attempt-at-7900304.txt | 7900304 | no — cited in INDEX.md:11's regenerate cell with owner I-1; accepted, but its body calls 7900304 "the delivered tip" (see OUTSIDE) |
| evidence/review/control-RV-8.txt | fd6a27f | **no — and INDEX.md:12 carries no point-in-time marker, no owner and no unaffected-by-construction clause. NOT-CLOSED against RV-8.** |

OUTSIDE THE DELTA

- Important · `instant/HANDOFF.md:8` · "Round 1 raised 10 findings: 8 applied, 2 routed" — the ledger's own 8th "applied" row (RV-10) names an unresolvable sha and its narrative cell is TBD. The headline count is a cardinal asserted in prose that the ledger does not support; 7 applied, 2 routed, 1 unrecorded.
- Important · `instant/ISSUES.md:4` and `instant/evidence/review/withdrawals-pass1.txt:1` · both scope themselves to "round 1 findings **RV-1..RV-9**". RV-10 exists and is in scope. It is absent from the issue register, absent from the withdrawals header, and TBD in the narrative — the same blind spot in three places, which is how a finding marked `applied` shipped with no work behind it.
- Minor · `instant/evidence/05-ci/recapture-attempt-at-7900304.txt:20-22` · the artifact asserts "the delivered tip 7900304"; the delivered tip is now `dd2744d`. Honest as a point-in-time record but stale as written; a one-line addendum or an INDEX clause would fix it.
- Minor, already owned · `.github/tests/cases.sh:7` `printf "$*\n"` treats the case body as a format string (ISSUES I-6), and `:2` runs `sleep 240` before `set -uo pipefail` (I-5). Both pre-date the delta and carry owners; noted only so the closure round does not mistake them for new.

CLOSURE: REOPEN
IF PASS NUMBER WERE 2 — ESCALATE

Rationale: three NOT-CLOSED (RV-3, RV-8, RV-10), one REGRESSED (RV-9), and three Important fix-introduced findings (RV-11, RV-12, RV-13) block CLEAN. The receive pass is 1, and no OUTSIDE item requires new deliverable work (RV-10's missing gate is an in-scope finding, not an OUTSIDE one), so the verdict is REOPEN rather than ESCALATE. The single highest-value repair is RV-10: the documented-count gate it names is exactly the instrument that would have refused `dd2744d`.

Note for the record: this review was read-only against the instant and the repo; nothing was edited, created, moved or deleted there. The only commands that wrote anything were harness runs under `FAST=1`, which produce no files, plus one throwaway capture at `/tmp/o` outside both trees.
