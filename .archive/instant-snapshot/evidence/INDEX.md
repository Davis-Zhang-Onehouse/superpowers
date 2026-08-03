# evidence INDEX — criterion → artifact → source → how to regenerate
Updated: 2026-08-03 by session e7426760-8dc2-481c-a368-b80f1bce54eb | Status: LIVE

Every claim this instant makes cites a row here. A claim with no row is an opinion.

| criterion | artifact | source (what produced it) | regenerate |
|---|---|---|---|
| `A-1` — the briefs still describe the tree (the gate on starting ANY gap) | `2026-08-03-brief-reverification.txt` | `bin/reverify-briefs.sh` at `11f2f58`, tree CLEAN | `bash bin/reverify-briefs.sh` — exit 0 = every premise holds, exit 1 = read the rows first |
| `A-2` — the "six send paths" count | same artifact, row `A-2` | `DA-2`'s own text at `design-20260730-fleetInfraRefactor/09-OPEN-QUESTIONS.md:37` + a repo-wide count of real `send-keys` implementations | same command; row `A-2` |
| `AC-1` — every gap closed or re-deferred | the Status section of each `issues/G-*.md` | the closing commit named in each brief | `grep -A2 '^\*\*State:' issues/G-*.md` |
| `AC-1` / `G-6` CLOSED | `d07b4a2` | that commit + its tests | `git -C /home/ubuntu/davis_root/superpowers show d07b4a2 --stat` |
| `G-8` severity half fixed (the vocabulary half is still open) | `11f2f58` | that commit, 1183 tests green | `cd $REPO/fleet && PYTHONPATH=src python3 -m unittest discover -s tests` |
| ordering / sequencing rationale | `recommended-sequence.md` + `../PRIORITIES.md` | analysis, 2026-08-03 — argument, not measurement, and labelled as such | n/a (a judgement; its inputs are the rows above) |
| `G-2` symptom: the detector WORKS (so the gap is downstream) | `2026-08-03-repro-g2.txt` PART 1 + `repro-g2/part1-detector.txt` | `bin/repro-g2-stall-loop.sh` at `11f2f58`; drives `reconcile()` on the package's own `test_cli.Fleet` fixture | `bash bin/repro-g2-stall-loop.sh` |
| `G-2` root cause: every consumer is a VIEW | `repro-g2/part2-consumers.txt` | same script, PART 2 — content census over `fleet/src`, `scripts`, `skills`, `bin` | same command |
| **`FI-14`'s detector is guarded by NO test** (new, not in any brief) | `repro-g2/part3-mutations.tsv` + `repro-g2/mut{1,2,3}.out`, `baseline.out` | same script, PART 3 — mutation, baseline GREEN 1183 tests first, control M-2 KILLED | same command |
| `G-1` root cause: no send in the package | `2026-08-03-brief-reverification.txt` row `G-1` | `bin/reverify-briefs.sh` | `bash bin/reverify-briefs.sh` |
| `RA-1`/`A-6`: the type→Enter race is REAL, INTERMITTENT (1/5 at gap=0), and `pane-guard` after the type predicts the outcome 12/12 | `2026-08-03-ra1-send-race.txt` (narrative) + `.tsv` (rows) | `bin/probe-ra1-send-race.sh` on a real claude 2.1.220 pane, private tmux socket, loadavg 0.32, at `11f2f58`; derived from the parent instant's `probe2-timing.sh` with residue-clearing added | `FLEET_ALLOW_LIVE_CLAUDE=1 bash bin/probe-ra1-send-race.sh` |
| `G-1`: the correct contract exists only in a test script | `repro-g1/live-pane-submit.sh.txt` | `fleet/it/bin/live-pane.sh` `cmd_submit` @ `11f2f58` | `sed -n '/^cmd_submit/,/^}/p' $REPO/fleet/it/bin/live-pane.sh` |
| `G-1`: the one production send path uses a 150ms delay, not the condition; its `pane-guard` patch gates only BEFORE typing | `repro-g1/car-tmux-send.js.txt` | `claude-auto-retry/src/tmux.js:29-92,99-140`, vendored at `/home/ubuntu/davis_root/opt/car/…`, captured 2026-08-03 | `sed -n '29,92p;99,140p' /home/ubuntu/davis_root/opt/car/node_modules/claude-auto-retry/src/tmux.js` |
| `G-2`: the watchdog's "reconcile" is monitor lifecycle, not fleet's | `repro-g1/watchdog-reconcile.sh.txt` | `scripts/claude-watchdog.sh:180-235` @ `11f2f58` | `sed -n '180,235p' $REPO/scripts/claude-watchdog.sh` |
| the `G-1`+`G-2` why-chain, every node cited or flagged | `../investigations/g1-g2-stall-loop/analysis.md` | this RCA, 2026-08-03 | n/a — its citations regenerate via the two commands above |
| `D-8`: a parked child past the idle threshold reads `state=IDLE`, so a state-only nudge filter WOULD hit it | `2026-08-03-nudge-eligibility.txt` | `bin/probe-nudge-eligibility.sh` at `11f2f58` — four constructed situations through the package's own fixture | `bash bin/probe-nudge-eligibility.sh` |
| `G-11`: a freshly parked question is `PARKED` with `needs_a_human=False` — invisible to the attention count | same artifact, case 2 | same probe | same command |
| `G-10` CLOSED: the IDLE detector now has a test, proven by the mutation flipping `M-1`/`M-3` SURVIVED→KILLED by the NAMED test | `repro-g2/part3-mutations-BEFORE.tsv` + `-AFTER.tsv`, `repro-g2/mut1.out`, `repro-g2/mut3.out`, `repro-g2/baseline.out` | commit [`653ff90`](https://github.com/Davis-Zhang-Onehouse/superpowers/commit/653ff90) — `bash bin/repro-g2-stall-loop.sh` at that commit; baseline 1186 tests OK | `bash bin/repro-g2-stall-loop.sh` |
| `AC-2` — nothing regresses | **NOT YET CAPTURED** — no release cut since `d07b4a2`/`11f2f58` | — | `RUNBOOK.md` §"Release cycle" |
| `AC-3` — the briefs stay true at close-out | partially: the re-verification above covers each brief's CORE premise, not its whole body | `bin/reverify-briefs.sh` | `bash bin/reverify-briefs.sh` |
| `D-9` gate: attention population BEFORE `PARKED` joined the tuple | `2026-08-03-attention-before.txt` | `bin/measure-attention.sh before` against the real store at `fdccc8c` — 10 subjects, `NEEDS-YOU=1`, `ACTIONABLE_STATES=('BLOCKED', 'IDLE')` | `bash bin/measure-attention.sh before` |

## Gaps in this index, stated rather than implied
- **`AC-2` has no artifact at all.** Two commits have landed since `0.3.1` was verified and no release has
  been cut over them. Until one is, "nothing regresses" is an intention.
- **`bin/reverify-briefs.sh` has no control.** The charter requires that every fix to a check ship with a
  control proving the check still fails when it should. This check has none yet — a row could report
  `HOLDS` vacuously. Tracked as `G-9`; it must be built before the script's verdict is cited as proof of
  anything but its own rows.
