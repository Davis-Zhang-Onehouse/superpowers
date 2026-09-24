---
name: dispatching-a-wave
description: Use when putting several worker instants in parallel onto one shared base - deriving the cap from the guard rather than a formula, taking the lineage base from the chain manifest rather than prose, and writing each worker's scope before releasing its seed. Triggers include "dispatch the next wave", "two rows are ready on the same base", "put three workers on this", "dispatch these milestones in parallel".
---

# Dispatching a Wave

## Overview

A **wave** is several workers admitted onto **one shared base** at roughly the same time. Each takes a
different milestone, cuts its own branch from the same lineage base, and opens its own PR. They are
siblings, not a chain — linearising them is a separate job
(`superpowers:integrating-a-pr-stack`).

Dispatching one worker is a `fleet dispatch` away and `superpowers:coordinating-instants` covers it.
Dispatching *several* adds four problems that one does not have: which rows are actually dispatchable, how
many you are allowed, whether two of them will collide, and a race between creating a worker and telling
it what to do.

**Announce at start:** "I'm using the dispatching-a-wave skill to dispatch this wave."

## The routine

| # | Step | Why it is not optional |
|---|---|---|
| 1 | **Read the ready set off the roadmap's `ready` rows and state it out loud.** | A set you named is auditable; a set you had in mind is not. See below. |
| 2 | **Take the base from the chain manifest, then confirm it on the remote.** | `fleet` checks that the slot *arrives* at the sha; nothing checks that it was the right sha. |
| 3 | **Ask the guard for the cap. Never compute it.** | The guard counts records; you would be counting your recollection. |
| 4 | **Declare the surface each worker will touch, or sequence them.** | Two workers on one file is a real event, not a hypothetical. |
| 5 | **Prepare the scope and profile → `dispatch --seed-extra`.** | Dispatch launches immediately with the complete rendered seed. |
| 6 | **Verify the launched process carried the right environment.** | A worker can come up attributed to somebody else. |
| 7 | **Write briefs one milestone ahead, never two.** | A brief written early decays faster than it is consumed. |

## Step 1 — the ready set is a column read

`fleet roadmap --porcelain` emits exactly one `ready` or `not-ready` row per milestone, one `pending-proposal`
row per waiting proposal, and a closing `population` row. Every milestone row carries the milestone's `title` ($7) and `owner` ($8) as
fields, so the dispatchable set is:

```bash
fleet roadmap --instant "$INSTANT" --porcelain | awk -F'\t' '$1=="ready" && $8==""{print $2 "\t" $7}'
```

**Write that set down before dispatching any of it.** A set you named is auditable; a set you had in mind
while dispatching is not.

Do not drop the `$8==""` half. A `ready` row whose `owner` is set is already claimed by the instant it names —
readiness is derived from dependencies alone and never reads the claim, so a dispatched milestone stays
`ready` until its worker's `running` proposal is applied. (Before `SI-47` was fixed the ready set had no
rows at all and had to be rebuilt from `.fleet/roadmap.json` by hand; do not reach for that file now.)

A claim outlives an instant that finished or died without landing the milestone (`abort` releases it; other
exits do not). A claimed `ready` row is **stranded** only when BOTH hold: no `fleet board --porcelain` row carries
that milestone in its `milestone` column (`$6`; the board has no instant-path column, so never match `$8`
against it), AND the roadmap has no `pending-proposal` row for it. A harvested worker whose `done` report is
still pending is not stranded — `fleet apply` it. Only a truly stranded claim is released with
`fleet milestone --instant "$INSTANT" --id <m> --disown --reason "<why>"`, after which it is dispatchable. If
the owner's folder was deleted while its record is still open, a board row may still carry the milestone and
`--disown` will not release it yet: `fleet close --id <todo>` ends that record first (`abort` and `harvest`
cannot resolve a gone folder). The refusals name the door for the owner's state; take the one they name.

## Step 2 — the base comes from the manifest, then from the remote

