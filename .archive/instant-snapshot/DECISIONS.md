# DECISIONS   (durable; append-only; the WHY behind anything a reader would otherwise re-litigate)

## D-1 the briefs live in `evidence/issues/`, and ISSUES.md indexes rather than summarises
The operator asked for *"exhaustive self contained context under evidence/issues/"*. Each brief carries
the symptom with its verbatim quotes, the measurements, the code locations, what has already been fixed
nearby, what a fix must decide, and how to know it is closed — so a reader needs neither the parent
instant, nor the quanton registers, nor this session's transcript.

**Why the index does not summarise:** a summary is a second copy that drifts. `II-3` was two registries
nothing kept in step; `II-7` described a case that had passed, because it was written from an aggregate
row instead of the source. An index pointing at one authority cannot disagree with it.

## D-2 the parent instant stays inflight and keeps the monitoring duty
This instant owns CLOSURE of six named gaps. The parent
(`00000000-08021753-inflight-append-quantonFeedbackAndReleases`) keeps the standing duty of monitoring
the two quanton registers for new findings.

**Why not complete the parent:** its acceptance criteria are met, but its duty is ongoing rather than
finishable. Renaming it `-complete-` would say the monitoring stopped, which is false. Splitting closure
out means design work does not block a monitoring loop, and a monitoring loop does not hold six design
questions open.

## D-3 `G-3` and `G-4` are re-confirmed as deferred until brainstormed
Carried from the parent's `D-4` (operator, 2026-08-03: *"3 and 4 document it for now"*). They are now
DOCUMENTED — full briefs, which they did not have when that decision was taken; they existed only as
one-line triage rows and the description lived in a register read-only to this effort.

**Do not implement them opportunistically while working nearby.** Both change what an existing state or
verb MEANS mid-effort.

## D-4 the `A-1` re-measure is a runnable gate, not an instruction (2026-08-03, ACTIVE)
**Context.** `A-1` said "before starting a gap, re-run the measurement its brief quotes — each one names
the exact command". That is an instruction to a human, and it was about to be followed by hand for the
fourth time. Three findings in this line of work evaporated on re-measure (`FI-8`, half of `FI-11`,
`FI-3`); the discipline is proven, its execution was not repeatable.

**Decision.** `bin/reverify-briefs.sh` re-derives the CORE premise of every open brief in one command, one
row per gap, non-zero exit if any premise moved or was refuted. `evidence/INDEX.md` cites it as `A-1`'s
artifact. Running it is the first action of any session that intends to work a gap.

**Rationale.** Working method rule 6 — *prefer a reusable mechanism to an ad-hoc script* — and the
observation that "re-measure first" survives exactly as long as the session that remembers it. It also
paid for itself immediately: it refuted `A-2` and found `G-7`'s false premise sitting in shipped source,
neither of which the by-hand reading of the same briefs had noticed.

**Consequences.** A new gap must add a row to the script, or it is outside the gate. The script is itself a
check with no control (`G-9`) — recorded before its verdict was relied on, not after. Two of its ten rows
assert an ABSENCE and are the likeliest to be vacuously green.

## D-11 coordinators are nudged too, with their own text, keyed on the DECLARED profile kind (2026-08-03, ACTIVE)
**Context.** Operator, 2026-08-03: *"coordinator should be nudged as well when eligible. it should read all
parked state and other eligible state to unblock workers."* The design had assumed the target was always a
worker — wrong, and it misses the case the original report actually described: *"coordinator is also not aware
so the entire system stuck forever"*. A stalled coordinator gates every worker under it, so it is the higher-
consequence target, not an afterthought.

**Decision.** The nudge predicate is UNCHANGED (a stalled instant is a stalled instant); the **text** is
selected by the target's profile kind, read from `Profile.load(rec.profile).kind` and surfaced as
`subject.evidence["profile_kind"]`.
- `coordinator` → text pointing at the actionable population: read the board, ANSWER parked children, unpark.
- `worker` / `compaction` → the worker text.
- **kind unreadable** → the worker text, and the report row SAYS the kind could not be read.

**Rationale.** The kind is a DECLARED field: `profiles.Profile.load` raises rather than defaults, because a
kind inferred from prose once made five shipped profiles silently fall back to `worker` (`OBS-5`/`OBS-64`) —
*"a kind-aware linter that picks the wrong kind is worse than no linter, because it converts 'unchecked' into
'checked and fine'."* So the kind is read from the manifest, never guessed from the folder name, the title or
the charter's prose. It goes in `evidence` rather than `Subject.kind` because `reconcile.KINDS`
(`worker`/`unknown-session`/`stale-lease`) is a different axis — the row kind of the JOIN, not the profile —
and conflating two closed vocabularies that share a name is a trap.

An unreadable kind defaults to the WORKER text in the safe direction: the worker text tells a coordinator to
park a question it has no one to send to (harmless), whereas the coordinator text would tell a worker to go
unblock workers it does not have (confusing). Defaulting is still REPORTED, so it never becomes silent.

