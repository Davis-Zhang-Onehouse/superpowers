"""Admission control — the rules a lifecycle verb must pass, and the ONE shape of their answer.

**A guard here can be asked without being triggered.** `evaluate` answers "would this be admitted?" and
writes nothing: not a lease, not a record, not a declaration, not a file. That is not a convenience. *"A
guard you cannot interrogate non-destructively gets interrogated destructively"* — twice, by two actors,
one of whom had **read and cited** the entry that declined to run that exact command. The probe's failure
mode is *doing the thing you were checking you could not do*, and it fires precisely when the freeze has
lifted: a capacity probe that claims a lease to find out leaves no trace at all while the pool is full,
and takes somebody's slot the moment one is free. So `PoolCapacity` counts unleased slots and never
claims one, and `tests/test_guards.py` diffs the filesystem, the record store and the pool around every
probe.

**`enforce` never re-implements `evaluate`.** `Guard.enforce` is defined once, on the base class, and its
whole body is "evaluate, then raise if the verdict said no". Two code paths for one rule is how the two
drift, and a rule that answers differently depending on which door you knocked at is worse than either
answer. `enforce_all` likewise consumes `evaluate_all`'s verdicts rather than re-walking the guards.

**Two admission rules, kept structurally apart.** The WIP cap counts *active-dev* subjects (default 1) and
excludes declared CI-waiters; a compaction is *exclusive* and blocks every dispatch even at zero active-dev,
because its cost is unfoldable rebase debt rather than attention. *"Folding rule 2 into rule 1 gets exactly
one of those two cases wrong, whichever way you fold it."* They are separate classes, each reporting its own
`Verdict`, because *"'the cap says I have room' is not an answer to 'may I dispatch?'"*

**Every control signal is structured state.** The phase comes from `store.Declarations` through the one
join in `reconcile`; a `HANDOFF.md` that *talks* about `Phase: AWAITING-CI` changes nothing (`RCF-9`), and
neither does a quiet pane. The profile's kind comes from `profile.json` via `profiles`, never from charter
prose. No `.md` file is opened in this module at all.
"""
from dataclasses import dataclass, replace
from pathlib import Path

from fleet.errors import BadInput, InstantNameError, NoCapacity, Refused
from fleet.identity import InstantName
from fleet.profiles import OPTYPES_OF_KIND, Profile, agrees_with_optype
from fleet.reconcile import AWAITING_CI, COMPLETE, KIND_WORKER, PENDING_LAUNCH, Subject, reconcile

#: A guard's failure DIRECTION, part of the contract rather than a comment (`FR2-11.6`). An
#: under-triggering guard's worst day is a coordinator asking a question it did not need to ask; a
#: mis-triggering guard's worst day is a refusal nobody can clear.
UNDER_TRIGGERS, MIS_TRIGGERS = "under-triggers", "mis-triggers"

#: `MD-6`. One dev slot per effort unless a caller says otherwise out loud, through `Context.cap`.
DEFAULT_WIP_CAP = 1

#: The only states the cap excludes. Everything else counts — including `DEAD` and `PENDING-LAUNCH`,
#: deliberately: a stopped worker's half-finished tree is exactly what a second dispatch collides with,
#: and inventing an exemption for it is the silent slot leak this direction exists to avoid.
CAP_EXCLUDED_STATES = (AWAITING_CI, COMPLETE)

#: Verbs no admission rule is evaluated for. `OI-2`/`MD-9.2`/`FD-9`, and the reason is recorded below
#: rather than left to be re-derived: rev 1 of the design deleted this door entirely (`FI-8`) precisely
#: because the row explaining it had gone missing.
EXEMPT_FROM_ADMISSION = {"resume"}

#: Why each exemption exists, in the module, next to the set. An exemption whose reason lives only in a
#: review comment is an exemption the next rewrite drops.
EXEMPTION_REASONS = {
    "resume": ("`resume` adopts an instant that already exists; it is resume, not dispatch, and refusing "
               "a recovery path is its own outage — the alarm that blocks the fix. `OI-2`/`MD-9.2` keeps "
               "this as an accepted risk whose reason must survive every refactor, and design §10's "
               "'no alarm blocks a documented recovery path' is only true if this door stays open. The "
               "residual bypass (hand-create an instant, then resume it) is accepted knowingly."),
}

