# Analysis & retrospective + the RCA routine: the `free(): invalid pointer` saga

> **STAGING NOTE (2026-06-15):** Moved into `~/superpowers/_staging/` (with
> `WORKSPACE-AND-HANDOFF-ROUTINE.md`) to be merged later into a new skill / to revise
> existing skills. The companion evidence docs referenced below remain at their source:
> `/home/ubuntu/operations/tasks/quantonMORScanSupport/tasks/0611glutenveloxcleanup/m2/githubCI/symbols-map/{RCA-COMPREHENSIVE.md,RAW-TIMELINE.md}`.

Companion to `RCA-COMPREHENSIVE.md` (the technical story) and `RAW-TIMELINE.md` (the dated spine).
Two parts:

- **Part I — Retrospective** (the *process* story, honest about dead-ends): why earlier RCAs missed
  the caveats and what broke the wrong logic (Q1); which instructions sped us up (Q2); crystallized
  guidelines (Q3).
- **Part II — The RCA routine** (use this next time): a documented, repeatable procedure built from
  this saga's lessons — the two RCA patterns, the minimum-diff A/B checkpoint, the multi-setup
  fix-reconciliation discipline (the trap we fell into), the green-invariant check, the RCA-report
  template, and the prompt requirements that force all of it.

Grounded in the actual session transcripts (ws1/ws2/ws3, 2026-06-07 → 06-15) and the tracking docs.
**Read `RAW-TIMELINE.md` first** — it is the exhaustive dated event spine (every PR, CI run, commit,
hypothesis, and pivotal instruction) that this analysis interprets.
The saga ran across ~7 hot sessions and roughly **20+ CI round-trips**; the bug's *root family*
(static-libstdc++ symbol leak) was correctly named in a commit message on **06-06** (`1a2ebf144`,
"hide static libstdc++ symbols"), yet the durable fix didn't land until **06-12** — and the *truly*
root fix (drop `-static`) not until the holistic phase that night. That gap is the subject here.

---

# Part I — Retrospective

## Q1. Why earlier RCAs missed the caveats — and what broke the wrong logic

The earlier RCAs weren't *wrong* so much as **locally correct and globally incomplete**. Each one
explained the failure in front of it and stopped at the first intervention that turned CI green.
Five distinct mechanisms produced the blind spots:

