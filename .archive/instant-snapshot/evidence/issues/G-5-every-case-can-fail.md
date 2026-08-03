# G-5 — AC-2: no IT case has been shown to FAIL when the thing it asserts breaks

**Origin:** `AC-2` of `fleetItStabilisation/00000000-08020624-inflight-append-itSuiteStabilisation`.
**State:** OPEN. Frame BUILT and first targets written; **no mutations run.**

---

## 1. What the criterion says
> each case in the sampled population is shown to FAIL when the behaviour it asserts is broken — the
> counter-measure for `P-C`, which has eight recorded sightings and one that shipped.

`P-C` is "green for the wrong reason". The one that SHIPPED was `SI-38`: the release gate recorded GREEN
over a suite with 7 FAIL rows, because it read an exit code from a script with no final `exit` and cited
an evidence file holding two lines about tmux.

## 2. Why it is sampled, not exhaustive — decision `D-5`
Delegated by the operator 2026-08-03: *"base on impact u saw in prod, i leave the decision to u."*

**Every false verdict found in two days had ONE shape: a verdict decided by matching a STRING or a ROW
KIND against another component's output, or by reading a file another component writes.**

| finding | the match that was wrong |
|---|---|
| `II-4` | `*) echo "UNMAPPED"` counted as "the product did not refuse" |
| `II-9` | `receiver in SELF_LIKE` — a bare-name match a chained call defeats |
| `II-10` | `grep -qE 'FLEET_HOME\|--home'` — matched the usage block on all 39 verbs |
| `II-8` | an aggregate reciting all three sub-assertions whatever failed |
| `E9` mode 1 | `awk '$1=="reaped"'` — one of the TWO kinds `reap` emits |
| `SI-38` | a gate reading a file nobody had opened |

**None** was a case asserting an exit code, a count, or a file's existence. So the sampling frame is the
string/kind matchers, and the rest are reported as UNSAMPLED rather than counted as covered — an
unmeasured case reported as covered is the defect this criterion exists to remove.

## 3. The frame, derived mechanically
`fleetItStabilisation/.../bin/case-risk-census.sh`, output at `.../evidence/ac2-risk-census.txt`:

```
RUNNER            CASES  MATCH   CODE   risk
run-J                11     37      1   HIGH
run-group5           28     36      8   HIGH
run-group3           27     34      9   HIGH
run-B                19     32     12   HIGH
run-D                20     27      9   HIGH
run-O                11     22      0   HIGH
run-A                38     18      4   HIGH
run-F                14     17      2   HIGH
run-lineage           5     12      0   MEDIUM
run-G                13      9      0   MEDIUM
run-H                 7      9      0   MEDIUM
run-C                17      0     13   low
run-I                15      0      0   low
… (w1, rmw, Q, P, e9-leak, m9-mutation: low)
TOTAL               259    268
```

**The census is a HEURISTIC and is labelled one.** It counts call sites, not cases, so 259 ids and 268
matching sites are upper bounds, not a per-case classification. Good enough to ORDER the work; not good
enough to certify anything.

## 4. First targets, with the mutation each needs
Full text at `fleetItStabilisation/.../investigations-ac2-first-targets.md`. Summary:

**1. `J7` — the highest-consequence case in the suite.** Its own header:
> *"a tmux session that NO record claims is reported and **never reaped**. If this is wrong, `reap` kills
> somebody else's pane — 'some of those sessions are people's'."*
- *Mutation:* in `pool.reap`, drop the `if not mine: skipped.append(...); continue` guard.
- *Expected:* `J7` RED, naming the ghost. If it stays green, the operator's strongest safety claim is
  unproven.
- *Second mutation:* make `reap` REPORT the ghost but reap it anyway. Separates "the case checks the
  report" from "the case checks the behaviour" — `E9` mode 1 was exactly that confusion.

**2. `J2` — the close-out transaction as a whole.** Five consequences of one call; any four passing is a
half-committed transaction. Mutate each independently; `J2` must go red for EACH.

**3. `group5`'s `M5`/`L7`** — the UNMAPPED path is new (`II-4`) and unmutated. Plant a verb with no
recipe; `*-coverage` must fire and `M5`/`L7` must NOT.

**4. `group3`'s `E9`** — the row-kind matcher is controlled (`bin/e9-says-control.sh`); the orphan-
detection python is not. Mutate it to miss a bodiless claim.

## 5. Deliberately UNSAMPLED, and reported as such
`run-C` (0 matching sites, 13 code checks), `run-I`, `run-w1`, `run-rmw`. Not because they cannot be
wrong, but because no false verdict in two days came from that shape, and an hour there is an hour not
spent on `J7`.

## 6. Rules that apply while doing this
- **One IT job at a time.** Concurrent runners contaminated a run already (`SI-36`).
- **Mutate a COPY**, never the live package — `run-m9-mutation.sh` is the pattern: `cp -r` the tree,
  inject, assert the case dies BY THE NAMED CHECK.
- **A kill for the wrong reason is not a kill.** `run-m9-mutation.sh` checks WHY a mutant died, and that
  is what caught `QI-1` — four mutants "killed" by a ModuleNotFoundError.

## 7. How to know it is closed
- Every case in the frame has a recorded mutation and a demonstrated failure, or is named as having none.
- The unsampled population is listed, not implied.
- A case with no demonstrated failure mode is reported as such rather than counted as coverage.

## 8. Files
- `fleetItStabilisation/.../bin/case-risk-census.sh` and `evidence/ac2-risk-census.txt`
- `fleetItStabilisation/.../investigations-ac2-first-targets.md`
- `fleet/it/run-m9-mutation.sh` — the mutation pattern to copy
- `fleet/it/run-J.sh`, `run-group5.sh`, `run-group3.sh` — the first targets
