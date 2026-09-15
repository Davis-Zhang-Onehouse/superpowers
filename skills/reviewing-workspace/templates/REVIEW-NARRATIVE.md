# REVIEW-NARRATIVE — <instant>
Updated: <date> | Status: LIVE

Reasoning behind the rounds in `.fleet/review.json`. `REVIEW.md` is the generated view and
`fleet review` rewrites it in full; this file is not regenerated.

## Hunt — T0 <sha>, <date>
Wave: format · alignment · code (one call to `fleet review` per reviewer, all at T0). Kind: hunt.
Defect family handed to the code lens: <list>.
<what each lens found that mattered, and why>

## Receive pass 1
| id | class | sites / commit | order | closed by |
|---|---|---|---|---|
Withdrawals: evidence/review/withdrawals-pass1.txt

### Noticed along the way
<one line per defect, oddity or doubt this pass met that no finding named — each already carried
into ISSUES.md with an owner or raised as a `routed` finding — or the single word `none`>

## Closure 1 — T_prev <sha> → T_now <sha>
CLOSURE: <CLEAN | REOPEN | ESCALATE>. <what came back NOT-CLOSED, REGRESSED or fix-introduced, if
anything>

## Stop-rule outcome
<READY at closure n | ESCALATED at pass n: family <…>, parked as <question>>
