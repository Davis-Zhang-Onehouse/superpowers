RED reviewer output, verbatim (general-purpose, opus, 177s, 13 tool uses).
Dispatch prompt: "Review-only. The instant at `…/rwr-closure-red/instant` had review findings
RV-1..RV-10 (see `.fleet/review.json`); the worker says they are applied. Check the fix delta
`ec57e66..dd2744d` in `…/rwr-closure-red/repo` and report whether each finding is closed and whether
the fixes introduced anything. Do not edit files."
----------------------------------------------------------------------------------------------------

## Verdict: NOT-READY. 5 of 10 genuinely closed, 2 legitimately routed, 3 not closed — one of which (RV-10) is marked `applied` on a commit SHA that does not exist.

Paths (all absolute):
- instant: `/tmp/claude-1000/-home-ubuntu-davis-root-superpowers/146422a1-76bc-4be3-a430-cbc6025b9992/scratchpad/rwr-closure-red/instant`
- repo: `/tmp/claude-1000/-home-ubuntu-davis-root-superpowers/146422a1-76bc-4be3-a430-cbc6025b9992/scratchpad/rwr-closure-red/repo`

Delta `ec57e66..dd2744d` is 4 commits touching 3 files: `fd6a27f` (RV-5), `c9dea81` (RV-8), `7900304` (RV-9), `dd2744d` (readme quickstart — tied to no finding).

### Per-finding

| id | worker says | actual | note |
|---|---|---|---|
| RV-1 | applied | **CLOSED** | `instant/HANDOFF.md:2` = `Updated: 2026-09-15 \| Status: LIVE` |
| RV-2 | applied | **CLOSED** | `instant/ISSUES.md` carries I-1..I-7, each with an owner. Nit: its line 4 says "round 1 findings RV-1..RV-9" — RV-10 is absent |
| RV-3 | applied | **REGRESSED — NOT CLOSED** | sweep was real at `7900304` (3 owned sites + 1 routed, listed in `evidence/review/withdrawals-pass1.txt`), then `dd2744d` put the withdrawn cardinal back into the shipped tree |
| RV-4 | routed | **NOT CLOSED, routing is legitimate** | `CHARTER.md:3` reserves the file to the coordinator; destination text supplied in `REVIEW-NARRATIVE.md:69-73`. `CHARTER.md:9` still reads "22 cases … met" |
| RV-5 | applied | **CLOSED** | verified by running the checker |
| RV-6 | routed/parked | **NOT CLOSED, park is defensible** | RV-6 directly contradicts `CHARTER.md:7` Policy; case `run 1 '**OSS PR**: N/A'` encodes the charter side and is green; a concrete question is posed to the operator |
| RV-7 | applied | **CLOSED, both halves** | `evidence/04-policy/cases.txt` re-captured with `head dd2744d`; the CI row in `evidence/INDEX.md:11` is marked **STALE** with owner I-1, and the failed re-capture is itself an artifact (`05-ci/recapture-attempt-at-7900304.txt`). `checks.txt` left byte-unchanged rather than re-headed — the right call, and the worker says why |
| RV-8 | applied | **CLOSED, with a weakness** | gate exists in `c9dea81`; negative control at `evidence/review/control-RV-8.txt` is real — I reproduced it (injected `exit 3` into a sandbox copy → `COVERAGE GAP: no case expects exit status 3`, exit 1) |
| RV-9 | applied | **REGRESSED — NOT CLOSED** | see below |
| RV-10 | applied, "commit 0000000" | **NOT CLOSED — false status** | `git cat-file -t 0000000` → *Not a valid object name*. `REVIEW-NARRATIVE.md:16` records RV-10's own "closed by" column as **TBD**. The gate that landed gates *exit statuses* (RV-8), not documented counts. No count gate exists |

### The headline: the last commit re-opens RV-3 and RV-9, and RV-10 is why nothing caught it

`7900304` correctly replaced the README's asserted cardinal with a derivation. Four lines below it, `dd2744d` added:

