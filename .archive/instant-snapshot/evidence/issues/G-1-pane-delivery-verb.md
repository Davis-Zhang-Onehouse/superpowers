# G-1 — no `fleet` verb owns pane delivery, so six send paths each implement it

**Origin:** `QI-4` (fleetInfraOps parent instant), from `FI-15` in the quanton v2stackcoordinator register.
**State:** OPEN. Deferred 2026-08-03 by operator decision `D-4` ("document it for now").
**Depends on / blocks:** `G-2` cannot be built cleanly without this, and `G-2` is the concrete consumer
this deferral lacked at the time it was taken.

---

## 1. The observable

`fleet pane-guard` is described in `skills/using-fleet/SKILL.md` as *"the send-keys contract, as an exit
code"*. It **gates** a send. Nothing in the package **performs** one:

```
$ grep -rn "send-keys" fleet/src skills scripts bin
skills/using-fleet/SKILL.md:60    | `fleet pane-guard` | the send-keys contract, as an exit code |
fleet/src/fleet/cli.py:2545       """The contract the external monitor is REQUIRED to call before any send-keys"""
fleet/src/fleet/cli.py:153, 3288  — comments ABOUT sending
scripts/claude-watchdog.sh:20     — a comment ABOUT sending
scripts/claude-tmux.sh:4          — a comment ABOUT sending
```

Every hit is a mention. There is no implementation.

`cli.py:153` records the count, and it is the number that matters:

> because the external monitor branches on them before every send-keys and **DA-2 enumerated SIX send
> paths**.

So the package owns the gate and six callers each own the keystrokes.

## 2. Why that is expensive — measured, not argued

`FI-15` was reported as *"`tmux send-keys … Enter` does not submit; a printable character THEN Enter
does."* Reproduced on a real claude pane 2026-08-02 (claude 2.1.220), one session, varying only the gap
between the text and the Enter:

| gap | `pane-guard` after type | after Enter | submitted? |
|---|---|---|---|
| 0s | **0** — the text had not even landed | **10** | **NO — the Enter was dropped** |
| 0.05s | 10 | 11 | yes |
| 0.5s | 10 | 0 | yes |
| 3s | 10 | 0 | yes |

**The reported mechanism is false.** Bare Enter submits fine. What fails is a RACE: the keystroke reaches
a widget that has not processed the text yet and is discarded. The reporter's "send a space first" works
because the extra round-trip buys milliseconds — a charm, not a mechanism.

> **RE-MEASURED 2026-08-03 at `11f2f58` — see §2a. The mechanism is confirmed; the table above is
> superseded by a cleaner 12-trial sweep, because these trials 2-4 ran with residue in the input box.**

The correct contract is a CONDITION, not a delay, and the predicate already exists: `pane-guard`'s `10`
means precisely *"there is text in the box"*.

```
type the text  →  poll pane-guard until it returns 10  →  then send Enter
```

That discovery landed in the reporter's own RUNBOOK. **The other five send paths cannot see it.** That is
`FI-20`'s shape on the other side of the boundary: the safety-critical primitive implemented once per
caller, so a correction reaches one of them.

## 2a. Re-measured 2026-08-03 (`A-6`/`RA-1` CLOSED) — the race is INTERMITTENT, and the guard predicts it

Operator authorised the allowance spend. Same claude (2.1.220), same box, one session, **12 clean trials**,
every trial started from an ASSERTED idle-and-empty pane. Artifacts:
`../2026-08-03-ra1-send-race.txt` + `.tsv`. Regenerate:
`FLEET_ALLOW_LIVE_CLAUDE=1 bash bin/probe-ra1-send-race.sh`.

| gap | trials | Enter dropped | rate |
|---|---|---|---|
| **0s** | 5 | **1** | **1/5** |
| 0.05s | 3 | 0 | 0/3 |
| **0.15s** (what `claude-auto-retry` uses) | 2 | 0 | 0/2 |
| 0.5s | 1 | 0 | 0/1 |
| 3s | 1 | 0 | 0/1 |
| `submit` — poll for `10`, then Enter | 1 | 0 | submitted |

**Three things this establishes that §2 could not:**

1. **The race is INTERMITTENT.** §2 showed gap=0 failing once and read as deterministic. It is 1-in-5 here.
   That is the signature of a race, and it is what kills "just pick a delay": a delay buys a probability.
2. **`pane-guard` after the type is a PERFECT discriminator — 12 of 12.** The single dropped trial is the
   single trial whose `guard_after_type` read `0`; all eleven reading `10` submitted. So the condition does
   not merely lower the risk, it **removes the failure mode by construction** — the failure *is* "the text
   has not landed", and `10` is exactly the answer to that question. This is the strongest available
   argument for the verb's contract, and it is now measured rather than reasoned.
