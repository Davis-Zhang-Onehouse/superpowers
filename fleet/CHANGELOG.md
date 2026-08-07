# fleet — changelog

## fleet/v0.3.10 — 2026-08-07T23:25:03Z
Cut from 0df31d2 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.9.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (1 file).

- 0df31d2 it: seed-check needs an argv recipe, or §L7 and §M5 say nothing about it

## fleet/v0.3.9 — 2026-08-07T22:08:46Z
Cut from 84355ef on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.8.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (6 files), skills (1 file).
Skills changed: using-fleet.

- 84355ef fleet: dispatch asserts the seed it rendered is the seed that was delivered

## fleet/v0.3.8 — 2026-08-06T15:01:17Z
Cut from 6626405 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.7.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (10 files), skills (1 file).
Skills changed: releasing-fleet.

- 6626405 fleet: the release's evidence, version and payload all describe the release

## fleet/v0.3.7 — 2026-08-06T06:49:18Z
Cut from b8dc466 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.6.

- b8dc466 fleet: the exemption was unreachable — release-cut's own stamp is in every diff

## fleet/v0.3.6 — 2026-08-06T06:41:24Z
Cut from 10147f1 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.5.

- 10147f1 docs: record the exemption design's outcome and the gate fix it forced

## fleet/v0.3.5 — 2026-08-06T06:13:23Z
Cut from 926fcdd on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.4.

- 926fcdd it: a claude-count check must attribute an addition, not just detect one

## fleet/v0.3.4 — 2026-08-06T05:11:24Z
Cut from 9833dd9 on `live` (upstream base pre-merge-fleet-skills-20260731). 3 commit(s) since fleet/v0.3.3.

- 54d1eb5 docs: design for release test exemption
- 0368435 fleet: a release that changes nothing the suites read is EXEMPT, not forced
- 9833dd9 skills: the release chain, and the traps that cost a gate run

## fleet/v0.3.3 — 2026-08-05T04:45:58Z
Cut from 3150f5a on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.2.

- 3150f5a fleet: a release drill marker, so v0.3.3 has a delta to carry

## fleet/v0.3.2 — 2026-08-04T20:08:12Z
Cut from 11f2f58 on `live` (upstream base pre-merge-fleet-skills-20260731). 3 commit(s) since fleet/v0.3.1.

- b9b0a08 skills: the close-out has a FIFTH step, and it is a second wait (FI-11)
- d07b4a2 skills: the release pipeline is documented where users look (G-6)
- 11f2f58 fleet: a dep that can NEVER land is actionable, not information

## fleet/v0.3.1 — 2026-08-03T01:32:45Z
Cut from c4a729a on `live` (upstream base pre-merge-fleet-skills-20260731). 4 commit(s) since fleet/v0.3.0.

- c8d44f0 fleet: the profiles fleet ships now pass fleet's own lint (FI-13)
- 11b2d13 fleet: a not-ready milestone's severity follows the REASON (FI-2)
- bd69a7f fleet: the coordinator can retire a superseded milestone (FI-10)
- c4a729a fleet: capture_pane can say it FAILED, fixing FI-7 at the source

## fleet/v0.3.0 — 2026-08-03T01:07:53Z
Cut from d73a528 on `live` (upstream base pre-merge-fleet-skills-20260731). 4 commit(s) since fleet/v0.2.4.

- 8f1323b it: a runner's exit status is a verdict, not a failure count
- 448c663 release: the worktree cleanup unfreezes, and the area keeps 10 releases
- b44891e fleet: one authority on whether a source can be harvested at all (FI-5)
- d73a528 fleet: a failed observation is not a negative one (FI-7)

## fleet/v0.2.4 — 2026-08-02T22:06:08Z
Cut from 4ab0270 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.2.3.

- 4ab0270 fleet: reap reports the claim it cannot yet judge (E9, both modes)

## fleet/v0.2.3 — 2026-08-02T19:31:09Z
Cut from 8fd20d9 on `live` (upstream base pre-merge-fleet-skills-20260731). 3 commit(s) since fleet/v0.2.2.

- 9767679 fleet: reconcile derives a severity, and a stranded slot is one
- ecae22c release: a release carries the evidence its FAIL rows cite
- 8fd20d9 fleet: the send contract is a condition, not a delay (FI-15 refuted and fixed)

## fleet/v0.2.2 — 2026-08-02T18:45:51Z
Cut from 956d168 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.2.1.

- 956d168 fleet: a stalled worker is actionable, and a proposal can carry a note

## fleet/v0.2.1 — 2026-08-02T18:14:30Z
Cut from b836240 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.2.0.

- b836240 it: mutant trees carry tests/, which the II-3 registry import needs

## fleet/v0.2.0 — 2026-08-02T17:50:04Z
Cut from 1944d67 on `live` (upstream base pre-merge-fleet-skills-20260731). 8 commit(s) since fleet/v0.1.1.

- 6f047c5 verify: the IT verdict comes from FAIL rows, not from an exit code
- b7b18a5 it: M9 resolves a call's receiver structurally, not by bare name
- 17b8c83 it: A1's aggregate names the sub-assertions that failed
- 80153b2 it: a missing argv fixture is a coverage gap, not a product defect
- b7c92c5 it: run-all.sh ends with a verdict, and group5 propagates its failures
- b3c9dde it: one implementation of the isolation contract, plus the part it cannot see
- dfb44de it: M9 reads the hermetic registry instead of restating it
- 1944d67 release: verify from a git worktree at the tag, not from the export

## fleet/v0.1.1 — 2026-08-02T08:22:50Z
Cut from f757d00 on `live` (upstream base pre-merge-fleet-skills-20260731). 2 commit(s) since fleet/v0.1.0.

- 7c489c4 plan: repoint the marketplace by file edit, never by the plugin CLI
- f757d00 P-2: pin the source without requiring a git repo it never consults

## fleet/v0.1.0 — 2026-08-02T07:57:30Z
Cut from e87d546 on `live` (upstream base pre-merge-fleet-skills-20260731). Initial release — no predecessor, so no commit range is listed.

