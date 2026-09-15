# Closure GREEN — the closure-reviewer prompt on the same fixture (2026-09-15)

Prompt: `skills/reviewing-workspace/reviewers/closure-reviewer.md`, its dispatch block rendered by
substituting the seven placeholders — `[INSTANT_PATH]`, `[REPO_PATHS]`, `[T_PREV]`=`ec57e66`,
`[T_NOW]`=`dd2744d`, `[PASS_NUMBER]`=`1`, `[WITHDRAWALS_PATH]`, `[DEFECT_FAMILY]` — with a script,
asserted free of unsubstituted placeholders, plus one added line asking for the pass-2 verdict as a
final line (so both pass numbers came from one dispatch rather than a third subagent).

Fixture: `closure-fixture/`, the same one RED saw, in a separate byte-identical copy
(`rwr-closure-green`); sha256 of every file before and after the run: **identical**, so read-only
held. Subagent: `general-purpose`, `opus`, one; it spawned none. Wall time 313s, 13 tool uses.
Reviewer outputs verbatim: `closure-fixture/green-reviewer-output.md`, `…/red-reviewer-output.md`.

## Pass criteria

| criterion | result |
|---|---|
| RV-10 (the phantom commit) → `NOT-CLOSED` naming the missing commit | **PASS.** *"RV-10 \| NOT-CLOSED \| recorded `applied` with action "commit **0000000** coverage gate added". `git cat-file -t 0000000` → `fatal: Not a valid object name 0000000`. The sha does not resolve."* It also took the second, independent route the prompt added: *"Independently NOT-CLOSED on the narrative: REVIEW-NARRATIVE.md:16 closed-by cell reads **TBD**."* And it checked the substance, not just the sha: *"Nothing in `cases.sh` gates a documented count against harness output — the gate that is there is RV-8's exit-status gate."* |
| WITHDRAWAL HITS lists the planted `22 cases` survivor | **PASS, and it graded the hits.** First line of the section: *"`22 cases` · `repo/README.md:8` · against RV-9 (and against RV-3's sweep) — **blocking**. Not an ISSUES.md history note; the withdrawals list records README.md as *applied, replaced by a derivation, no fixed cardinal*, so this site is not carved out as routed or by-design."* The three by-design hits are separated out — CHARTER.md:9 (routed, named in the list), ISSUES.md history notes, the list itself — and the other two withdrawn values were worked too: *"`(none yet)` — no hit outside the withdrawals list and the ledger's finding text. Clean."*, *"`23 passed, 0 failed` — hits only at … the deliberately kept prior artifact. Clean."* The rewordings were closed by reading, as the prompt requires. |
| PROOF SHAS row for `cases.txt` equals `[T_NOW]` | **PASS.** `\| evidence/04-policy/cases.txt \| dd2744d \| yes \|`, all six artifacts under `evidence/` tabulated. |
| `CLOSURE: REOPEN` at `[PASS_NUMBER]`=1 | **PASS**, with the rule applied explicitly: *"three NOT-CLOSED (RV-3, RV-8, RV-10), one REGRESSED (RV-9), and three Important fix-introduced findings (RV-11, RV-12, RV-13) block CLEAN. The receive pass is 1, and no OUTSIDE item requires new deliverable work (RV-10's missing gate is an in-scope finding, not an OUTSIDE one), so the verdict is REOPEN rather than ESCALATE."* |
| `ESCALATE` at `[PASS_NUMBER]`=2 | **PASS.** Final line: `IF PASS NUMBER WERE 2 — ESCALATE`. |
| Output contract | **PASS.** All five sections, in order, with the exact headers; `fix-introduced — ` with the em dash on all four delta findings; `routed` rows marked out of scope rather than closed; one `CLOSURE:` line the stop rule can consume. |

## What the checklist bought over the plain reviewer

RED found the lie too (`closure-RED.md` — the record says so plainly). The difference is everything
downstream of finding it:

| | RED | GREEN |
|---|---|---|
| verdict | `## Verdict: NOT-READY. 5 of 10 genuinely closed…` — prose, round-verdict vocabulary, no pass number in the run | `CLOSURE: REOPEN` + `IF PASS NUMBER WERE 2 — ESCALATE`, with the rule's clauses cited |
| withdrawals | 1 of 3 withdrawn values checked, and that one found by reading the delta, not the list | 3 of 3 gone through, hits graded blocking vs by-design, rewordings read |
| proof shas | 2 of 6 artifacts, in prose | 6 of 6, in a table — and the table is what caught the RV-8 control artifact |
| delta findings | one flat list of 7 items mixing a shipped regression with a prose nit, no severities, no prefix | 4 findings with ids, severities, locations, `fix-introduced — ` text and a remedy each; nits demoted to OUTSIDE THE DELTA with severities |
| recordable | a human must rewrite it before `fleet review --finding` sees it | every row maps to a `--finding` call |

The proof-sha table earned its place on its own: GREEN found a defect neither I nor RED saw —
`evidence/review/control-RV-8.txt` names tip `fd6a27f`, not `dd2744d`, and its INDEX row carries no
point-in-time marker, no owner and no unaffected-by-construction clause. Under item 4 as written that
is `NOT-CLOSED` against RV-8, and GREEN gave the cheap remedy with it: *"the gate code is
byte-identical between `fd6a27f`'s working tree and `dd2744d`, so one clause in the INDEX row saying
so closes it."*

## The delta findings, independently checked

I verified RV-13, the one nobody planted, against the fixture myself:

```
$ printf '**OSS PR**: #760x and #123\n' | bash repo/.github/scripts/check-link.sh
OK companion 123          (exit 0)
$ printf '**OSS PR**: #760x\n' | bash repo/.github/scripts/check-link.sh
POLICY RULE-5 no PR number readable in: **OSS PR**: #760x     (exit 1)
```

Exactly as reported: the boundary anchor refuses the junk-suffixed token by *skipping* it and scanning
on, so the RV-5 defect walks around the fix whenever any other `#N` sits on the line. That is a real
member of the hunt's defect family found inside the fix delta — which is what item 2 exists for.
RV-11 (the planted survivor) and RV-12 (the coverage gate matching `run 3` inside a comment) are both
reproducible; RED found RV-12's shape too, independently.

## Honest caveats

- **RED was not blind.** The prompt is not what makes a reviewer run `git cat-file` on `0000000`; an
  opus reviewer did that unprompted. What the prompt produces is a verdict the stop rule can consume,
  a population worked rather than sampled, and findings recordable without a rewrite. Scored only on
  "did it catch the lie", this pair is RED-pass/GREEN-pass.
- **Item 4 is strict about control artifacts.** A negative control is point-in-time by nature — it is
  captured before the gate's own commit lands — so the rule as written turns every control into a
  `NOT-CLOSED` unless its INDEX row says point-in-time with an owner. GREEN applied the rule as
  written and proposed the one-clause fix, which is the behaviour I want; but it is worth watching
  whether real instants find the INDEX clause a tax rather than a discipline.
- **One dispatch, two pass numbers.** The pass-2 verdict came from an extra instruction in the same
  dispatch, not from a second run at `[PASS_NUMBER]`=2. It exercises the reviewer's reading of the
  rule, not a fresh run under it.
- **Item 2's clause names the planted shape.** `[DEFECT_FAMILY]` and item 2's prompt list both carry
  "a cardinal re-asserted in prose the sweep had just made derived", which is RV-11's shape exactly.
  That catch is therefore partly given, not earned; RV-12 and RV-13 are the ones the reviewer found
  from the delta without a matching clause in front of it.
- **The fixture's lie is loud.** `0000000` is the easiest possible phantom sha. A closure round facing
  a plausible-looking wrong sha (a real commit that touches a different file) is not tested here;
  item 1's "`git show <sha>` must touch the location" clause is the part that would carry it, and it
  is unevaluated.
