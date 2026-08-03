# Fleet open-gap closure — CHARTER   (durable; edit deliberately)
Instant: 00000000-08030228-inflight-append-fleetOpenGapClosure

## Goal (e2e)
Close the eight gaps that survived the 2026-08-02/03 fleet work. Each is OPEN for a stated reason — four
were deferred as design work, one is an untouched acceptance criterion, one was found while checking
whether the release pipeline was documented at all. This instant exists to finish them, not to find more.

## Setup to begin with
- Base instant: `00000000-08021753-inflight-append-quantonFeedbackAndReleases` (the parent, still
  inflight — it keeps the standing duty of MONITORING the two quanton registers; closure of these six
  moved here so a monitoring effort is not blocked on design work).
- Code: `/home/ubuntu/davis_root/superpowers`, branch `live`, pushed to
  `ssh://git@github.com/Davis-Zhang-Onehouse/superpowers.git`. **Everything is in that one repo** —
  21 package modules, all tracked, no untracked files.
- Releases: `/home/ubuntu/davis_root/fleet-releases`. `FLEET_HOME=/home/ubuntu/.fleet`.
  Latest RELEASED is `0.3.1`; `current` → the checkout (DEV).
- The gate works and is trustworthy as of `0.3.1`: `run-all.sh` returns a real verdict, the IT suite no
  longer reports harness gaps as product defects, and `release-verify` runs the suite from a `git
  worktree` at the tag.

## The eight gaps
Each has an EXHAUSTIVE, SELF-CONTAINED brief in `evidence/issues/`. A reader should need nothing else —
not the parent instant, not the quanton registers, not this session's transcript.

| id | brief | one line | why it is open |
|---|---|---|---|
| `G-1` | `evidence/issues/G-1-pane-delivery-verb.md` | no `fleet` verb owns pane delivery; six send paths each implement it | deferred `D-4` |
| `G-2` | `evidence/issues/G-2-stall-loop-actuation.md` | fleet DETECTS an idle worker and nothing ACTS on it | not tracked until 2026-08-03 |
| `G-3` | `evidence/issues/G-3-dispatch-scope-race.md` | `dispatch` renders the charter and launches in one call | deferred `D-4` |
| `G-4` | `evidence/issues/G-4-blocked-discriminator.md` | `BLOCKED` cannot tell a stuck worker from an attached human | deferred `D-4` |
| `G-5` | `evidence/issues/G-5-every-case-can-fail.md` | AC-2: no case is shown to FAIL when its subject breaks | frame built, mutations not started |
| `G-6` | `evidence/issues/G-6-release-pipeline-undocumented.md` | ~~8 release verbs, zero operator docs~~ | **CLOSED `d07b4a2`** |
| `G-7` | `evidence/issues/G-7-refusal-names-no-route.md` | a refusal names its rule but not the route; **corrects a false claim I shipped** | `FI-16`, 2026-08-03 |
| `G-8` | `evidence/issues/G-8-no-status-closes-and-satisfies.md` | no terminal status both closes honestly AND satisfies dependents | `FI-17`, 2026-08-03 |

**Ordering, impact and effort: `PRIORITIES.md`.** In short — `G-1`+`G-2` are one loop and must be
taken together; `G-4` gates `G-2`'s safety and carries the highest risk-of-fixing; `G-5` measures the
instrument everything else is verified by; `G-3` is real but least urgent and has a cheap 80%.

## Scope
- IN: the eight gaps above (seven open — `G-6` closed `d07b4a2`), to closure, each red→green with a control
  where it touches a check. Also `G-9` (`ISSUES.md`), a defect in this instant's own tooling: the same rule
  applies to a check we write as to one we fix.
- OUT: finding new product defects (that is the parent instant's monitoring duty); the quanton efforts'
  own work.
- **Real `claude` probes are AUTHORISED without asking (operator, 2026-08-03: _"in this session, never block
  on claude allowance again, you are allowed"_).** Still only through `live-pane.sh` — private socket, never
  the default server, never a `dt-` name. See `D-6`.

## Working method (inherited, non-negotiable)
1. **systematic-debugging**: reproduce and RCA before fixing; every claim a cited fact or a flagged
   assumption. A hypothesis that explains the symptom and cites the source is a CANDIDATE, not evidence.
2. **TDD red→green→refactor.** The failing test is SEEN to fail against shipped behaviour first, and the
   failure COUNT is checked — three times in two days a filter or fixture made a test pass vacuously.
3. **A release every few fixes.** Cut → verify → triage every FAIL row → promote. Never promote over an
   unexplained red.
4. **Push after every commit** (standing instruction, 2026-08-03).
5. **One IT job at a time.** Concurrent runners contaminated a run in this line of work already.
6. **Prefer a reusable mechanism to an ad-hoc script.** Three times an ad-hoc script broke a rule that
   already existed in a tool.

## Acceptance criteria
### AC-1 every gap is closed or explicitly re-deferred with a reason
- [ ] Proof: each `evidence/issues/G-*.md` ends with a Status of FIXED (naming the commit and the
      control) or DEFERRED (naming who decided and why). No gap left silently open.

### AC-2 nothing regresses
- [ ] Proof: a GREEN `release-verify` on a release cut after the last fix, with every FAIL row on the
      way attributed before promotion.

### AC-3 the briefs stay true
- [ ] Proof: on close-out, each brief's "current state" section matches the tree. A brief that describes
      a fixed defect as open is the doc-rot this line of work has hit twice (`II-7`, `FI-3`).
- Partial machine coverage since `D-4`: `bash bin/reverify-briefs.sh` re-derives each brief's CORE premise
  every run and exits non-zero if one moved. It does not cover a brief's whole body, so this criterion is
  not discharged by a green run — and the check itself has no control yet (`G-9`).

## Standing constraints
- **NEVER create, kill or write a `dt-` session** on the default server.
- Never touch `~/.claude-dispatch-board`, `~/.claude-ws-pool`, or another effort's instant.
- **Never weaken an assertion to obtain a green.** A case that cannot pass is reported as one.
- Every fix to a check ships with a control proving the check still fails when it should.
- Evidence into this instant by RELATIVE path, never `/tmp`.