#: The guard name reported for an exempt verb, so `evaluate_all` still answers with a `Verdict` and the
#: exemption is visible in the output rather than being an empty list a caller has to interpret.
EXEMPTION_GUARD = "admission-exemption"

#: `reconcile` marks an instant it could not find on disk with this suffix. Read here so a compaction
#: whose folder is missing is still recognised as a compaction from the name the record carries.
_MISSING_SUFFIX = " (missing)"

_EMPTY_OVERRIDE = (
    "an override needs a stated reason, and \"\" is not one. This is not the ordinary refusal: that "
    "refusal's remedy is \"give a reason\", and a caller who passed an empty reason has already done "
    "what it asked — telling someone to do the thing they just did sends them in a circle (`OI-3`). "
    "Either pass a reason a reader can audit, or clear the rule the honest way."
)


@dataclass(frozen=True)
class Verdict:
    """One answer to "may I proceed", from any rule in the package.

    `clears_when` and `clears_who` are the alarm contract (design §9): every refusal names the condition
    that clears it AND the actor who can clear it, because *"not yours to clear" is a state, not a
    failure* (`RI-31`). `blocker` names the concrete thing in the way, so the reader can act without
    first working out what the sentence is about.

    Reused by `review.gate()` rather than duplicated there: two verdict types is how two callers start
    disagreeing, and a caller that must branch on which verdict it got is a caller that will branch wrong.
    """

    allowed: bool
    guard: str
    reason: str
    clears_when: str | None = None
    clears_who: str | None = None
    blocker: str | None = None


@dataclass(frozen=True)
class Context:
    """Everything a guard reads, and nothing it may write.

    The four state sources arrive injected (`FD-6`), so the suite describes a fleet without owning one.
    `subjects()` calls the ONE join every time rather than caching: a cached answer is a stale premise,
    and *"a report that instructs action on a stale premise"* is the shape three of the predecessor's
    bugs shared.
    """

    store: object
    pool: object
    sessions: object
    instants_dir: Path
    base: str = ""
    #: The WIP cap, said out loud. `None` means "whatever the guard's default is".
    cap: int | None = None
    #: The profile being dispatched, as a `profiles.Profile` or a path to one. `None` when the verb
    #: carries no profile, in which case the agreement guard reports what it could not check.
    profile: object = None
    optype: str | None = None
    #: `None` = no override asked for. `""` = an override asked for with no reason, which is BAD INPUT
    #: and not a refusal. A non-empty string overrides the rules that would have refused, and is quoted
    #: back in the verdict so the audit trail carries it.
    override_reason: str | None = None
    #: The slot this caller has ALREADY CLAIMED, when it is asking a second time while holding the claim
    #: (`FI-21`). Empty on the ordinary advisory pass. Setting it is what turns "may I?" from a question
    #: about records — which cannot be settled by a read, because the record is written after the gate —
    #: into a question about the ordered claim list, which is atomic. It never makes a guard write
    #: anything: the claim was taken by the caller, and this field only tells the guards whose it is.
    claim: str = ""

    def subjects(self) -> list:
        return reconcile(self.store, self.pool, self.sessions, self.instants_dir)

    def under_claim(self, slot: str) -> "Context":
        """The same context, asking as the holder of `slot`. Reads only; writes nothing."""
        return replace(self, claim=str(slot))


# --- the base class: one evaluate per rule, one enforce for all of them ----------------------------


