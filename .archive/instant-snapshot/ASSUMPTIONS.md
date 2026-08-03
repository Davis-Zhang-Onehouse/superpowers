# ASSUMPTIONS   (unverified; each states how it would be checked and what breaks if it is false)

## A-1 the six briefs describe the tree as it is on 2026-08-03 at `0.3.1`
**Status: VERIFIED for every open brief's CORE premise at `11f2f58`, 2026-08-03T03:17Z.** Still OPEN for
the briefs' full bodies — the check covers each one's central claim, not every sentence in it.

Written from measurements taken that day. Code moves.
- **Check:** `bash bin/reverify-briefs.sh` — one command, one row per gap, exit 1 if any premise moved.
  Supersedes "re-run the measurement its brief quotes" (a pasted measurement cannot be re-run; this can).
- **Result:** `G-1`'s absence, `G-2`'s two claims, `G-3`, `G-4`, `G-5`, `G-7`'s two claims and `G-8` all
  HOLD. `A-2` was REFUTED — see below. Artifact: `evidence/2026-08-03-brief-reverification.txt`.
- **If false:** a fix aimed at a defect that has moved or gone. `FI-8` and half of `FI-11` turned out
  ALREADY FIXED when re-measured, and `FI-3` was not a fleet defect at all.

## A-2 `DA-2`'s "six send paths" is still six
**Status: REFUTED 2026-08-03 — the count has no source at all, so there is no "still" to check.**

`G-1` rests on that count, quoted from `cli.py:153`. It was established before this line of work and has
not been re-counted.
- **Check (done):** `bash bin/reverify-briefs.sh`, row `A-2`. `DA-2`'s own text
  (`design-20260730-fleetInfraRefactor/09-OPEN-QUESTIONS.md:37`) is a **WITHDRAWN** assumption about
  whether `claude-watchdog.sh` had defects. It enumerates no send paths, and no enumeration of six exists
  anywhere in the tree. Every citation traces back to the `cli.py:153` comment that cites `DA-2`.
- **What is true instead:** two in-repo implementations, both test-harness (`live-pane.sh`,
  `run-group5.sh:127`), plus the external `claude-auto-retry` package — the one real outside caller,
  which `DA-2` itself records as **still unread**.
- **Consequence (realised, not hypothetical):** `G-1`'s closure criterion "the five other send paths are
  enumerated and migrated" is aimed at paths that do not exist here and must be restated. The
  de-duplication argument for the verb does not carry; the choke-point + `G-2`-needs-it argument does.
  Written up in `evidence/issues/G-1-pane-delivery-verb.md` §6a.

## A-4 `claude-auto-retry` does not already implement the correct type-wait-Enter contract
**Status: VERIFIED 2026-08-03 — it does NOT. It uses a fixed 150ms delay, and its `pane-guard` patch gates
only BEFORE typing, never after.** Artifact: `evidence/repro-g1/car-tmux-send.js.txt`. Write-up:
`evidence/issues/G-1-pane-delivery-verb.md` §6b. This closes `DA-2`'s long-open "still unread" action.

Consequences realised: `G-1` §5.1 (verb vs library) is settled on evidence — the sole production consumer is
node and can only reach python by subprocess, which it already does for `pane-guard`. And code `10` inverts
meaning across the type (stop before, go after), which is the trap a naive verb falls into.

## A-5 `claude-auto-retry`'s 150ms delay actually fails under load on this box
Raised by `A-4`'s verification. The measured failure threshold was between 0 and 50ms (`G-1` §2), so 150ms
has margin — but the box runs 12 concurrent IT runners and a dropped Enter is silent.
- **Check:** instrument the monitor to log `pane-guard` after its Enter, or replay `G-1` §2's gap sweep under
  concurrent load.
- **If TRUE:** a live instance of `FI-15`'s race in the only auto-resume path on the box — a real defect, and
  it belongs to the parent instant's monitoring duty, not to this design.