3. **§2's conclusion survives its flawed method.** Its trials 2-4 were contaminated (the dropped gap=0 text
   was still in the box, so their `guard_after_type=10` was true regardless of their own keystroke, and
   their Enter submitted a concatenation). A clean sweep reproduces the conclusion anyway: 0 drops in 6
   trials at 50ms and above. The number to trust is this table; the finding was right.

**Not established:** that 150ms fails in production. 0/2 at loadavg 0.32 is not a rate, and an idle box says
nothing about a loaded one — `A-5`, still OPEN. The argument for changing it rests on contract strength, not
on a demonstrated failure.

## 3. What exists today

- **`skills/using-fleet/SKILL.md`** — the contract is documented, with the measurement table above, in a
  section titled "Delivering text to a pane: type, WAIT, then Enter".
- **`fleet/it/bin/live-pane.sh submit`** — a working reference implementation. Verified 5/5 where the raw
  sequence dropped at gap=0. It also REFUSES to press Enter if the text never arrived, rather than
  pressing into an empty box and looking like it worked.
- **Nothing in the package.** Documentation and a test-harness script are not a verb.

## 4. Why it was deferred, in the operator's terms
It adds a new **outward-acting** verb to a package whose outward call sites are audited exactly — §M9
enumerates every spawn seam and every delete site, in two registries that must agree (`II-3`). A send is
a new class of outward act. That is a design pass, not a repair, and on 2026-08-03 the operator chose to
document rather than build.

## 5. What a fix has to decide
1. **Is it a verb or a library call?** A verb is scriptable by the watchdog and by cron; a library call
   is only reachable from python. `G-2` wants the verb.
2. **Does it gate internally, or require the caller to have gated?** Internal gating is safer and makes
   the verb the choke point `DA-2` wanted. It also means the verb can return `pane-guard`'s codes.
3. **What does it do on a pane it should not touch?** `dt-*` on the default server is forbidden to this
   whole line of work. The verb must refuse by name, not by convention — `live-pane.sh` does exactly
   this and is the model.
4. **The spawn-seam audit.** `session.default_probes` already owns tmux. If the send goes through it,
   the seam count stays three and §M9 stays green. If it does not, §M9 fails and correctly so.
5. **Timeout and reporting.** `live-pane.sh submit` polls 50 × 0.2s and reports failure rather than
   pressing blind. A verb needs the same, plus an exit code a script can branch on.

## 6. How to know it is closed
- A `fleet` verb delivers text to a pane, gating internally on `pane-guard`'s `10`.
- It refuses a `dt-` target on the default server, by an explicit check, with a test.
- §M9's spawn-seam count is unchanged (still 3) or the change is argued in BOTH registries.
- `live-pane.sh submit` is reimplemented on top of it, or deleted in its favour — two implementations of
  the same primitive is the defect this closes.
- The five other send paths are enumerated and migrated, or each is recorded as why-not.

## 6a. ⚠️ Re-measured 2026-08-03 at `11f2f58` — the "six send paths" number has no source

`A-1` says re-measure before starting. Doing so **refuted `A-2`**, and it changes this gap's scope.
Artifact: `../2026-08-03-brief-reverification.txt`, row `A-2`. Regenerate: `bash bin/reverify-briefs.sh`.

**The absence still HOLDS** — no `send-keys` invocation exists anywhere in `fleet/src`; the two hits are
prose. The package still gates a send it cannot perform. That half of §1 is unchanged.

**But the count of callers does not survive.** Every citation of "six send paths" — this brief's §1, `A-2`,
`PRIORITIES.md`, the parent's `ISSUES.md`, `test_cli.py:1273`, `plan-4-surface-layer.md` — traces back to
the comment at `cli.py:153`, which attributes it to `DA-2`. `DA-2`'s actual text
(`design-20260730-fleetInfraRefactor/09-OPEN-QUESTIONS.md:37`) is:

> `DA-2` ⚠️ **WITHDRAWN.** Rev 1 asserted `claude-watchdog.sh` had "no defects bearing on these
> requirements". **REFUTED by doc 03's own text** … Read the 204 LOC, `claude-tmux.sh`, and the
> `claude-auto-retry` package. **Still unread.**

It is a withdrawn assumption about one script's defect status. **It enumerates no send paths, and no
enumeration of six exists anywhere in the tree** (`grep -rn "six send\|send path"` finds only citations of
the comment). The number is circular: the comment cites `DA-2`; `DA-2` says nothing; everything else cites
the comment.

What actually exists in-repo today is **two** implementations, both test-harness:
`fleet/it/bin/live-pane.sh` (`cmd_type` / `cmd_key` / `cmd_submit` — the correct one) and
`fleet/it/run-group5.sh:127` (`it_send`, a one-line helper). `scripts/claude-watchdog.sh` *documents*
send-keys but delegates the send to the external `claude-auto-retry` package — outside this repo, and
per `DA-2` still unread.