class Guard:
    """A rule. Subclasses implement `_decide` and inherit `evaluate`/`enforce`.

    `name`, `direction` and `cost_on_pass` are contract, not documentation. `cost_on_pass` exists
    because of a probe that was free while a guard was armed and a **full dispatch** the moment it was
    not, with nothing in its text saying so (`FR2-11.6`/`W2-27`): what it costs to ask when the answer is
    yes is the fact a caller needs before it asks.
    """

    name = ""
    direction = ""
    cost_on_pass = ""
    #: The error class `enforce` raises. `NoCapacity` (3) and `Refused` (4) are different answers with
    #: different remedies, and a caller must be able to tell a full pool from a policy refusal.
    raises = Refused
    #: Whether HOLDING a claim already answers this rule. `FI-21`'s second pass runs while the caller owns
    #: a lease, and for the pool that is not a question any more — the slot is in its hand. A rule that
    #: says "yes" to the first pass and "the pool is full" to the second would refuse a dispatch for
    #: having succeeded at the very thing it was asking about.
    settled_by_claim = False

    def evaluate(self, ctx) -> Verdict:
        """The rule, non-destructively. Reads state; writes nothing, ever."""
        overridden = _override_in_force(ctx)
        verdict = self._decide(ctx)
        if verdict.allowed or not overridden:
            return verdict
        return replace(
            verdict, allowed=True,
            reason=(f"overridden by hand: {ctx.override_reason.strip()} — the rule said: "
                    f"{verdict.reason}"))

    def _decide(self, ctx) -> Verdict:
        raise NotImplementedError(f"{type(self).__name__} states no rule")

    def enforce(self, ctx) -> None:
        """The rule, enforced. THE ONLY body here is "ask `evaluate`, then raise" — a second derivation
        of the same rule is how `evaluate` and `enforce` come to disagree about one cell."""
        self.raise_for(self.evaluate(ctx))

    def raise_for(self, verdict: Verdict) -> None:
        if verdict.allowed:
            return
        if issubclass(self.raises, Refused):
            error = self.raises(verdict.reason, clears_when=verdict.clears_when,
                                clears_who=verdict.clears_who)
        else:
            error = self.raises(verdict.reason)
            error.clears_when, error.clears_who = verdict.clears_when, verdict.clears_who
        error.verdict = verdict
        error.blocker = verdict.blocker
        raise error


# --- rule 1: the WIP cap --------------------------------------------------------------------------


class WipCap(Guard):
    """How many subjects of this effort are consuming attention right now.

    Excludes declared CI-waiters and nothing else. **The declaration is the whole bargain**: at a cap of
    1, an undeclared waiter holds the effort's only dev slot for the length of a CI queue, so the
    exclusion is bought by running `fleet declare --instant <instant> --phase awaiting-ci` and by nothing else — not by a quiet
    pane, and not by a line of `AWAITING-CI` prose in a handoff (`RCF-9`). That is the stated direction:
    it under-triggers, so its worst day is a coordinator asking a question, never a silent slot leak.
    """

    name = "wip-cap"
    direction = UNDER_TRIGGERS
    cost_on_pass = ("free — it counts subjects the one join already produced. Allowing costs no lease, "
                    "no record, no session and no keystroke, so it is safe to ask before every dispatch "
                    "and safe to ask twice.")

    def __init__(self, cap=None):
        self.cap = DEFAULT_WIP_CAP if cap is None else cap

    def _decide(self, ctx) -> Verdict:
        cap = self.cap if ctx.cap is None else ctx.cap
        workers = _workers(ctx)
        claims = _claims_in(workers)
        counted = [s for s in workers if _counts_against_cap(s)]
        excluded = [s for s in workers if not _counts_against_cap(s)]
        held = ", ".join(_instant_name(s) or s.identity for s in counted) or "nothing"
        spare = ", ".join(f"{_instant_name(s) or s.identity} ({s.state})" for s in excluded)
        population = (f"examined {len(workers)} subject(s) of {ctx.base or 'every base'}"
                      + (f", {len(claims)} of them claims held ahead of {ctx.claim!r}" if claims else "")
                      + f"; {len(counted)} counted, {len(excluded)} excluded"
                      + (f" ({spare})" if spare else ""))
        if len(counted) < cap:
            return Verdict(allowed=True, guard=self.name,
                           reason=f"{len(counted)} of {cap} active-dev slot(s) in use. {population}")
        return Verdict(
            allowed=False, guard=self.name,
            reason=(f"the WIP cap is {cap} and {len(counted)} active-dev subject(s) hold it: {held}. "
                    f"{population}"),
            clears_when=("one of those subjects completes, or declares `fleet declare --instant "
                         "<instant> --phase awaiting-ci` — the declaration is the only channel; prose "
                         "and a quiet pane are not"),
            clears_who=held,
            blocker=held)


def _counts_against_cap(subject) -> bool:
    """Whether one subject occupies a dev slot.

    A state, and only a state — from the one join, which reads the phase through `Declarations`. Nothing
    here looks at the pane: inferring AWAITING-CI from a quiet pane is how an undeclared waiter's slot
    leaks silently, and a guard that guesses this fact right most of the time converts *"undeclared"*
    into *"declared and fine"*.
    """
    return subject.state not in CAP_EXCLUDED_STATES