**Consequences — and this is the honest limitation.** Nudging requires a dispatch record, so **only
DISPATCHED instants are nudgeable.** A top-level coordinator has no record — `_do_init`'s own comment states
it: *"at `init` time there is no record"*. Such a session is either invisible to `reconcile` or classified
`unknown-session`, which the package reports and NEVER touches (*"some of those sessions are people's"*).
So the operator's own hand-started coordinator will not be nudged, by design, and that must be stated in the
spec rather than discovered. Dispatched coordinators — the `v2stackcoordinator` shape — are covered.

Reporting orders coordinators first, since a stalled coordinator gates the workers beneath it.

## D-10 `awaiting-ci` requires a LIVE WATCHER, refused at the producer and re-checked at the consumer (2026-08-03, ACTIVE)
**Context.** Operator, 2026-08-03: *"for AWAITING-CI let's also add extra condition that the claude session
must come with watchers. a session with no watchers is not waiting for anything."*

The hazard is structural and worse than the other two states'. `AWAITING-CI` is decided at branch 2 of
`_live_state`, **before** `busy` (3) and before the idle threshold (4). So a declared CI wait can never decay
into `IDLE`, therefore never enters `ACTIONABLE_STATES`, therefore is never nudged and never counted in
"N needs you" — **and** per `coordinating-instants` the declaration frees the WIP cap, so the coordinator
dispatches the next milestone and stops thinking about it. It is the only state that suppresses the detector
that would otherwise catch it. A session that declares it and then simply stops waits forever, silently, with
its own declaration as the thing hiding it.

**Decision.** A phase declaration of `awaiting-ci` must name a watcher, and the state holds only while that
watcher is alive. Both halves, deliberately:
- **At the producer:** `fleet declare phase awaiting-ci` REFUSES without a live watcher reference. Same idiom
  as *"an empty park is not a park"* and `propose`'s mandatory evidence — a declaration nothing backs is
  refused where it is made.
- **At the consumer:** `_live_state` treats an `awaiting-ci` phase whose watcher is NOT alive as absent, so
  derivation falls through to `busy`/idle as if nothing had been declared. A stale declaration stops lying
  rather than needing a cleanup.

**Rationale.** Liveness needs no new machinery: `pool._live_pid` already reads `/proc/<pid>` and is injectable
(`pid_alive`), and `session.default_probes` already reads `/proc` for every cwd and cmdline — so this adds no
platform assumption and no new subprocess seam. Fails in the safe direction: a dead or absent watcher makes a
worker MORE visible, never less.

**Alternatives rejected.** (a) *Any live descendant of the pane's pid* — no schema change and no worker
cooperation, but it is process-shape matching, wrong in both directions (a stray `sleep` counts; a detached
watcher does not), and this codebase's own hard-won lesson is *"never match a NAME PATTERN to find your
workers"*. (b) *Ask `gh` whether the run is still in progress* — semantically the ideal test, and rejected on
architecture: `reconcile` is a pure local read-only join called by every view, and putting a network call
inside it would make `board` slow and failable. The run URL is still worth recording as evidence for a human;
it is just not what liveness is checked against.

**Consequences.** `declare.json` gains a watcher field, so the schema, the worker skill
(`working-as-a-dispatched-instant`) and BOTH charter templates (`worker`, `compaction`) must teach it — the
templates were freshly edited by `FI-13`, so check `git log` before touching them. Declarations already on
disk carry no watcher and are therefore treated as unwatched: nothing breaks, and the grandfathered ones stop
suppressing detection, which is the intended direction. This also means a legitimately-waiting worker whose
watcher dies becomes nudgeable — correct, because nobody is going to wake it.

## D-9 `G-11` is folded into the `G-1`+`G-2` piece (2026-08-03, ACTIVE)
**Context.** `G-11` (a parked question is not in `ACTIONABLE_STATES`, so it reaches nobody) was found while
designing the nudge. Operator folded it in: *"g-11 let's fold into this piece."*

**Decision.** `PARKED` joins `ACTIONABLE_STATES` as part of this work, so a child's blocking question counts in
"N needs you" the moment it is asked rather than after a 30-minute timeout that mislabels it `IDLE`.

**Rationale.** It is the same defect family as `FI-14` and it is in the code this work already touches;
splitting it would mean two passes over one tuple. And it composes with the nudge rather than conflicting: the
nudge must not touch a parked child (`D-8`), while this makes that child visible — together they are the
behaviour the operator described (coordinator engages and answers; the child is never told to just continue).

**Consequences — and this one is load-bearing.** This is the **THIRD** change to `ACTIONABLE_STATES`
(`FI-14` widened it 2026-08-02; `G-4` would change it again). The standing constraint applies:
**measure the attention count on a real board before and after**, or a regression in the counter is
unattributable. That measurement is a gate on this work, not a nice-to-have. `G-4` remains deferred and its
question — splitting `BLOCKED` — is untouched by this.

## D-8 nudge eligibility is a STATE **and** the absence of a park — not a state alone (2026-08-03, ACTIVE)
**Context.** The design as first presented used `NUDGEABLE_STATES = (IDLE,)`. The operator asked whether a
child that legitimately asks the coordinator a question and waits would get nudged, since the real unblock is
an answer. Measured with `bin/probe-nudge-eligibility.sh`: **it would.** A parked child past the idle
threshold comes back `state=IDLE`, because `_live_state` APPENDS the park to the note and leaves the state
actionable. A state-only filter cannot see a park.

