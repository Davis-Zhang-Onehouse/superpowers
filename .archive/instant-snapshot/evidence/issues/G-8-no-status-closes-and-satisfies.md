# G-8 — no terminal status BOTH closes a milestone honestly AND satisfies its dependents

**Origin:** `FI-17`, added to the quanton v2stackcoordinator register 2026-08-03 ~02:51Z.
**State:** OPEN. Feature gap — missing vocabulary, not a defect.
**Already caused one regression on our side; see §4.**

---

## 1. The situation, concretely (theirs)

`q4-nonansi-quarantine-owner` covered 4 non-ANSI test failures quarantined inside the ANSI dims. The
operator sanctioned them:

> *"those 4 tests I sanctioned them, keep them disabled so we have green ci and no re enablement needed"*

The milestone's **question was answered** — but **no work was done and none ever will be.** Meanwhile
`q5-quarantine-lift-verify`, the forcing function proving the *other 74* come back, **depends on `q4`**.

## 2. Both available statuses are wrong

| status | what it expresses | what it does to `q5` |
|---|---|---|
| `dropped` | accurate: *"withdrawn, no work will happen"* | **not "landed"** — `q5` permanently unreachable, silently destroying the forcing function for 74 tests |
| `done` | **inaccurate**: reads as *"the work completed"*, i.e. the 4 tests were made green | `q5` unblocks correctly |

They chose `done` — a broken forcing function being worse than an imprecise label — and then spent three
artifacts compensating: a note on the proposal, an evidence file, and a DECISIONS entry, all saying
*"`done` here means the question is answered, NOT that the tests are green."*

**That compensation is prose, and prose is what this registry says not to trust.** A successor reading
`q4 = done` from the porcelain — the correct thing to read — is told the tests passed. They are
permanently disabled by sanction.

## 3. The shape of it
**`fleet` models "did the work happen?" but not "is this question closed?"**, and a roadmap needs both.
Every long effort accumulates milestones resolved by DECISION rather than by WORK — scope cuts,
sanctioned exclusions, supersessions — and today each must either block its dependents forever or
overstate what was achieved.

Two occurrences in one five-day effort (`p1`, `q4`) suggests it is common rather than exotic.

## 4. ⚠️ It already bit US, and the bite is instructive
`milestone --retire` (`FI-10`, released `0.3.1`) sets `dropped`. Measured 2026-08-03:

```
before retire:  ready = ['p1']          # q5 depends on p1
after  retire:  ready = []              # q5 is now permanently unreachable
q5 row: severity=info                   # ← reported as INFORMATION
  clears_when: every dep reaches status=done through an applied proposal   # ← impossible
```

So the retire verb we shipped to fix `FI-10` walks straight into `FI-17`, and my `FI-2` fix — which made
"deps not landed" INFO — filed the permanent block as news with an impossible remedy. **Three of our own
changes composing into a silent trap.**

**The severity half is FIXED** (`11f2f58`): a dep that is TERMINAL-and-unlanded is now ATTENTION and its
`clears_when` names the routes that exist. **The vocabulary gap is NOT fixed** — that is this issue. A
coordinator retiring a milestone with dependents still has to choose between the same two wrong statuses.

## 5. Their request
A terminal status that **satisfies dependencies** while **not claiming completion**:
- **`sanctioned`** — resolved by explicit decision that no work will occur; counts as landed.
- **`superseded`** — the intent is carried elsewhere; counts as landed. (Would also have suited `p1`,
  whose successors `v0`…`v3` genuinely carry its intent.)
- or make **`dropped` configurably landing** — `propose --status dropped --satisfies-deps` — so the
  coordinator states the intent explicitly rather than encoding it in a status meaning something else.

## 6. What a fix must decide
1. **New status(es), or a flag on the existing one?** A new status changes `STATUSES`, `LANDED`,
   `TERMINAL`, every render, and the IT matrices that derive from them. A flag is smaller but puts the
   meaning in the transition rather than in the state, and the state is what a successor reads.
2. **If a new status: is it one or two?** `sanctioned` and `superseded` express different things and both
   occurred. Two vocabulary words for two real situations may be right; it may also be over-modelling on
   a sample of two.
3. **What does `--retire` become?** It currently writes `dropped`. If `superseded` exists, retiring a
   milestone whose intent moved elsewhere should probably write that instead — and `--retire` should
   likely require the coordinator to say WHICH.
4. **Migration.** Nothing on disk uses a new status, so no data migrates; but `LANDED` widening changes
   readiness for existing roadmaps, and that must be measured before and after on a real one.
5. **`G-7` interacts:** if `--retire` becomes sugar over propose/apply, the status choice moves into the
   proposal, where it is attributed and evidenced — which is the better home for a decision this
   consequential.

## 7. How to know it is closed
- A milestone resolved by decision can be closed with a status that is TRUE and that unblocks dependents.
- No compensating prose is required to explain what a status means.
- `--retire` cannot silently strand dependents — either the status lands, or the operator is told what
  will happen and chooses.
- Readiness is re-measured on a real roadmap before and after any `LANDED` change.

## 8. Files
- `fleet/src/fleet/roadmap.py` — `STATUSES`, `LANDED`, `TERMINAL`, `PENDING`, `_blocker`, `retire`
- `fleet/src/fleet/cli.py` — `_do_milestone` (`--retire`), `_do_propose` (`--status`)
- `fleet/it/run-group5.sh`, `run-A.sh` — matrices deriving from the status vocabulary
- `11f2f58` — the severity half, already fixed