# --- rule 2: a compaction is exclusive ------------------------------------------------------------


def blocking_compactions(ctx) -> list:
    """Every unfinished compaction of this effort, from BOTH places one can exist.  `SI-30`.

    -> a sorted list of instant NAMES.

    The bug this exists to fix. `CompactionExclusive` read only `_workers(ctx)` — the reconciled join over
    records, leases and live processes — so a compaction that exists **as a folder with no record** was
    invisible, and measured: `fleet init --optype compact` produced `…-inflight-compact-ondiskcompact`, the
    store held 0 records, the next `fleet dispatch` was **ADMITTED at exit 0**, and `compaction-status`
    reported *"no compaction of this effort is inflight"*. Confidently wrong, because it had examined
    records and the question was about the disk.

    Why that path is not hypothetical: `superpowers:maintain-workspace`'s compact operation says *"Create
    `<base>/main-<MMDDHHMM-now>-inflight-compact-<name>/`"*. A folder. No record. That is the documented way
    a compaction instant is born in this system, and it was exactly the case the freeze could not see.

    And it broke this guard's own promise. Its `direction` is `MIS_TRIGGERS` and its docstring says it
    *"will refuse a dispatch that would have been harmless rather than admit one that lands work under a
    compaction, because the second is unrepairable after the fact"*. For an on-disk-only compaction it
    **under-triggered** — the one direction it had declared it would never take, toward the outcome it calls
    unrepairable. A declared direction that the implementation can violate is worse than an undeclared one.

    Two vocabularies, deliberately not unified. A recorded subject carries a RECONCILE state (`RUNNING`,
    `DEAD`, `AWAITING-CI`, `COMPLETE`) and is blocking while it is not `COMPLETE`; a folder carries an
    INSTANT state (`inflight`, `complete`, `abort`) and is blocking only while `inflight`. Collapsing them
    into one word is how `OI-17` happened — a hardcoded value of a parsed field, after which every correct
    compaction rendered `(missing)`.
    """
    names = set()
    for subject in _workers(ctx):
        if _optype_of(subject) == "compact" and subject.state != COMPLETE:
            names.add(_instant_name(subject) or subject.identity)
    #: The disk. Read directly rather than by adding a fourth source to `reconcile`: an on-disk instant holds
    #: no slot, so `board` — "every subject HOLDING A SLOT" (FD-4) — would not show it anyway, and widening
    #: the join to serve one guard would change every view that reads it.
    if getattr(ctx, "instants_dir", None):
        root = Path(ctx.instants_dir)
        if root.is_dir():
            for entry in sorted(root.iterdir()):
                if not entry.is_dir():
                    continue
                try:
                    parsed_name = InstantName.parse(entry.name)
                except InstantNameError:
                    #: A directory that is not an instant name is not an instant. Skipped, not refused: the
                    #: instants directory is allowed to contain other things.
                    continue
                if parsed_name.optype != "compact" or parsed_name.state != "inflight":
                    continue
                #: Per-effort, matching `_workers`: another effort's compaction is that effort's rebase debt.
                if ctx.base and parsed_name.base != ctx.base:
                    continue
                names.add(entry.name)
    return sorted(names)


class CompactionExclusive(Guard):
    """An inflight compaction blocks every dispatch, at any cap, in any state short of done.

    Kept structurally apart from the cap, because the two come apart in practice: a compaction that is
    **awaiting CI** costs no attention and therefore does not count against the cap, and still blocks
    everything, because what it holds is an unfoldable rebase against a moving tree rather than a
    reviewer's time. *"Folding rule 2 into rule 1 gets exactly one of those two cases wrong, whichever
    way you fold it."*

    It mis-triggers by choice: it will refuse a dispatch that would have been harmless rather than admit
    one that lands work under a compaction, because the second is unrepairable after the fact while the
    first clears the moment the compaction renames its folder.
    """

    name = "compaction-exclusive"
    direction = MIS_TRIGGERS
    cost_on_pass = ("free — it reads the opType out of instant names the one join already resolved, and "
                    "touches no lease and no session whether it allows or refuses.")

    def _decide(self, ctx) -> Verdict:
        workers = _workers(ctx)
        claims = _claims_in(workers)
        #: `SI-30`: records UNION disk, through the one shared derivation. The population line now says which
        #: sources were consulted, because "examined N subjects, 0 of them compactions" was a true sentence
        #: about the wrong question and there was no way to tell from the output.
        blocking = blocking_compactions(ctx)
        population = (f"examined {len(workers)} recorded subject(s) and the instants directory, for "
                      f"{ctx.base or 'every base'}, {len(blocking)} unfinished compaction(s)"
                      + (f"; {len(claims)} claim(s) held ahead of {ctx.claim!r}" if claims else ""))
        if not blocking:
            return Verdict(allowed=True, guard=self.name,
                           reason=f"no compaction of this effort is inflight. {population}")
        name = blocking[0]
        others = ", ".join(blocking[1:])
        return Verdict(
            allowed=False, guard=self.name,
            reason=(f"the compaction {name} is inflight and a compaction is exclusive: every dispatch "
                    f"waits, even at zero active-dev work, because its cost is unfoldable rebase debt and "
                    f"not attention"
                    + (f". Also inflight: {others}" if others else "") + f". {population}"),
            clears_when=(f"{name} renames its folder to `-complete-` or `-abort-` (the rename is the "
                         "completion signal), or the dispatch is overridden with a stated reason"),
            clears_who=name,
            blocker=name)


