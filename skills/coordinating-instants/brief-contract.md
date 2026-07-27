# The brief contract — what every worker brief must contain

The profile supplies the CHARTER skeleton; the **brief** is what you author per milestone. Your own
completion signals (a report at a path you own, and the worker's folder rename) only exist because the brief
demanded them — so they are mandatory clauses, not niceties. Walk this list for every dispatch.

1. **Authority + read-first list.** Your CHARTER, the canonical registry, and the prior siblings' REPORTs
   whose work/seams this milestone INHERITS. Say which is authoritative if they disagree.
2. **Base + lineage.** The exact base instant/branches@sha this milestone builds on, and why (what end-state
   it inherits). One line, unambiguous.
3. **ACs — including negative results, and what a green actually PROVES.** What "done" means, testable.
   Explicitly: *if the target does NOT close, say so explicitly with evidence* — a worker that quietly
   redefines success is worse than a red run.
   **Every AC must name the path a green result proves was exercised, and how that is verified
   independently of the pass.** A test can go green without touching the thing you are claiming: a shared
   test trait can route the assertion to the reference implementation, a suite can be skipped and leave no
   result, a run can flake and be carried over. In all three the pass is real and the claim is false. Ask of
   each AC: *if the feature under test were absent entirely, could this still go green?* If yes, the AC is
   decoration — require a positive artifact that the intended engine/path ran (a plan probe, a config
   forced off its default, a named row in the result set), not the absence of a failure.
4. **Pipeline order + evidence location.** The non-negotiable sequence (e.g. local repro → RCA → fix → CI)
   and that all artifacts land under the instant's `evidence/`, never `/tmp`.
5. **The pinned baseline + analysis tool.** The exact baseline artifacts every worker diffs against, and the
   exact tool/variant to use — this is what makes deltas comparable ACROSS workers. Pin the lineage base too
   (the two-diff rule).
6. **Propose-only.** The worker delivers a *proposed* registry delta; it must never edit the canonical
   registry. (Check the rendered charter for a profile AC that contradicts this.)
7. **The gate.** Before renaming its folder it MUST run `superpowers:review-workspace` (all stages) on its
   own instant and PASS: READY, or READY-WITH-FIXES with no open Critical/Important, every AC verified on
   fresh evidence, recorded in `REVIEW.md`. No passing round = not complete.
8. **Report-back path + rename.** "Write `<your-instant>/dispatch/<MR>-REPORT.md`: AC results with evidence
   paths, branch tips, the proposed registry delta, the REVIEW verdict, and any operator forks. Then
   transition your folder `-inflight-` → `-complete-`." **These two are how you detect completion** — omit
   them and you are reduced to guessing.
9. **Autonomy horizon + parking rule.** How long the operator is away; park ONLY a genuine operator-only
   fork, and keep working every other unblocked step meanwhile. Tell it you will answer the forks that are
   yours to call.
10. **Resource + build isolation.** Private per-workspace build cache/local repo; which reference checkouts
    are shared READ-ONLY (write ⇒ worktree); anything else it must not touch.
11. **Budget ceiling.** Expensive-run allowance (e.g. "ONE CI run") — and that a failed or stale run does not
    count as evidence: it re-spends and reports the overrun rather than lowering the bar.

## After rendering, before launching
Review the child CHARTER + seed against the seven-item checklist in SKILL.md Phase B. The brief is what you
*asked for*; the rendered charter is what the worker will actually *read*. They drift — check both.
