# Fleet executable pin and redraw follow-up

The standard real-Claude test initially passed its lifecycle checks only after the worker diagnosed
an older `fleet` earlier on its login shell's PATH. The first `brief` and `base-check` commands failed
with unknown runtime record fields: see `claude-before.md` and `claude-before-run.log`.

Dispatch now exports the matching absolute CLI path as `FLEET_BIN` and prepends that instruction to
the rendered seed before verifying delivery. The unit regression supplies an obsolete inherited
`FLEET_BIN` and verifies both launch and resume replace it. The seed body remains unchanged.
`claude-after.md` confirms the initial commands worked immediately. That run also caught a missing
`--instant` in the old P test's own proposal example, which was corrected.

The final P run passed all four acceptance checks plus isolation: `claude-final-run.log`,
`claude-final.md`, and `claude-final-session.json`. Its worker explicitly tested the wrong-lineage
refusal before repositioning, then reviewed, proposed, completed and was harvested. Remaining report
remarks concern the historical P fixture's blank charter sections and task wording; the two-runtime
runner supplies complete charters. The report's suggestion that a refused real proposal would reach
the inbox is an inference by that worker, not a behavior established by the test.

The fresh Codex two-worker lifecycle also passed after the executable pin and bounded redraw wait:
`runtime-after/codex/runner.log`, `commands.json`, `records.json`, `roadmap.json`, and the session exports
record that run. Both workers used `FLEET_BIN`, received GO once, fixed the test with captured evidence,
reviewed, proposed, completed, and were harvested before switch-back.

One earlier Codex send stopped during input observation. `codex-stabilized-draft.frame` captures the
exact matching draft visible immediately afterward. Messaging now continues read-only observation of
indeterminate redraws within the existing deadline. It still refuses a non-idle pane before insertion,
requires an exact draft match before Enter, and never inserts or submits twice. Regression cases cover
both transient redraws and persistent uncertainty. Terminal exports omit trailing blank padding rows.

The native runs started with e848f11 as Git HEAD plus pending source changes. `source-verification.json`
compares every file in their unchanged before/after source pins with committed `8f3e892`: all 67 match.
Their environment metadata retains the original HEAD rather than relabeling the run retrospectively.