# --- rule 3: the profile and the opType must agree ------------------------------------------------


class ProfileOpTypeAgreement(Guard):
    """The declared profile kind and the dispatched opType must be the same decision twice.

    `W2-13`/`OBS-58`: **both** flags that make a compaction a compaction defaulted wrong, on a path taken
    **once**, at a cap of 1, and unrepairable by renaming the instant afterwards. The agreement is a
    table in `profiles` (`OPTYPES_OF_KIND`) — one table, consulted here rather than restated, because a
    second copy of a table is a second answer.
    """

    name = "profile-optype-agreement"
    direction = MIS_TRIGGERS
    cost_on_pass = ("free — it reads `profile.json` and compares two declared fields; it renders no "
                    "charter, writes no instant and starts nothing, pass or refuse.")

    def _decide(self, ctx) -> Verdict:
        if ctx.profile is None or ctx.optype is None:
            missing = ", ".join(part for part, value in (("profile", ctx.profile),
                                                        ("opType", ctx.optype)) if value is None)
            return Verdict(allowed=True, guard=self.name,
                           reason=(f"nothing was checked: no {missing} was supplied to this context, so "
                                   "this guard covered a population of zero and says so"))
        profile = ctx.profile if isinstance(ctx.profile, Profile) else Profile.load(Path(ctx.profile))
        agrees = agrees_with_optype(profile, ctx.optype)
        legal = ", ".join(OPTYPES_OF_KIND[profile.kind])
        if agrees:
            return Verdict(allowed=True, guard=self.name,
                           reason=(f"the profile at {profile.path} declares kind={profile.kind!r}, whose "
                                   f"opType(s) are {legal}; dispatching as {ctx.optype!r} agrees"))
        return Verdict(
            allowed=False, guard=self.name,
            reason=(f"the profile at {profile.path} declares kind={profile.kind!r}, whose opType(s) are "
                    f"{legal}, and the dispatch says opType={ctx.optype!r}. Both flags that make a "
                    f"compaction a compaction once defaulted wrong on a path taken once, and no rename "
                    f"afterwards repairs it — so this disagreement is refused, never coerced (FD-1)"),
            clears_when=(f"the dispatch is re-issued with opType in ({legal}), or with a profile whose "
                         f"declared kind admits {ctx.optype!r}"),
            clears_who="the dispatching coordinator",
            blocker=str(profile.path))


# --- rule 4: the pool ------------------------------------------------------------------------------


