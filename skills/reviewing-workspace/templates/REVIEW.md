# <Effort> — REVIEW   (GENERATED VIEW of .fleet/review.json — regenerated in full on every render; hand edits are discarded)
Updated: <date> by session <uuid>  |  Status: GENERATED VIEW

Records every review round for this instant: findings, their status, and the action taken —
the audit trail from "comment raised" to "comment addressed". Newest round on top. Findings are recorded
through `fleet review --finding`, which is what writes the ledger this view is rendered from; reasoning
that must survive belongs in REVIEW-NARRATIVE.md, which nothing regenerates.

## Round R<n> — <date> · trigger: <on-demand | pre-complete> · scope: <all | format | alignment | code>
Note: <why this round ran, from --note>
Git snapshot (from HANDOFF PR-stack table):
| Repo | Branch | Tip sha at review |
|------|--------|-------------------|
| <repo> | <branch> | <sha> |

### Stage 1 — Format & hygiene   (verdict: PASS | FIXED | ISSUES)

#### RV-<n> — <short title>
- Stage: format | Severity: Critical | Important | Minor | Auto-fix
- Status: OPEN | ADDRESSED | SANCTIONED | WONTFIX
- Location: <file:line | PR #N>
- Finding: <what is wrong>
- Why it matters: <the invariant/consequence>
- Action taken (<date>): <auto-fix applied / flagged for operator / sanctioned because …>
- Verified-by: <artifact path or command>

### Stage 2 — Goal alignment   (verdict: ALIGNED | GAPS)

Chain: setup-to-begin → deliverables → evidence → acceptance → goal. Per acceptance criterion:

#### AC-<id> — <name> : VERIFIED | INSUFFICIENT | MISALIGNED
- Evidence: <evidence/INDEX row + artifact, or "MISSING: <what is needed>">
- Note: <how it chains, or the misalignment vs a charter constraint/philosophy>
- (record any raised gap as an RV-<n> finding below with Stage: alignment)

### Stage 3 — Code review   (verdict: CLEAN | ISSUES | N/A)

Reviewed (delta since last round):
| PR | Base sha | Head sha (this round) | Prev-reviewed head | Verdict |
|----|----------|-----------------------|--------------------|---------|
| <#N link> | <sha> | <sha> | <sha or "first review"> | Yes/No/With-fixes |

Skipped (inherited from base instant, reviewed upstream): <PR list or "none">

#### RV-<n> — <short title>
- Stage: code | Severity: Critical | Important | Minor
- Status: OPEN | ADDRESSED | SANCTIONED | WONTFIX
- Location: <file:line in PR #N>
- Finding / Why it matters / Action taken (<date>) / Verified-by: <…>

<!-- HEADING SHAPE — the gate parses these, so keep them literal:
     single round      : "## Round summary — overall verdict: <VERDICT>"
     multiple rounds   : "## Round R<n> summary — overall verdict: <VERDICT>"   (one per round)
     The verdict token must be one of READY | READY-WITH-FIXES | NOT-READY. Bold is fine.
     The counts line must name Critical and Important with numbers; either
     "- Open findings: Critical <n> · Important <n> · Minor <n>" or
     "- Open Critical: <n> · Open Important: <n> · Open Minor: <n>" parses. -->
## Round summary — overall verdict: READY | READY-WITH-FIXES | NOT-READY
- Stage verdicts: format=<…> · alignment=<…> · code=<…>
- Open findings: Critical <n> · Important <n> · Minor <n>
- Recommendation: <e.g. "resolve RV-3 (AC-4 evidence) before mv …-complete-…">
