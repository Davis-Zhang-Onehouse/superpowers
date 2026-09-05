# Pinned multi-repo restacks

The worked example is a Gluten/Velox stack: `gluten-internal` is the primary repo, `velox-internal` is the
paired native repo, and each gluten commit resolves a velox commit through `ep/build-velox/src/get-velox.sh`.
The shape generalises to any stack where one repo's build pins another by sha.

## Why a pinned pair is not two independent stacks

The pin makes the primary chain's positions **depend on specific commits of the paired chain**, so the two
histories have to be rebased in a fixed order and re-linked afterwards:

```
velox   base ──▶ [11 kernel] ──▶ [12 kernel]
                     ▲               ▲
                     │ pin           │ pin
gluten  base ──▶ [11 wiring] ──▶ [12 routing] ──▶ [13 tests]
```

Rebase gluten without moving the pins and every position still builds — against the **pre-restack** velox
commits. Tests pass. The chain is wrong and nothing says so.

## Order of operations

1. **Paired repos first.** Chain them, so their post-restack shas exist.
2. **Then the primary**, one position at a time, updating the pin during each position's rebase rather
   than in a sweep afterwards. A sweep leaves intermediate positions pinned to old history, and those
   positions are what a bisect or a per-PR CI run actually builds.
3. **Retarget PR bases** in both repos.
4. **Grade the primary tip.**

## Twin lineages

A paired repo often carries a second lineage — an `-enhanced` variant, a vendor branch, a build with extra
features. It is a **parallel chain that must be restacked identically**, and its PRs retargeted the same
way.

The trap is that the primary chain usually pins only one of the two, so the twin has no pin pulling it
into the grade. It can be left un-chained and nothing downstream complains until somebody builds that
variant. Restack the twin in the same pass, and record its tips beside the main ones.

## Proving the pins

Per position, resolve the pin **from the tree**, not from your commit message:

```bash
git show "<position sha>:ep/build-velox/src/get-velox.sh" | grep -nE 'VELOX_REPO|VELOX_BRANCH|VELOX_ENHANCED_BRANCH'
```

Then assert the pinned commit is in the chained history:

```bash
git -C <paired repo> merge-base --is-ancestor <pinned sha> <paired chain tip>
```

And at the tip, the pin should equal the paired tip exactly.

**Cross-check against what CI actually built.** The native job logs name the commit they built. If the
build's commit and the pin disagree, the pin is not what is being tested — and that check is the only one
that catches a resolution path (a branch pin, a default, a cache) quietly overriding the sha you wrote.

## The grant, for a pinned pair

The enumerated force-push list spans both repos and is usually twice the size you first think, because
each primary position with a native half has a paired branch and possibly a twin. Write out every ref.
Positions below the fork point are excluded even though they are part of the same chain.

## Evidence to capture

- `git ls-remote` for **both repos**, before and after, as files.
- Pairwise `merge-base --is-ancestor` output for each repo's consecutive positions.
- Per position: the resolved pin, and the ancestry check that it is in the chained paired history.
- Per PR: `gh pr diff --name-only`, showing each PR's files-changed is only its own delta.
- The tip grade: the named job list, the sha, and evidence each job executed.

Capture proof **slices** and the command that regenerates them. Do not archive whole CI runs.

## Local builds

In a pinned pair the native artifacts in a workspace were built from whatever commit that slot was leased
at. After re-chaining the paired repo, they are stale for anything end-to-end — the source moved and the
`.so` did not.

Where a local native rebuild is unavailable or unreliable, use CI as the compiler and the grader, and say
in the report that you did. A local run against stale native artifacts is worse than no local run: it
produces a green you will believe.