- **If FALSE:** the argument for the verb rests on contract strength (a condition beats a timer), not on a
  present failure — which is where it should rest anyway.
- **Do not state it as a live defect until measured.** Tracked as `RA-2` in the RCA.
- **Partial evidence 2026-08-03 (`A-6`'s probe):** 150ms — the exact value `claude-auto-retry` uses — was
  measured directly: **0 drops in 2 clean trials at loadavg 0.32**. That neither clears nor condemns it. Two
  trials is not a rate, and idle-box behaviour says nothing about a loaded one. What the same run DID
  establish is that the outcome is predictable from `pane-guard` after the type (12/12), so the production
  path could become correct rather than probable by polling instead of sleeping — regardless of how 150ms
  scores. **Still OPEN.**

## A-6 the type→Enter race measured 2026-08-02 still behaves that way
**Status: CONFIRMED and REFINED 2026-08-03 on a real claude pane (2.1.220, the same version), 12 clean
trials.** Artifacts: `evidence/2026-08-03-ra1-send-race.txt` (narrative) and `.tsv` (rows).
Regenerate: `FLEET_ALLOW_LIVE_CLAUDE=1 bash bin/probe-ra1-send-race.sh`.

- **The race is real and still there.** At gap=0 the Enter is dropped and the text sits queued.
- **It is INTERMITTENT — 1 in 5 at gap=0**, which the original's single trial could not show. That is the
  signature of a race rather than a protocol rule, and it is the fact that matters for design: a fixed delay
  can only ever buy a *probability*.
- **`pane-guard` after the type PREDICTS the outcome perfectly — 12/12.** The one dropped trial is the one
  where it read `0` (text not landed); all eleven that read `10` submitted. So the condition does not merely
  reduce the risk, it **eliminates the failure mode by construction**: the failure *is* "the text is not in
  the box yet", and that is exactly what `10` answers.
- **The original's conclusion survives its flawed method.** Its trials 2-4 were measured with residue in the
  box (see `bin/probe-ra1-send-race.sh` header), but a clean re-measurement independently reproduces
  "50ms and above submits": 0 drops in 6 trials across 50/150/500/3000ms.
- **Consequence:** the polling contract is solving a race that DOES exist, so `G-1` is not reducible to
  consolidation plus a choke point. The verb's core behaviour is justified on measurement.
- Tracked as `RA-1` in the RCA — now CONFIRMED there too.

### A-4 as originally written (2026-08-03, ~03:20Z) — CLOSED by the entry above; do NOT act on these lines
Kept because the register must show the arc, not just the answer. Every action item below is DISCHARGED.

> It is the only real send path outside this repo and the only one with a live pane in production. `A-2`'s
> refutation makes it the sole existing consumer `G-1`'s verb would have to serve.
> - **Check:** read it (`DA-2` has had "read the 204 LOC, `claude-tmux.sh`, and the `claude-auto-retry`
>   package" as an open action since the design phase; still unread). Does it poll for `pane-guard`'s `10`,
>   or send blind?
> - **If false** (i.e. it already does it right): there are then TWO correct implementations and the verb's
>   job is consolidation after all — which restores part of the argument `A-2`'s refutation removed.
> - **If true:** it is a live instance of `FI-15`'s race in the only daemon on the box, which is a finding
>   in its own right and belongs to the parent instant's monitoring duty.

**How it resolved:** neither branch cleanly. It neither polls nor sends fully blind — it gates *before*
typing and then trusts a 150ms timer for the Enter. The "if true" branch's conclusion is therefore held back
to `A-5` and explicitly NOT asserted, because margin over the measured threshold means the race is plausible,
not demonstrated. The binary the assumption was written as did not survive contact with the code.

## A-3 nobody else is depending on the current `dispatch` single-call form
`G-3` may change it.
- **Check:** grep the operations tree and the dispatch scripts for `fleet dispatch` before deciding.
- **If false:** a two-phase dispatch breaks callers outside this repo.