class PoolCapacity(Guard):
    """Is there a slot to put this worker in?

    **Counted, never claimed.** A probe that claims a lease to test capacity *is* the destructive
    interrogation this module exists to make unnecessary: it does the thing it was checking it could do,
    and it does it exactly when a slot has just come free. So this reads `free_slots()` and stops.

    Answers with `NoCapacity` (3), not `Refused` (4): a full pool is reaped or enrolled out of, a policy
    refusal is waited out. A caller that cannot tell them apart takes the wrong action.
    """

    name = "pool-capacity"
    direction = UNDER_TRIGGERS
    raises = NoCapacity
    settled_by_claim = True
    cost_on_pass = ("free — it counts unleased enrolled slots and does NOT claim one to find out. "
                    "Claiming to test capacity is the probe that takes somebody's slot the moment the "
                    "freeze lifts, which is the destructive interrogation this split exists to remove.")

    def _decide(self, ctx) -> Verdict:
        slots = list(ctx.pool.slots())
        free = list(ctx.pool.free_slots())
        population = f"examined {len(slots)} enrolled slot(s)"
        if free:
            return Verdict(allowed=True, guard=self.name,
                           reason=f"{len(free)} free slot(s): {', '.join(free)}. {population}")
        return Verdict(
            allowed=False, guard=self.name,
            reason=(f"every enrolled slot is leased ({', '.join(slots) or 'none is enrolled'}). "
                    f"{population}"),
            clears_when=("a lease is released, a stale lease is reaped by its owning base, or another "
                         "workspace is enrolled"),
            clears_who="the base owning a stale lease, or the operator",
            blocker=", ".join(slots) or "an empty pool")


# --- the gate --------------------------------------------------------------------------------------


def guards_for(ctx) -> list:
    """Every admission rule, in the order a caller should hear about them.

    Exclusivity first: it is the answer with the longest remedy and the most expensive miss. Capacity
    last, because "the pool is full" is a resource fact and a policy refusal outranks it — a caller told
    `NoCapacity` would go reap slots while a compaction is the actual reason it cannot dispatch.
    """
    return [CompactionExclusive(), WipCap(), ProfileOpTypeAgreement(), PoolCapacity()]


def evaluate_all(ctx, verb: str) -> list:
    """One `Verdict` per guard, and never a merged boolean.

    *"'The cap says I have room' is not an answer to 'may I dispatch?'"* — the caller gets both rules,
    separately, each naming its own blocker and clearing actor. Writes nothing.
    """
    verb = _verb(verb)
    _check_override(ctx)
    if verb in EXEMPT_FROM_ADMISSION:
        return [Verdict(allowed=True, guard=EXEMPTION_GUARD,
                        reason=f"{verb!r} evaluates no admission rule: {EXEMPTION_REASONS[verb]}")]
    return [guard.evaluate(ctx) for guard in guards_for(ctx)]


def enforce_all(ctx, verb: str, under_claim: bool = False) -> None:
    """Raise on the first rule that says no — from `evaluate_all`'s verdicts, not from a second walk.

    There is exactly one derivation of the answer in this module, and this function consumes it.

    `under_claim` marks the second pass of `FI-21`'s claim-then-verify: the caller has taken the lease and
    is asking again while holding it. Only the rules a held claim does not already answer are enforced
    there — the pool's own capacity is not a question once the slot is in your hand.
    """
    verdicts = evaluate_all(ctx, verb)
    by_name = {guard.name: guard for guard in guards_for(ctx)}
    for verdict in verdicts:
        if verdict.allowed:
            continue
        guard = by_name.get(verdict.guard, Guard())
        if under_claim and guard.settled_by_claim:
            continue
        guard.raise_for(verdict)


# --- helpers ---------------------------------------------------------------------------------------


def _verb(verb) -> str:
    if not isinstance(verb, str) or not verb.strip():
        raise BadInput("a gate is evaluated for a named verb; got nothing to evaluate")
    return verb.strip()


def _check_override(ctx) -> bool:
    """Whether an override was asked for — and a hard stop when one was asked for with no reason.

    Three states, not two: absent (the rules apply), empty (bad input), stated (the rules are overridden
    and the reason is quoted back into the verdict). Collapsing the middle one into either neighbour is
    `OI-3`'s circle: the ordinary refusal's remedy is *"give a reason"*, which an empty-reason caller has
    already done.
    """
    reason = ctx.override_reason
    if reason is None:
        return False
    if not reason.strip():
        raise BadInput(_EMPTY_OVERRIDE)
    return True


def _override_in_force(ctx) -> bool:
    return _check_override(ctx)


