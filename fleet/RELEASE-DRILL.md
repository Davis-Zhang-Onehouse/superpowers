# Release drill

A deliberately inert marker file. It exists to give a release **content** — a cut with an empty delta
proves the plumbing moves but not that the plumbing moves anything.

## 2026-08-05 — v0.3.3

The first drill run through the whole gate rather than around it. Every release before it either stopped
at CANDIDATE or was deployed with `release-verify` skipped; `0.3.2` was force-deployed, UNVERIFIED, on
2026-08-04, and this drill is the run that was promised to follow it.

Nothing imports this file, no test asserts on it, and `fleet verify` does not read it — it reads an
*instant's* `RUNBOOK.md` and `evidence/INDEX.md`, not the repository's docs. It is safe to append to.
