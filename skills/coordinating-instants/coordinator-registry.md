# Coordinator registry — the tables a coordinator instant adds to its HANDOFF

maintain-workspace gives you the canonical files (HANDOFF/CHARTER/RUNBOOK/DECISIONS/ISSUES/…). A
*coordinator* instant additionally maintains these four live registers inside HANDOFF.md (Part A). Copy
and adapt. Keep them a LATEST-STATE snapshot — churn belongs in git history, not the registry.

## 1. Milestone / task registry (the central state — one row per milestone)
| MR | Task | Disposition | Depends-on | Instant | Slot | Status | Proof / blocker |
|----|------|-------------|------------|---------|------|--------|-----------------|
| MR1 | <what> | port \| rework \| sanction | — \| MR0 | `<child-instant-folder>` | wsN | ⬜ TODO \| 🟨 READY \| 🔵 running \| 🅿 parked \| ✅ done \| ⛔ superseded | <PR / CI run / gate verdict, or the named blocker> |

Status legend: ⬜ TODO (not dispatchable yet) · 🟨 READY (dispositioned + ACs written + every `Depends-on`
LANDED) · 🔵 dispatched/running · 🅿 parked · ✅ done (AC-proven + gated + harvested) · ⛔ superseded.
Only 🟨 rows may fill a free slot. A row goes ✅ ONLY after a passing `superpowers:review-workspace` round,
the worker's own folder rename to `-complete-`, and your harvest of its delta into the catalog.

## 2. Fleet / slots (reconfirm via `pdispatch pool list` / `pdispatch board`)
| Slot | State | Holder instant | tmux | Note |
|------|-------|----------------|------|------|
| ws1 | LEASED \| FREE \| STALE | `<instant>` | `dt-<id>` | this coordinator lives in its own slot — never dispatch there |
| ws5 | LEASED (OTHER effort) | `<other-coordinator's instant>` | — | shared pool — NOT yours; never claim/reap until confirmed done + session dead |

Rule: the pool + board are GLOBAL across efforts. Each tick, reap STALE **that are yours** and fill every FREE slot
with the next ready milestone (or record why held) — but always confirm a slot isn't another effort's lease first.

## 3. Lineage tracker (instant dependency — what each new instant was built on)
| Instant | Base it inherited | Delivered end-state (branches @sha) | Note |
|---------|-------------------|-------------------------------------|------|
| MR1 | fresh baseline @<sha> | <repo branch @sha> | |
| Compaction #1 | MR0..MRk | <one stack/repo @sha> | gated ✓ — adoptable as a base |
| MR(k+1) | Compaction #1 | … | |
| MR(k+2) | MR(k+1) end-state | … | `restack-pending` — dispatched while Compaction #2 was in flight |
| MR(k+3) → successor | (same milestone, continued) | … | succession: predecessor flushed; do NOT restart |

A new instant's base = the end-state it inherits (normally the latest **gated** compaction). Record it when
you dispatch. Dispatches made while a compaction is in flight are marked `restack-pending` — the next
compaction must fold them. Record a worker succession here too, so the milestone's history stays one thread.

## 4. Single-writer catalog overlay
The canonical status catalog is `catalog/CATALOG.md` (or your registry). **You are its only writer.** Each
worker delivers a *proposed delta + CI evidence* in its own instant; you verify and apply it here. Pair it with
an append-only `sanctioned-flips` allowlist — one GOLD-justified entry per previously-green test that now flips
red for an intended reason. Never let a worker write this file.

The canonical baseline ITSELF can be superseded: if a better-grounded authoritative version is delivered mid-effort
(e.g. by a parallel exposure effort), re-seed from it and RECONCILE your existing fix-statuses onto the new body —
don't blindly overwrite it and don't blindly keep the old one.