**1. Fix-the-symptom-in-front-of-you (whack-a-mole).** The crash was a *cascade*: each fix unmasked
the next failure (Dim-1 `UnsatisfiedLinkError` → Dim-2 snappy multiple-def → Dim-3 `free(): invalid
pointer`; and within Dim-3, the teardown free site → a mid-test protobuf free site). Removing the
`~VeloxBackend` atexit destructor (PR #341) genuinely removed *one* free site — so it looked like
progress — but the crash just **moved**. We were enumerating call sites instead of removing the
condition that makes *any* cross-module free fatal (two allocators). Killing call sites can't
converge when the defect is structural.

**2. "It worked, ship it" stopped the inquiry one level too early.** The conditional `symbols.map`
(PR #355) turned every CI dim green and was proven four independent ways. By every *empirical* test
it was a valid fix — so the natural instinct was to close the ticket. What it hid: visibility
(`local:*` vs global) only *chooses which* of two allocators wins interposition; it never removes
the second allocator. The fix lived on a knife-edge — safe only because Trigger A (feature OFF) and
Trigger B (feature ON) never compile into the same build. Green CI is necessary but not sufficient
evidence of a *root-cause* fix; it can equally certify a lucky equilibrium.

**3. We trusted a written RCA comment instead of re-deriving it.** The in-file `symbols.map` comment
asserted "exporting std causes the rocksdbjni rebind, so hiding std is the fix." That was *half*
true (Trigger B) and the *opposite* of the truth for Trigger A (where hiding *causes* the crash).
The comment had authority because it was already in the tree with a confident root-cause story — so
it framed the investigation. It took an explicit A/B experiment (PR #356: revert *only* the hide)
to show the same change is protective in one build and fatal in the other.

**4. We reasoned about linkage from belief, not from the actual binaries/toolchain.** The biggest
single dead-end — "ship our own shared `libstdc++.so.6`" — rested on an unchecked assumption that
the build toolchain *had* a shared GCC-11 `.so.6` to ship. It doesn't: devtoolset-11's
`libstdc++.so` is a linker script pointing at the *system* `.so.6`, with the newer symbols only in
the static `libstdc++_nonshared.a`. We burned ~4 CI rounds on an impossible premise because nobody
ran `g++ -print-file-name` / `nm -D` inside the real build container until late.

**5. We validated in an environment that structurally couldn't reproduce the bug.** Early relinking
happened on the ws1 Ubuntu host, which links libstdc++ *dynamically* — so it could never exhibit the
*static*-duplication abort. Effort there felt like testing but couldn't decide anything; only the
centos container (or the A/B CI legs) could.

**What finally forced us to deny the old logic — the new questions.** Three of your questions, in
order, dismantled the incomplete model:

- *"Why are we hitting this now if we've used this image for a long time? Pinpoint the exact unmerged
  code."* — refused the environmental hand-wave and forced isolation to a specific diff line
  (the `local:*` in `symbols.map`).
- *"Why in the MOR-read-on case do we need to hide? How is the read-off case avoided while we hide?"*
  and *"alloc is done by one copy but free by the other … right?"* — these refused to accept "hiding
  fixes it" as a black box and named the **two-allocator** mechanism directly, which is what exposed
  the knife-edge.
- *"What libstdc++ version is actually used at runtime? **Pull the image and verify yourself.**"* +
  *"check quanton's embedded static libstdc++ version."* — these moved us from *reasoning about*
  linkage to *measuring* it on real artifacts, which is exactly what overturned the ship-a-lib
  premise and produced the `U`-vs-`T` proof.

The common thread: every breakthrough came from a question that **refused a black-box explanation and
demanded a measured, mechanism-level answer**. The earlier RCAs stopped at "this change makes it
green"; the questions pushed to "*why*, at the symbol/allocator level, and prove it on the real
binary."

---

## Q2. The specific instructions that made us iterate faster

These are the interventions that measurably changed velocity, with the verbatim instruction:

1. **Autonomy with fixed acceptance criteria — removed approval latency.**
   > "don't ask me for design, execution plan approval or any clarification questions, I give clear
   > acceptance criterion, you follow the procedure and carry them out."
   and later the concrete criteria: *"symbols.map should be reverted … x86 CI all green … toy example
   green."* Clear, checkable exit conditions + permission to act let the work run end-to-end without
   round-trips, while still being objectively gradeable.

2. **"push it now, there is no harm."** Lowered the cost of an iteration when a change was low-risk and
   CI was the only remaining gate — the right call once local checks are exhausted.

3. **The brainstorm → plan → subagent (superpowers) workflow.** Forced an explicit design + risk list
   *before* coding (which is where SONAME-precedence and the GLIBCXX floor were surfaced as risks),
   and parallelized the history mining for this very retrospective.

4. **"build me a toy … we should get to the bottom of this."** Commissioning a minimal, deterministic
   C++ reproduction of the cross-free (and extending it to the rocksdbjni/feature-ON case) converted a
   fuzzy load-order argument into a runnable 2×2 truth table. That toy is what made the knife-edge
   *undeniable* and grounded the holistic design.

5. **The single highest-leverage intervention: the mid-stream interrupt —**
   > "could you test these as much as possible locally setting up a similar env, or you have already
   > done that?"
   This stopped the CI-as-test-loop pattern cold. Within minutes of pulling the real build container it
   exposed the impossible ship-a-lib premise and ended ~4 wasted CI rounds. One well-timed question
   saved more wall-clock than any code change.

6. **Standing "repro locally first / mount the container" rule** (from the ARM track and #7):
   *"Always start with setting up the same env and repro locally … mount docker containers with those
   folders and run things inside it."* When followed, it was decisive (the 4m38s local centos-8 repro
   that anchored the symbols.map RCA).

A caveat worth recording: one piece of guidance *thrashed* us — the local-vs-CI direction flipped
mid-saga (*"pull the image to verify locally"* → later *"don't verify compilation locally, just launch
another PR"*). The lesson isn't "always local" or "always CI" — it's the decision rule in Q3 below.

---

## Q3. How to do issue-RCA better next time — crystallized guidelines

Concrete, ordered by leverage. These are written as defaults to follow unless there's a reason not to.

**G1. Reproduce in the real environment before theorizing — and never in one that can't show the bug.**
The first move on a build/linkage/native-crash bug is to pull the *actual* build/runtime container and
reproduce or measure there. We had Docker access the whole time; using it on day 1 would have
collapsed most dead-ends. Corollary: if your repro host differs from prod in the dimension that
matters (Ubuntu dynamic-libstdc++ vs centos static), results there are *not authoritative* — say so
explicitly and don't let them anchor a conclusion.

**G2. Measure the binary; don't reason about it.** For any claim about linkage, symbols, or versions,
run the command (`nm -D`/`nm -DC`, `readelf -d`, `objdump -T`, `g++ -print-file-name`,
`strings | grep GLIBCXX`) on the real artifact and paste the output. The `U`-vs-`T` distinction that
ended this saga was a 30-second command we could have run in week one. "I believe it links X" is a
hypothesis, not a finding.

**G3. Separate "made CI green" from "fixed the root cause."** Before closing, ask: *what would have to
be true for this fix to fail?* If the answer is "two independent conditions never coincide" (a
knife-edge) or "load order happens to be X," it's an equilibrium, not a fix — file the durable fix as
explicit follow-up even if CI is green. Green CI certifies *a* working state, not the *only* mechanism.

**G4. When a fix only moves the symptom, stop fixing call sites and find the invariant.** Two
consecutive "fixed it / no it moved" cycles (atexit dtor → mid-test protobuf) is the signal that the
defect is structural. Step back and name the condition that makes the whole *class* of symptom
possible (here: two allocator instances), then remove *that*.

**G5. Distrust inherited RCA prose; re-derive the mechanism.** A confident root-cause comment already
in the tree is a hypothesis with good PR, not evidence. The `symbols.map` comment actively misframed
the investigation. Re-derive from first principles / a minimal repro before building on someone's
stated cause.

**G6. Gate every push with the cheapest check that would have caught the last failure.** `bash -n` for
shell, a standalone `ld --version-script` parse for version maps, a local link for linker-flag changes.
We lost a full CI round to an unbalanced quote; the gate cost two seconds and was only added *after*
the loss. Maintain a short pre-push checklist that grows by one line each time CI catches something a
local check could have.

**G7. Pick the test loop by failure class, not by habit.** Build/toolchain/linkage bugs → local
container (fast, deterministic, inspectable). Genuine multi-process/JVM-runtime behavior (the actual
teardown abort) → CI, because it needs the full Spark fork. State *which* loop a given check belongs in
and why, so the local-vs-CI choice is principled rather than oscillating.

**G8. Build a minimal toy for any subtle mechanism.** The cross-free toy paid for itself many times
over: it made the 2×2 diagonal undeniable, de-risked the holistic design, and is now permanent
teaching material. For load-order/interposition/allocator/ABI bugs, a 50-line reproduction beats
paragraphs of argument.

**G9. The smallest fix that removes the invariant beats the cleverest fix that manages it.** The final
fix *deleted* code (drop `-static`, delete the conditional map, delete the staging machinery) and was
strictly smaller than the failed ship-a-lib approach. When the durable fix is *more* machinery than the
band-aid, suspect you haven't found the root cause yet.

**G10. Spend tokens on action and measurement, not re-summarization.** Several sessions emitted long
status recaps at every checkpoint and one forked session mostly re-derived known state. Keep a single
living STATUS doc, update it, and otherwise act.

---

# Part II — The RCA routine (use this next time)

A repeatable procedure for "we were green on a clean branch, we merged feature work, now CI is broken."
It has two patterns. **Pattern 1 (minimum-diff A/B)** finds *what* unmerged code triggers the failure.
**Pattern 2 (probe the dirty box)** is the empirical fix loop you run once you know roughly where the
problem is. Pattern 1 is the part we under-used and it is **not optional**; Pattern 2 is the part we
over-used and did sloppily. Run Pattern 1 first whenever you can.

## Step 0 — Frame the problem correctly (the premise that must stay front-of-mind)

```
clean branch (green)  +  unmerged feature code  →  CI broken
```

Therefore: **the trigger `X` is a subset of the unmerged diff.** Not the base image (it didn't change),
not "flaky infra" (until proven), not "an old known issue" (it was green before). Keep this premise
explicit in the investigation — every time you catch yourself blaming the environment, the toolchain
age, or a pre-existing condition, re-ask: *then why was it green before this diff?* (In this saga,
"we've used this image for a long time, why now?" is exactly the question that broke the gcc13 red
herring. The environment is a *constant*; the variable is the diff.)

Caveat to the premise: a merge can *unmask* a latent base problem (the diff changes load order /
link composition so a pre-existing fragility now fires). That's still "the diff is the trigger" — the
diff is what flipped it — but the *fix* may live in base code. Distinguish "X is the trigger" from
"X is where the fix goes" and say which you mean.

## Step 1 — Pin the green invariant before you touch anything

Find the last-green run and record **what was true in the green state** — not just "it passed," but the
*invariant* the green build satisfied. For a linkage/native bug that means concrete, measured values:

- libstdc++ provenance + version (`nm -DC` `U` vs `T` for `operator new`/`delete`; `readelf -d` for
  `DT_NEEDED`; `strings | grep GLIBCXX`), per `.so`.
- snappy / protobuf / other duplicated-runtime versions and whether they're static or dynamic.
- the exact build image, toolchain (`g++ --version`, `-print-file-name`), and link flags.

This is the **target you must restore (or consciously change)**. Write it down; it is the yardstick for
Step 5. We learned this the hard way: the green invariant was "one allocator instance services every
`new`/`free` in the process." Every fix should be evaluated against *that*, not against "did CI pass."

## Step 2 — Pattern 1: minimum-diff A/B isolation (the mandatory checkpoint)

**Goal: cut `X` down to the smallest diff such that `without X → no repro` and `with X → repro`, with a
transparent, mechanism-level relation between that minimum diff and the failure symptom.** A sound RCA
*must* contain this checkpoint. If you cannot state "toggling exactly this, and nothing else, flips the
symptom," you do not yet have an RCA — you have a guess that happens to go green.

Note what A/B means here: **toggle the *unmerged code*, not your candidate fix.** "With my fix it's
green" tells you your patch suppresses the symptom; it does *not* isolate the cause. "With feature code
X present it repros, with X excluded it doesn't" isolates the cause. These are different experiments;
do the cause-isolation one.

**Shrinking `X` — go from both ends:**

- **Clean → dirty (find solid ground first).** Start from the least-dirty build that still compiles and
  add unmerged code back in slices until the symptom appears. When you have no good hypothesis, this is
  the safer direction because each step is known-good-so-far. *Worked example:* turning `enable_hudi_mor`
  **OFF** (PR #350) stripped out most of the new code (no hudi-rs, no rocksdbjni, the MOR codepaths
  dark) — a near-clean ground. The abort *still* fired, which immediately told us `X` was **not** the
  hudi-rs/rocksdbjni code and **not** feature-gated at all — narrowing `X` to something compiled
  unconditionally (the `symbols.map` change).
- **Dirty → clean (excise slices from the full build).** Start from all-dirty and remove excludable
  chunks one at a time. Harder — it requires the diff to *be* decomposable into independently-removable
  pieces, which is case-specific and a judgment call. Use it when clean→dirty can't isolate far enough,
  or to confirm from the other side. *Worked example:* PR #356 reverted **only** the `local:*` std-hide
  (one slice of the diff) on an otherwise-full build → that single revert flipped the symptom → `X` =
  the std-hide line, full stop.

**Two outcomes once `X` is minimal — decide which:**

1. **`X` is not self-contained** — it's correct in isolation but needs additional patches to coexist
   with the rest (e.g. it assumes a sharing/visibility contract the surrounding code doesn't provide).
2. **`X` is implemented wrong** — it must be revised or removed.

You cannot choose the fix until you know which of these it is, and you can't know that without the
minimum-diff cut. (Our `X` was the std-hide; the honest classification was "not self-contained *and*
the chosen mechanism — symbol visibility — cannot satisfy both coexistence requirements at once," which
is what forced the holistic fix rather than another patch.)

## Step 3 — Pattern 2: probing the all-dirty box (the empirical loop), done right

This is the "add logs, try configs, propose fixes against the full repro" loop. It's legitimate — but
this saga shows three ways to do it far better:

**3a. Reproduce locally in the *exact* environment.** Before iterating through CI, find where the remote
setup is *defined* and reproduce it locally. Ask explicitly: *where does the thing I saw remotely come
from?* — the workflow YAML names the container image (`apache/gluten:1.5-vcpkg-centos-7`), the build
script names the toolchain (`source /opt/rh/devtoolset-11/enable`), the artifact step names what's
shipped. Pull that image, mount the repo, run the step. The 4m38s local centos-8 repro anchored the
whole symbols.map RCA; the `nm -DC` measurement in the real container ended the ship-a-lib dead end in
minutes. **Never anchor a conclusion in an environment that structurally can't show the bug** (the ws1
Ubuntu host links libstdc++ dynamically, so it could never exhibit the static-duplication abort — every
"result" there was non-evidence).

**3b. Parallelize the config matrix across PRs — don't serialize.** CI is slow; your hypotheses are
independent. If you have candidate fixes `a1, a2, b1, c2`, fire `a1`, `a1+a2`, `b1`, `c2` as separate
PRs **at once** and read them together, rather than one-fix-per-round. (We did this well in places and
poorly in others; do it deliberately every time. Also: one variable per PR so each result is
interpretable — the gcc13 PR bundled toolchain + Arrow + a cherry-pick and became uninterpretable.)

**3c. The multi-setup fix-reconciliation rule — the trap we fell into.**

This is the most important and the one we got wrong. Suppose you find:

> fix `f1` makes setup `s1` green, and a *different* fix `f2` makes setup `s2` green.

(Our case: `f1` = hide std → works for `s1` = feature **ON**; `f2` = export std (no-hide) → works for
`s2` = feature **OFF**. The conditional `symbols.map` shipped *exactly this* — pick `f1` or `f2` by the
feature flag.) **Before accepting that, you must answer three questions, and answer them from evidence,
not imagination:**

1. **Does `f2` cover the same failure as `f1`?** If they fix the *same* underlying issue, you should be
   able to find one fix that works for both setups — having two is a smell.
2. **If `f1` and `f2` are genuinely different fixes, then `s1` and `s2` must differ in *which code path
   is exercised* — what is that difference, and why does it make sense?** (For us: `s2`=OFF doesn't load
   rocksdbjni, so Trigger B can't occur there; `s1`=ON does. That part was real.)
3. **Is that `s1`/`s2` difference *allowed* for the end goal?** The end goal is **one fix for the
   all-dirty box that contains all the code.** If `s1` and `s2` can ever co-occur in a single shipped
   build, then a per-setup fix is not a fix — it's a coincidence that the two setups never overlap. **You
   must prove they are mutually exclusive, or unify the fix.**

**Where we failed:** we answered (1) and (2) loosely and *never pressed on (3)*. We let it loose —
"feature ON and the cross-free path don't happen in the same build, so the conditional is fine" — as an
*assumption*, without forcing the question "could they?" They could (a build with the feature on still
contains the gluten↔velox cross-free path); the conditional only survived because no single CI dim
exercised both. That is a knife-edge, and we shipped it as if it were a root fix. The discipline that
would have caught it: **treat "I need two different fixes for two setups" as an alarm, not a solution,
and refuse to close until you've either unified the fix or *proven* the setups are disjoint.**

**3d. Materialize `f1/s1/f2/s2` in a toy.** When you have a multi-setup situation, build a minimal toy
that reproduces `s1` and `s2` and shows `f1`/`f2` acting on each. A toy *forces* you to make every
assumption concrete — you can't hand-wave "these never co-occur" when the toy lets you run the
co-occurring case in one command. Our cross-free toy did exactly this: the 2×2 diagonal (`demo_global`
vs `demo_hidden` × `crossfree` vs `rocks`) made it undeniable that each visibility setting is fatal on
the other trigger, and the `both` case proved they *do* co-occur — which is precisely what the
conditional fix had assumed away. **If the conclusion rests on a claim about which setups can coexist,
a toy demonstrating it is required, not optional.**

## Step 4 — Converge to ONE fix for the all-dirty box

The deliverable is a single fix that makes the full build (all unmerged code, every setup) green —
*or* a rigorous proof that the setups are disjoint and a per-setup fix is therefore total. Default to
the former. In this saga the unification was: stop creating a second allocator instance at all (drop
`-static-libstdc++`), so there is nothing for visibility to arbitrate — one fix, every setup, no flag.

Sanity check from Q3-G9: **the smallest fix that removes the invariant beats the cleverest fix that
manages it.** If your "fix" is *more* machinery than the band-aid (we briefly shipped staging +
`LD_LIBRARY_PATH` + rpath), you probably haven't found the root cause.

## Step 5 — Reconcile against the green invariant (Step 1)

Re-measure the post-fix build and compare to the invariant you recorded in Step 1:

- Same libstdc++ provenance/version everyone shares? Same snappy/protobuf static-vs-dynamic posture?
- If the invariant is **restored** → strong evidence you're back to a known-good state.
- If the invariant **changed** → that is not automatically wrong, but you must **justify the change
  explicitly**: what is different now, why is the new invariant also correct, and what new risk does it
  carry? (Our fix *changed* the invariant — release libs gain a `DT_NEEDED libstdc++.so.6` and rely on
  the runtime system `.so.6` instead of an embedded copy. We justified it: system 3.4.33 ⊇ build 3.4.29,
  and it's the *same* image at build and run. An unjustified invariant change is an unshipped bug.)

## The RCA report template (raw evidence chain, mandatory shape)

Every RCA report must be a **raw, traceable evidence chain** — not a narrative summary. Concretely:

1. **Symptom (raw).** The exact error string, from **which job of which CI run (ID + URL), at which git
   SHA**, on which dimension. Quote the log line and line number, not a paraphrase.
2. **Green baseline + invariant.** The last-green run ID/SHA and the measured invariant (Step 1).
3. **Minimum-diff A/B (the checkpoint).** State `X`. Show the two runs: `without X → green` (run ID) and
   `with X → repro` (run ID), plus a local repro if available. This is the proof that `X` is the cause.
4. **Code walk-through (raw code + logging).** Step through the actual source, not a description of it,
   annotated with the log lines that prove each step executed — rigidly tracing the path from `X` to the
   symptom. (e.g. `operator new` resolves to libgluten's copy → object handed across JNI → freed via
   libvelox's copy → `_int_free` abort, with the symbolized backtrace frames quoted.)
5. **The fix, mapped onto the same chain.** The proposed fix, the **green run ID** that proves it, and a
   *second* code walk-through showing exactly how the problematic flow is altered — **map the old
   (repro) evidence chain onto the new (green) one, step for step**, so it's visible which link in the
   chain the fix breaks.
6. **Multi-setup justification (if applicable).** If the fix is `f1`-for-`s1` and `f2`-for-`s2`, you must
   justify why `s1` and `s2` are distinct *and* can never occur in one setup — **with a toy** that
   materializes both. (If you can't, the fix isn't done; unify it.)
7. **Invariant reconciliation (Step 5).** Restored, or changed-and-justified.

The report answers two questions unambiguously: **(a) what is the exact (minimal) unmerged code `X` that
causes the issue, proven by A/B?** and **(b) what is the fix, proven green, with the old→new evidence
chains mapped onto each other?**

## Prompt requirements (what to ask for next time, to force the above)

To avoid repeating the f1/s1·f2/s2 hallucination and the green-≠-fixed trap, the kickoff prompt for an
RCA task should state, explicitly:

- "The bug is in the unmerged diff. Isolate the **minimum diff `X`** via A/B (without-X green / with-X
  repro). Do not propose a fix before this checkpoint."
- "Reproduce locally in the **exact** CI environment first (name the image/toolchain from the workflow);
  don't anchor conclusions in a non-reproducing environment."
- "Measure the binaries (`nm`/`readelf`/`-print-file-name`); don't reason about linkage from belief."
- "Deliver **one fix for the full build**. If you find yourself needing different fixes for different
  setups, **stop and prove the setups can never co-occur, with a toy** — otherwise unify the fix."
- "Green CI is not acceptance. State the green invariant up front and show the fix restores it (or
  justify any change)."
- "The RCA report must be a raw evidence chain: symptom→run/SHA/log-line→A/B→code+log walk-through→
  fix+green-run→old/new chain mapping. No paraphrase-only conclusions."

---

### One-line takeaway
We already *knew* the root family on day one ("static libstdc++ symbol leak"); what cost five days was
**theorizing about linkage instead of measuring it on the real binaries, and accepting green CI as proof
of a root-cause fix** — most acutely, shipping a *two-fixes-for-two-setups* conditional without pressing
"could those setups ever co-occur?" The routine above is the antidote: isolate the minimum diff by A/B
(Step 2), refuse multi-setup fixes until proven disjoint *with a toy* (Step 3c/3d), converge to one fix
(Step 4), and reconcile against the measured green invariant (Steps 1 & 5).