Read the current tip from the chain manifest, then confirm that ref still resolves to that sha on the
remote before you type it. Both halves matter: the manifest saves you from retyping a prose table, and the
remote check catches a manifest that has gone stale.

`--lineage-base` is the single authority for what a worker builds on. It is rendered into the seed and the
charter, and a claim of done from a slot that is not at the base is refused.
<!-- v2-cite: done-from-wrong-base-refused LB2 -->
What is **not** checked is whether the sha you typed was the correct one for that milestone. That
judgement is yours and there is no safety net under it.

For a wave, every member normally takes the *same* base — that is what makes them a wave, and what lets
the integration step assume a common root.

## Step 3 — ask the guard, do not compute the cap

Run the dispatch with `--dry-run` first and read `guard.wip-cap` out of the output:

```
guard.wip-cap  allow: 0 of 1 active-dev slot(s) in use. examined 0 subject(s) of 00000000 in /work/effortA/instants; 0 counted, 0 excluded
```

That row names the count, the cap, the population examined, who is counted and who is excluded. It is the
answer. The guard's own cost note says it is free and safe to ask before every dispatch and safe to ask
twice, so there is no reason to ask anything else.

The population is **this effort's**: records of your `--base` whose instant lives in your `FLEET_INSTANTS`.
One store serves every effort on the root and base strings repeat (`00000000` is every effort's root base),
so same-base records of another instants directory are reported as `set aside` and never counted. Keep
`FLEET_INSTANTS` absolute: a relative one cannot place anything, and the guard falls back to counting every
record of the base. Each counted holder is named with three facts:

```
guard.wip-cap  refuse: the WIP cap is 1 and 1 active-dev subject(s) hold it: 00000000-08080738-inflight-append-i11old [folder: no, session: no, age: 47d14h]. examined 3 subject(s) of 00000000 in /work/effortA/instants; 1 counted, 2 excluded (…); set aside 12 subject(s) of base 00000000 whose instant lives in another instants directory — another effort's, which never holds this cap
```

A holder with `folder: no, session: no` is a phantom of your own effort, a record nothing is working on:
reap or harvest it. Raising `--cap` to get past it makes the cap decorative.

**Do not carry a formula.** The tempting one — *me, plus the workers already running, plus this one* — is
a remembered number with arithmetic on top, and it is **wrong in at least one ordinary case**: the cap
counts *records*, so whether your own coordinator counts depends on how it was created. A coordinator that
was itself dispatched has a record and counts, permanently. A coordinator created with `fleet init` has no
record and does not. Measured against a scratch store, an `init`-created coordinator with one worker
wanted reports `0 of 1` — the formula predicts 2.

A worker that has declared `awaiting-ci` stops counting; the declaration is what does it, and the same
words written as prose into a handoff do not.
<!-- v2-cite: declaration-frees-the-cap F2 -->
<!-- v2-cite: prose-does-not-free-the-cap F3 -->
A second dispatch over the cap exits 4 — refused by an admission rule, which is a rule deciding against
you rather than anything being broken.
<!-- v2-cite: cap-refuses-second-dispatch F1 -->
An inflight compaction of the same effort freezes dispatch entirely and names the instant responsible.
<!-- v2-cite: compaction-freezes-dispatch F4 -->

**The cap is not the only gate, and it is the weaker one.** The cap says how many *may* run. Your own
standing rule about how few must be left before another starts is a different question with a different
population, and the cap will happily admit a worker your throughput cannot absorb.

## Step 4 — collision is a real event

Two workers on the same file, at the same time, on sibling branches, is not a hypothetical. It has
happened at a scale that surprised the coordinator who found it: seven files under concurrent authorship
by two live workers, discovered after both had been running for hours.

Before dispatching a wave, for each member say **which surface it will touch**, and check the members
against each other. Where two overlap, either sequence them or give both charters an explicit note naming
the other and saying who resolves.

The reason to do this at dispatch rather than at integration is that a collision found at integration is a
merge conflict you resolve blind — neither worker is still around to say what they meant.

## Step 5 — finish scope before dispatch

Prepare each worker's scope and acceptance criteria before starting it. Put the finished charter in a
worker-specific profile, preserving the profile's identity and lineage placeholders. Prepare any extra
instructions in a UTF-8 file. Do not edit a shared profile while another dispatch is reading it.

```bash
fleet dispatch --profile "$PREPARED_PROFILE" --title "$TITLE" --base "$BASE" \
  --from "$INSTANT" --milestone "$M" --cap "$CAP" \
  --lineage-base "repo=$SHA" --seed-extra "$TASK_BRIEF" \
  --runtime codex --dry-run                       # codex on its configured default model
# or, for a claude worker on a chosen model:  --runtime claude --model claude-fable-5-1
# Once the gates allow, run the same command without --dry-run.
```

Type the runtime and model literally. A conditional expansion such as `${MODEL:+--model "$MODEL"}` is ONE word
under zsh, which `fleet` refuses as an unknown flag, and an empty `--runtime ""` is refused rather than read as
"use the box".

**Pick the runtime and model per worker, in the command.** `--runtime claude|codex` and `--model <name>` win
over the profile's `"runtime"`/`"model"`, which win over the box's `fleet runtime`; omit `--model` to run the
CLI's configured default (for codex, its default model). The dry-run prints `runtime` and `model` with their
source — read them before releasing: a row saying `(box …)` is an inherited default, not a choice you made.
Never switch the box (`fleet runtime --set`) to get a different CLI for one wave; other efforts share it.

`fleet dispatch` renders the charter and seed, appends `--seed-extra` to the seed, and starts the chosen
CLI with that complete seed as one argument. It owns the launcher and delivery; there is no post-dispatch
handoff or waiting shim. A missing or empty seed cannot start an unbriefed worker.

**Treat dispatch as the release signal.** Scope and acceptance criteria must be complete before it.
Keep the profile's self-check that tells the worker to park when its charter scope remains a placeholder;
never ask it to infer scope from a milestone title. Nothing on your side catches a placeholder scope: the
`authoring-placeholder` lint does not run from any command a coordinator can type (`SI-45`) and would not
match the HTML-comment placeholder convention anyway (`SI-46`), and with dispatch launching the worker
immediately there is no window to fix it afterwards.

## Step 6 — verify what actually launched

Read the launched process's environment and confirm it carried the workspace's identity rather than the
tmux server's. A worker running under the wrong credential does not fail loudly — an API call returns an
empty list, which reads exactly like *nothing is wrong*.

Check the variable is **present**; never print its value.

## Step 7 — one milestone ahead

Writing the next brief during a CI wait feels like good use of dead time. It is, for exactly one
milestone. Beyond that the brief **decays faster than it is consumed**: a predecessor lifts a quarantine,
a decision supersedes a measurement, a tool moves, and the brief now teaches something that was true when
written.

If you deliver a brief written earlier, re-verify every claim in it that a predecessor could have changed
— every sha, every count, every "already measured, do not redo" — and record in the dispatch note that you
did. Then a claim that turns out wrong is attributable to a measurement rather than to staleness.

## Red flags

| Thought | Reality |
|---|---|
| "Cap 3 for three workers" | `--cap` counts records, not intentions, and whether yours is among them depends on how you were created. Read the guard. |
| "I'll fix the charter right after it boots" | Dispatch starts the worker immediately. Complete the scope before dispatch. |
| "These two milestones are unrelated" | Seven files once said otherwise. Declare the surface; do not assume it. |
| "The profile lints clean" | Nothing lints a profile from the command line. That claim is not re-derivable today. |
| "The roadmap says two are ready" | Count the `ready` rows with an empty owner and name them before you dispatch them; the population row's number includes claimed ones. |
| "The base is in my HANDOFF table" | That table is narrative. The manifest is state, and the remote is truth. |
| "I have three slots free, so I can run three" | Free slots are capacity, not throughput. The cap admits workers you may not be able to absorb. |