**Consequence for this gap, and it cuts both ways:**
- The migration list in §6 ("the five other send paths are enumerated and migrated") is **aimed at paths
  that do not exist here**. That closure criterion must be restated, or it can never be satisfied.
- The de-duplication argument therefore does NOT carry this gap. The honest argument is the other one:
  `G-2` needs a gated primitive, and the verb is the choke point a future caller inherits — plus
  `live-pane.sh submit` is currently a test-harness script holding the only correct implementation of a
  safety-critical primitive that production code will need.
- **`claude-auto-retry` is the one real outside caller and nobody has read it.** Whether it races the way
  `FI-15` measured is unknown. That is worth an hour before designing the verb's contract, because it is
  the only existing consumer with a live pane and a real send.

This is the same shape as `G-7`: a claim that got repeated until it read as measured. Third sighting in
this line of work.

## 6b. `A-4` CLOSED 2026-08-03 — `claude-auto-retry` read at last, and it answers §5.1

`DA-2` has carried *"read the 204 LOC, `claude-tmux.sh`, and the `claude-auto-retry` package — still
unread"* as an open action since the design phase. Done. Artifact:
`../repro-g1/car-tmux-send.js.txt` (`claude-auto-retry/src/tmux.js:29-92,99-140`, vendored under
`/home/ubuntu/davis_root/opt/car/`). RCA: `../../investigations/g1-g2-stall-loop/analysis.md`.

**What the one production send path actually does:**

```js
export const SUBMIT_DELAY_MS = 150;   // "150ms is empirically reliable across Linux + macOS"

export async function sendKeys(pane, text) {
  await execFileAsync('tmux', tmuxArgv(buildSendTextArgs(pane, text)));   // type, literal
  await new Promise(r => setTimeout(r, SUBMIT_DELAY_MS));                 // ← a DELAY
  await execFileAsync('tmux', tmuxArgv(buildSendEnterArgs(pane)));        // Enter
}
```

It already knows the two-call shape and why it is needed. What it uses is a **delay where §2 says the
contract is a condition** — the charm, at 150ms.

**It also already shells out to `fleet pane-guard`** (a local patch, `superpowers/patches/claude-auto-retry`)
— but as a **PRE-SEND** gate: check for `10` *before* typing, so a nudge does not concatenate onto an
operator's half-typed sentence. It does **not** poll after typing. Its own comment gives the reason the verb
should exist: *"detecting it means knowing what an unsubmitted input box looks like on screen — which `fleet`
already decides, and which two independent implementations would eventually disagree about."*

### This settles §5.1: a VERB, not a library call
The only production consumer is **node**. It can reach python only through a subprocess, and it already does
exactly that (`FLEET_BIN … execFileAsync(FLEET_BIN, ['pane-guard', '--pane', session])`). The precedent, the
mechanism and the sole caller all point the same way. §5.1 can be closed on evidence rather than taste.

### ⚠️ Code `10` inverts across the type, and a naive verb will get it backwards
- **Before** typing, `10` = *"someone else's text is in the box"* → **stop**. (What the patch uses.)
- **After** typing, `10` = *"my text landed"* → **go**. (What `cmd_submit` uses, and what the verb needs.)

Same code, opposite meanings on either side of one keystroke. Any implementation that reuses the patch's
logic unexamined inverts the contract it is trying to fix.

### What is NOT established — do not assert it
Whether 150ms actually fails on this box is **UNMEASURED** (`RA-2` in the RCA). The measured failure
threshold was between 0 and 50ms, so 150ms has margin; the box also runs 12 concurrent IT runners, and the
failure is silent. Tempting and wrong to write *"production sends blind, hence the stalls."* It relies on a
weaker contract than the project already knows how to write. That is the finding; a live defect is not.

**Revised send-path census (supersedes §6a's "two"):** three real implementations —
`live-pane.sh` (correct, test-harness), `run-group5.sh:127` (a one-line test helper), and
`claude-auto-retry/src/tmux.js` (production, delay-based, pre-gated). Still not six, and still no verb.

## 7. Files
- `fleet/src/fleet/cli.py` — `_do_pane_guard`, the code registry at :158-176, the `DA-2` note at :153
- `fleet/src/fleet/session.py` — `default_probes`, the tmux seam
- `fleet/it/bin/live-pane.sh` — `cmd_submit`, the reference implementation
- `skills/using-fleet/SKILL.md` — the documented contract
- `fleet/it/run-group5.sh` — §M9's `SEAMS`, derived from `test_cli.SPAWN_SEAMS`