**Decision.** Eligibility is `state == IDLE` **and** `not subject.evidence["parked"]`. The park is already on
the subject (`reconcile.py:233`), so this needs no new plumbing — only that the filter read it.

**Rationale.** A nudge is *"continue where you left off"*. To a child blocked on a decision that is not just
useless, it is harmful: it invites the child to proceed without the answer, which is the guessing failure
`G-3` is separately about. The child did the right thing by parking; nudging punishes it.

**Consequences.** `NUDGEABLE_STATES` alone is not the contract, so the verb must not be written as a
membership test — and a test must cover the parked-and-idle case specifically, or the regression is invisible
(the state looks nudgeable). Making the parked question VISIBLE to the coordinator is a different gap
(`G-11`) and is NOT solved by this decision; this only guarantees `fleet` does not send the wrong remedy.

## D-7 the nudge loop is a `fleet` verb called by the EXISTING watchdog loop (2026-08-03, ACTIVE)
**Context.** `G-2` needs a heartbeat and `fleet` is passive by design — verbs that compute and print. Three
hosts were considered: the existing `claude-watchdog.sh` loop, a new independent setsid loop, or a
fleet-owned daemon. Operator chose the first.

**Decision.** `fleet nudge` owns the DECISION (which subjects are actionable) and the DELIVERY (the gated
send). `scripts/claude-watchdog.sh`'s existing `$INTERVAL` loop calls it. `fleet` stays a process that starts,
does one thing and exits.

**Rationale.** The watchdog has already solved — and had shaken out in production — single-instance guarding,
a pidfile, per-tmux-server scoping, and an exclude list. Re-solving those inside `fleet` is the ad-hoc-script
failure inverted: rebuilding a mechanism that exists. Keeping the judgement in the verb keeps it under the
package's tests, which is the half `G-10` proves matters.

**Consequences.** The watchdog gains a second duty unrelated to supervising node monitors — accepted
knowingly; it must be commented as such so a later reader does not "tidy" it away. A `fleet nudge` failure
must not be able to break auto-resume: the call has to be non-fatal in that loop (`|| true`-shaped), and that
is now a requirement of the design rather than a detail. It also means the nudge cadence is the watchdog's
`$INTERVAL`, not a value `fleet` picks — so back-off has to live in the verb, which cannot assume how often
it is called.

## D-6 real-claude probes need no per-run approval in this session (2026-08-03, ACTIVE)
**Context.** `live-pane.sh start` refuses a real claude unless `FLEET_ALLOW_LIVE_CLAUDE=1`, because it spends
the account's weekly allowance. `A-6`/`RA-1` could only be closed with one, so it was raised as a blocking
question. Mid-run the operator removed the block: *"also in this session, never block on claude allowance
again, you are allowed."*

**Decision.** Live probes are authorised for the remainder of this session without asking. The mechanical
guards are UNCHANGED and are not the operator's to waive casually: private socket only, `itfleet-probe-*`
names only, never the default tmux server, never a `dt-` session. `FLEET_ALLOW_LIVE_CLAUDE=1` still has to be
set deliberately per invocation — it is now an acknowledgement rather than a question.

**Rationale.** The allowance is the operator's to spend, and the alternative was carrying `RA-1`-shaped
assumptions into a design. Closing `RA-1` immediately paid for itself: it showed the race is intermittent
(1/5, not a rule) and that `pane-guard` after the type predicts the outcome 12/12 — the second of which is
the strongest argument the delivery verb has, and neither was visible from the carried-over table.

**Consequences.** `CHARTER.md`'s scope line no longer excludes real-claude work. Remaining pane-level
assumptions (`A-5` under load) are now answerable rather than blocked. The authorisation is scoped to THIS
session; a later instant re-reading this must not treat it as permanent.

## D-5 the two deltas amend the briefs in place; they are not new gaps (2026-08-03, ACTIVE)
**Context.** Re-measuring produced two corrections: `A-2` refuted (`G-1`'s six-send-paths count has no
source) and `G-7`'s false premise found in `roadmap.py`'s docstring. Both could have been filed as new
findings `G-10`/`G-11`.

**Decision.** They are appended to the affected briefs as dated `§Na` sections — `G-1` §6a, `G-7` §5a — and
indexed here and in `ISSUES.md`. No new gap ids. The count stays at eight gaps plus `G-9` (a defect in this
instant's own tooling, which is genuinely new).

**Rationale.** `D-1`: the brief is the record, and a reader of `G-1` must not be able to miss that its
central number is unsourced. A separate finding would be a second home for the same fact — `II-3`'s shape.
A correction to a premise belongs *inside* the artifact whose premise it is.

**Consequences.** The briefs are no longer purely as-written-2026-08-03; each amended one is dated and
marked. `AC-3` ("the briefs stay true") now has partial machine coverage via `D-4`'s script.
