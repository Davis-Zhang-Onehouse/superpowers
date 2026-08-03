# G-7 — a refusal names the rule it enforces but not the route that satisfies the intent

**Origin:** `FI-16`, added to the quanton v2stackcoordinator register 2026-08-03 ~02:51Z.
**State:** OPEN. **Corrects a false claim I made and shipped.**

---

## 1. What the reporter found — and it corrects ME

They tried to retire a superseded milestone:

```
$ fleet milestone --instant "$INST" --id p1-ansi-baseline --status dropped --title "SUPERSEDED"
BadInput: milestone 'p1-ansi-baseline' is already in the roadmap; refusing to shadow it     # exit 2
```

The refusal is **correct in itself** — silently reshaping a milestone would destroy the registry's
history. And `--status dropped` IS in `milestone`'s documented vocabulary; it is simply unreachable after
creation.

**But the refusal does not name the route that works**, so they concluded — and wrote into `FI-10` —
that *"no workaround exists within the tool"*.

**That was false.** A coordinator can propose into its OWN roadmap and apply:

```
$ fleet propose --instant "$INST" --to "$INST" --milestone p1-ansi-baseline --status dropped \
      --evidence evidence/p1-superseded-by-split.md --note "…"
$ fleet apply   --instant "$INST" --milestone p1-ansi-baseline
applied   p1-ansi-baseline -> dropped
```

Measured by them: `of which 1 ready` → `of which 0 ready`.

## 2. ⚠️ I repeated their error, and shipped a verb on it

Reproducing `FI-10` on 2026-08-03 I ran two probes — `milestone --status dropped` (refused) and a bare
`apply` (refused, no pending proposal) — and concluded *"across 31 verbs there was no path"*. **I never
tried `propose --to <self>`.** I then built `milestone --retire` on that premise and wrote the false
claim into the commit message (`bd69a7f`) and into `QI-11`.

So:
- The capability was NOT missing. `--retire` is a **discoverability and ergonomics** fix, not a
  capability fix, and its justification must be restated.
- `FI-16`'s own proposal 2 is *"or a first-class verb — `fleet retire --id <m> --reason <why>`"*, so the
  verb matches what they asked for. It is the reasoning that was wrong, not the artifact.
- **`--retire` writes the status directly, bypassing propose/apply.** The propose/apply route keeps
  `apply` as the single status writer and produces an ATTRIBUTED, EVIDENCED change; `--retire` produces
  neither. That is a real design question this gap must settle, not a footnote.

This is the third time in this line of work that a conclusion was drawn from an incomplete probe set
(`II-7`'s `A1a`, `FI-3`'s heading, and now this). The pattern: **"I tried the two obvious things and
neither worked" is not the same as "there is no way".**

## 3. Why the cost was real
Readiness is DERIVED, so once `p1`'s only dep reached `done`, `p1` computed READY permanently — and
`roadmap --porcelain` prints only `not-ready` and `population` rows, so **the phantom was invisible in
porcelain while being the entire `1 ready` count.** A successor asking the correct question ("what is
ready to dispatch?") would have been told `p1`, the one milestone that must never be dispatched. For two
days.

They mitigated with prose in three places, which the skill's own rule — *"read porcelain, never prose"* —
predicts is insufficient.

## 4. The gap, as they state it
1. **The anti-shadowing refusal should name the route:** *"…refusing to shadow it. To retire or re-state
   a milestone, `fleet propose --status dropped` then `fleet apply` — the change is then attributed and
   evidenced."* One clause, and it is what the alarm contract already requires elsewhere.
2. **Or a first-class verb.** Shipped (`bd69a7f`) — but see §2: it bypasses the attributed route.

## 5. What a fix must decide
1. **Does `--retire` stay, or become sugar over propose/apply?** Sugar keeps `apply` as the single status
   writer and gets attribution and evidence for free. Direct write is simpler and already shipped.
   **Recommend making it sugar** — the invariant is worth more than the two lines it saves, and I
   weakened it on a premise that turned out false.
2. **The refusal must name the route regardless.** Even with the verb, a reader hitting the refusal
   should be told what to do. That is `fleet`'s own alarm contract.
3. **Audit for other refusals that name a rule and no route.** This is a CLASS. `FI-5` was the same shape
   with an impossible route; this is the same shape with an absent one.

## 5a. ⚠️ Re-measured 2026-08-03 at `11f2f58` — the false premise is in the SHIPPED SOURCE

§2 says the false claim went into the commit message (`bd69a7f`) and `QI-11`. Re-measuring found a third
copy, and it is the one that matters: **`Roadmap.retire`'s own docstring** (`roadmap.py:231-252`) argues
the single-writer carve-out *from* the refuted premise.

```python
"""The COORDINATOR removes a superseded milestone from the population. `FI-10`.

Across 31 verbs there was no way to do this. `add` refuses an id already present … and
`apply` refuses to invent a status without a worker's proposal … Both doors correctly shut,
and no third one.
```

A commit message is read by archaeology; a docstring is read by the next person to touch the function.
This is the copy that will propagate.

**It also changes what closure criterion 2 costs.** That criterion asks that `--retire`'s direct write "be
deliberately argued in the module docstring" — and §"On the module's stated invariant" (`roadmap.py:243`)
*already argues it*, carefully:

> The header says `apply` is the only function that changes a milestone's status. That is now stated more
> precisely … `apply` is the only thing that ADVANCES a milestone on a worker's evidence, and `retire` is
> the coordinator removing one from the population by its own decision.

That distinction is sound **and independent of the false premise** — it would hold even if ten other
routes existed. So the work is **restating a live argument on a true premise, not writing one from
scratch**: delete "no way to do this / no third one", name the propose→apply route, and keep the
advance-vs-remove distinction, which is the part that actually justifies the carve-out.

**This makes "does `--retire` stay?" (§5.1) a genuinely open call rather than a foregone one.** The
recommendation in §5.1 — make it sugar — was written believing the carve-out rested on the false premise.
It does not. The two live arguments are now: *sugar* buys attribution + evidence + one writer; *direct
write* is already shipped, already reasoned, and expresses a different act (the coordinator removing a
milestone from the population, with no worker and no evidence to attribute). Worth deciding on the merits.

Artifact: `../2026-08-03-brief-reverification.txt`, rows `G-7`. Regenerate: `bash bin/reverify-briefs.sh`.

## 6. How to know it is closed
- `milestone`'s anti-shadowing refusal names a working route.
- `--retire` either goes through propose/apply, or its direct write is deliberately argued in the module
  docstring that currently claims `apply` is the only status writer.
- A grep over refusal messages finds none that state a rule without a route, or the exceptions are named.

## 7. Files
- `fleet/src/fleet/roadmap.py` — `add` (the refusal), `retire`, `apply`, the header's single-writer claim
- `fleet/src/fleet/cli.py` — `_do_milestone`, `_do_propose`, `_do_apply`
- `bd69a7f` — the commit whose message carries the false claim