def _workers(ctx) -> list:
    """This effort's subjects, from the ONE join — plus, when the caller HOLDS A CLAIM, the claims ahead
    of its own.

    Filtered by base: a WIP cap is per-effort, and another effort's compaction is that effort's rebase
    debt. Unknown sessions and unattributed stale leases are deliberately absent — *"some of those
    sessions are people's"* (`D-6`), and a guard that counts them refuses on evidence nobody can act on.

    The second half is `FI-21`. On the advisory pass (`ctx.claim` empty) this is exactly what it always
    was: records, and nothing a guard could not have read a moment earlier. That is what keeps `evaluate`
    pure and keeps `--dry-run`'s zero-delta contract intact, and both are protected for a measured reason —
    two actors damaged another effort's tree probing a guard. But records cannot settle the cap, because
    the record is written *after* the gate: five dispatchers all read "0 in active dev", all pass, all
    write, and 20 of 20 iterations admitted the wrong number. So the caller claims a lease first — the one
    artifact here that is already atomic — and asks again holding it, and on THAT pass the population also
    contains the claims that rank ahead of its own.
    """
    recorded = [s for s in ctx.subjects()
                if s.kind == KIND_WORKER and (not ctx.base or s.evidence.get("base") == ctx.base)]
    if not ctx.claim:
        return recorded
    return recorded + _claims_ahead(ctx, recorded)


def _claims_ahead(ctx, recorded: list) -> list:
    """The won-but-unrecorded claims of this effort that rank BEFORE this caller's own.

    Three things make this the right population, and each one is a way of getting it wrong:

    *Won-but-unrecorded.* A claim whose record exists is already in `recorded`, so counting it again would
    double it — and would defeat the `AWAITING-CI` exclusion, whose whole bargain is that a *declared*
    waiter stops costing attention while it keeps its slot.

    *Of this effort.* A lease with another base is that effort's business, and one with no base at all is
    unattributable — refusing on it would refuse on evidence nobody can act on (`D-6`).

    *Ahead of its own.* This is the part with no obvious alternative. If every claimant counted every other
    claimant, five simultaneous dispatchers at a cap of 1 would each see four and all five would refuse —
    a livelock wearing a cap's clothes, and a strictly worse failure than the one being fixed. Ranking by
    the order recorded in the lease bodies makes every racer compute the same sequence, so the first `cap`
    of them admit and the rest are refused by claims they can name.
    """
    known = {s.identity for s in recorded}
    ahead = []
    for lease in ctx.pool.claims():
        if lease.slot == ctx.claim:
            break                     # ordered: everything past our own claim came after us
        if ctx.base and (lease.base_instant or "") != ctx.base:
            continue
        if not lease.base_instant or lease.todo_id in known:
            continue
        ahead.append(_claim_subject(lease))
    return ahead


def _claims_in(workers: list) -> list:
    """Which of a population are held claims rather than records — so a verdict can SAY which they are.
    A refusal that counts something the reader cannot find in the store has to name it, or it reads as the
    guard being wrong (`RI-31`'s family: a correct refusal that never said whose lease it was)."""
    return [s for s in workers if s.evidence.get("record") == "none"]


def _claim_subject(lease):
    """A won claim as a subject, so ONE `_decide` covers both passes.

    `PENDING-LAUNCH` is the accurate state and it comes from the closed vocabulary in `reconcile` rather
    than a new value invented here: dispatched, no launch recorded, no live session. The evidence carries
    the child instant, which is what lets the compaction rule read an inflight compaction's opType out of
    a claim that has no record yet — the same read-then-decide race, on the other rule.
    """
    return Subject(
        kind=KIND_WORKER, identity=lease.todo_id, state=PENDING_LAUNCH, holds_slot=True,
        evidence={"record": "none", "base": lease.base_instant, "instant": lease.child_instant,
                  "slot": lease.slot, "lease": "held", "tmux": lease.tmux,
                  "claimed_at": lease.claimed_at, "claimed_ns": str(lease.claimed_ns)},
        note=(f"slot {lease.slot} is claimed by {lease.todo_id} and its record is not written yet; the "
              "claim is what admission is decided on, because the record comes after the gate (FI-21)"))


def _instant_name(subject) -> str:
    """The subject's instant folder name, resolved through any rename the record predates."""
    raw = subject.evidence.get("instant", "")
    if raw.endswith(_MISSING_SUFFIX):
        raw = raw[:-len(_MISSING_SUFFIX)]
    return Path(raw).name


def _optype_of(subject) -> str:
    """The opType field of the subject's instant name, or `""` when the name is not an instant.

    Parsed by `identity` and nowhere else: `OI-17` hardcoded a VALUE of this field at one call site and
    every correct compaction rendered `(missing)` from the moment of dispatch.
    """
    try:
        return InstantName.parse(_instant_name(subject)).optype
    except InstantNameError:
        return ""
