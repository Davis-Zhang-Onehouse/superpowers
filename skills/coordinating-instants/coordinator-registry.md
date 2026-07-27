# Coordinator registry — the tables a coordinator instant adds to its HANDOFF

maintain-workspace gives you the canonical files (HANDOFF/CHARTER/RUNBOOK/DECISIONS/ISSUES/…). A
*coordinator* instant additionally maintains these four live registers inside HANDOFF.md (Part A). Copy
and adapt. Keep them a LATEST-STATE snapshot — churn belongs in git history, not the registry.

## 1. Milestone / task registry (the central state — one row per milestone)
| MR | Task | Disposition | Instant | Slot | Status | Proof / blocker |
|----|------|-------------|---------|------|--------|-----------------|
| MR1 | <what> | port \| rework \| sanction | `<child-instant-folder>` | wsN | ⬜ TODO \| 🔵 running \| 🅿 parked \| ✅ done \| ⛔ superseded | <PR / CI run / gate verdict, or the blocker> |

Status legend: ⬜ TODO · 🔵 dispatched/running · 🅿 parked (operator) · ✅ done (AC-proven + gated) · ⛔ superseded.
A row goes ✅ ONLY after `workspace review --all` passed and you harvested its delta into the catalog.

## 2. Fleet / slots (reconfirm via `pdispatch pool list` / `pdispatch board`)
| Slot | State | Holder instant | tmux | Note |
|------|-------|----------------|------|------|
| ws1 | LEASED \| FREE \| STALE | `<instant>` | `dt-<id>` | this coordinator lives in its own slot — never dispatch there |
| ws5 | LEASED (OTHER effort) | `<other-coordinator's instant>` | — | shared pool — NOT yours; never claim/reap until confirmed done + session dead |

Rule: the pool + board are GLOBAL across efforts. Each tick, reap STALE **that are yours** and fill every FREE slot
with the next ready milestone (or record why held) — but always confirm a slot isn't another effort's lease first.

## 3. Lineage tracker (instant dependency — what each new instant was built on)
| Instant | Base it inherited | Delivered end-state (branches @sha) |
|---------|-------------------|-------------------------------------|
| MR1 | fresh baseline @<sha> | <repo branch @sha> |
| Compaction #1 | MR0..MRk | <one stack/repo @sha> |
| MR(k+1) | Compaction #1 | … |

A new instant's base = the end-state it inherits (normally the latest compaction). Record it when you dispatch.

## 4. Single-writer catalog overlay
The canonical status catalog is `catalog/CATALOG.md` (or your registry). **You are its only writer.** Each
worker delivers a *proposed delta + CI evidence* in its own instant; you verify and apply it here. Pair it with
an append-only `sanctioned-flips` allowlist — one GOLD-justified entry per previously-green test that now flips
red for an intended reason. Never let a worker write this file.

The canonical baseline ITSELF can be superseded: if a better-grounded authoritative version is delivered mid-effort
(e.g. by a parallel exposure effort), re-seed from it and RECONCILE your existing fix-statuses onto the new body —
don't blindly overwrite it and don't blindly keep the old one.