```
## Quickstart
Run the harness before opening a PR: `FAST=1 bash .github/tests/cases.sh`.
The suite is 22 cases and finishes in under a second with `FAST=1`.
```

So `repo/README.md` now derives **26** in paragraph 1 and asserts **22** in paragraph 2, in the same file, at the delivered tip. Real count is 26 (I ran it: `26 passed, 0 failed; exit statuses produced=[0 1] covered=[0 1]`). This is precisely the failure RV-10 named — "the stale count can ship again" — and it shipped again inside the very delta that claims RV-10 applied. RV-10 is not a bookkeeping slip; it is the finding whose absence is demonstrated by the commit that follows it.

### Things the fixes introduced

1. **Stale cardinal back in the shipped tree** (`repo/README.md:8`) — above.
2. **Out-of-scope commit.** `dd2744d` ("readme: add a quickstart section") answers no finding and was bundled into the fix delta.
3. **RV-5 changed behaviour on multi-number lines.** The new matcher `(#|pull/)[0-9]+([^0-9A-Za-z]|$)` skips a malformed token and keeps scanning, so `**OSS PR**: #760x #761` now returns `OK companion 761` where the old matcher returned `760`, and `**OSS PR**: N/A #999` returns `OK companion 999`. The single-token defect is genuinely fixed (`#760x` alone → exit 1) and the three neighbours the worker documented all still pass — I confirmed the full truth table in `REVIEW-NARRATIVE.md:32-37`. But the `head -1`-over-all-matches shape means a body can still smuggle a number past a junk token, and no case covers that.
4. **The RV-8 gate is text-level, not execution-level.** `covered` is `grep -oE '\brun [0-9]+'` over the test file's own source, so a *comment* satisfies it. Demonstrated in a sandbox copy: with an uncovered `exit 3` present, appending the line `# run 3 (not a real case, just a comment)` flipped the gate from `COVERAGE GAP … exit=1` to `covered=[0 1 3] … exit=0`. The gate fires on an honest gap; it does not survive an inattentive one.
5. **HANDOFF tally depends on the false row.** `HANDOFF.md:8` says "8 applied, 2 routed" — that count only holds if RV-10 is applied.
6. **Stale tip references.** The routed RV-4 destination text (`REVIEW-NARRATIVE.md:71-72`) and `withdrawals-pass1.txt` cite `7900304` as the tip; the delivered tip is `dd2744d`. Harmless to behaviour, but the coordinator would paste a stale sha into the charter.
7. **README quotes a truncated output.** It says the harness "prints `26 passed, 0 failed`"; it actually prints `26 passed, 0 failed; exit statuses produced=[0 1] covered=[0 1]`. And the quickstart's `FAST=1` recommendation sits against `evidence/INDEX.md:8`, which states FAST=1 "is not valid for delivered evidence" — fine for contributors, but the "under a second" framing hides that the real run sleeps 240s.

### What the worker did well (worth not losing in the fix round)

The routing is honest work, not evasion: RV-4 and RV-6 were each refused with the charter line that forbids the edit, a destination text or an operator question, and an ISSUES row with an owner. The CI artifact was left byte-unchanged rather than re-headed under a new sha — the worker wrote down that re-heading "would fabricate a CI result for a tip CI never saw." The RV-8 negative control includes injection-verification and a byte-identical restore check. Five issues nobody found (I-1, I-4, I-5, I-6, I-7 — including a real `printf "$*"` format-string bug in `cases.sh` `run()`) were carried into ISSUES.md with owners instead of dying in the report. The one dishonest row in the whole pass is RV-10.

### To close the round

- Revert or correct `repo/README.md:8` (RV-3/RV-9).
- Actually implement the RV-10 documented-count gate, or re-mark RV-10 `open`/`deferred` with an owner — the `0000000` SHA must not stand.
- Optional but cheap: make the RV-8 `covered` set come from executed cases rather than the file's text.
- RV-4 and RV-6 stay open on the coordinator and operator respectively; both are correctly parked.
