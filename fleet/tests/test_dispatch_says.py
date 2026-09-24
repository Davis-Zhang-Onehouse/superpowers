"""V23-B — `fleet dispatch` says what it did, on STDOUT, whether or not it started a worker.

Measured at 0.6.10 (`investigations/RCA-v23b.md` in the V23-B instant): every dispatch that did not start a
worker wrote NOTHING to stdout — a tmux refusal, a launcher that exited early, the admission lock, a named slot
already leased. The only trace was a paragraph on stderr. The exit code was whatever the surfacing exception
carried, so a tmux refusal after the claim exited 2, the caller-typo code. The quanton coordinator's wrapper
filtered that output and reported `NO CHILD` four times with no cause (v2-05, v2-14). And `--title
gdwsites-09240324` silently became `gdwsites09240324`, so the same wrapper globbed for a folder that could not
exist (v2-19, v3-01).

The contract these cases pin (the V23-B instant's DECISIONS D-1):
* a non-start writes a `refused` (exit 3/4) or `error` (exit 1/2/5) row to stdout, beside `title_as_used`;
* a failure AFTER the claim — a launch attempted and rolled back — exits `5 not-started`, whatever exception
  surfaced, and names the step, the todo, the instant, the record and the lease it left;
* every dispatch, dry-run included, prints `title_as_used`, and `title_rewritten` when the name differs.
"""
import fcntl
import shutil
import unittest
from unittest import mock

from fleet import EXIT_BAD_INPUT, EXIT_CODES, EXIT_NO_CAPACITY, EXIT_OK, EXIT_REFUSED
from fleet import cli, seedcheck
from fleet.errors import BadInput, Refused
from fleet.errors import FleetError
from fleet.roadmap import Milestone, Roadmap
from tests.test_cli import CliCase, Fleet

#: Written as the NUMBER, so a base without the constant fails on the behaviour rather than on an import.
NOT_STARTED = 5


def kv(out: str) -> dict:
    """The porcelain rows as {key: value}. A key seen twice is a defect of its own, so it fails here."""
    rows = {}
    for line in out.splitlines():
        key, _, value = line.partition("\t")
        assert key not in rows, f"row {key!r} printed twice: {out!r}"
        rows[key] = value
    return rows


class DispatchCase(unittest.TestCase):
    def setUp(self):
        self.fleet = Fleet()
        self.addCleanup(shutil.rmtree, self.fleet.tmp, ignore_errors=True)

    def dispatch(self, *extra, title="says what"):
        return self.fleet.run(["dispatch", "--profile", str(self.fleet.profile()), "--title", title,
                               "--cap", "9", "--porcelain", *extra])

    def seed_fails(self):
        original = self.fleet.context

        def context():
            build = original()

            def candidate(parsed, out, err):
                ctx = build(parsed, out, err)
                ctx.seed_delivery = lambda name, text: seedcheck.Verdict(seedcheck.NOT_DELIVERED)
                return ctx
            return candidate
        self.fleet.context = context

    def start_raises(self, exc):
        def start(name, cwd, cmd):
            self.fleet.started.append((name, str(cwd), cmd))
            raise exc
        self.fleet.sessions.probes.start_session = start


class TestAFailureAfterTheClaimIsNotStarted(DispatchCase):
    """N1/N2 of the measurement: the launch was attempted, rolled back, and the caller was told only on stderr."""

    def test_a_tmux_refusal_exits_5_with_an_error_row_not_the_bad_input_code(self):
        self.start_raises(BadInput("tmux refused to start 'dt-saysWhat': duplicate session: dt-saysWhat"))
        code, out, err = self.dispatch()
        self.assertEqual(code, NOT_STARTED, err)
        self.assertNotEqual(code, EXIT_BAD_INPUT, "a tmux refusal after the claim is not a caller's typo")
        rows = kv(out)
        self.assertTrue(rows.get("error", "").startswith("BadInput: tmux refused to start 'dt-saysWhat'"), out)
        self.assertEqual(rows.get("step"), "tmux new-session", out)
        child = str(self.fleet.instants / next(p.name for p in self.fleet.instants.iterdir()))
        #: RV-C6. Bare values under keys a success never prints: a reader that cds into `instant` after a
        #: success, or treats `todo_id` as "it started", must not match a non-start.
        self.assertEqual(rows.get("left_instant"), child, out)
        self.assertTrue(rows.get("left_todo_id", "").startswith("saysWhat-"), out)
        self.assertEqual(rows.get("left_record"), "pending-launch", out)
        self.assertEqual(rows.get("left_lease"), "given-back", out)
        self.assertIn("fleet abort --instant", rows.get("remedy", ""), out)
        for success_key in ("instant", "todo_id", "record", "lease", "launched_at"):
            self.assertNotIn(success_key, rows, out)
        self.assertEqual(rows.get("title_as_used"), "saysWhat", out)
        #: stderr keeps the human paragraph; only the data stream was missing.
        self.assertIn("dispatch rolled back", err)
        self.assertIn("tmux refused to start", err)

    def test_an_unverified_seed_exits_5_naming_the_seed_step(self):
        self.seed_fails()
        code, out, err = self.dispatch()
        self.assertEqual(code, NOT_STARTED, err)
        rows = kv(out)
        self.assertTrue(rows.get("error", "").startswith("FleetError: Seed delivery to dt-saysWhat is not verified"),
                        out)
        self.assertEqual(rows.get("step"), "seed delivery", out)
        self.assertEqual(rows.get("left_lease"), "given-back", out)

    def test_an_unexpected_exception_in_the_launch_is_a_row_and_not_a_traceback(self):
        self.start_raises(RuntimeError("the probe fell over"))
        code, out, err = self.dispatch()
        self.assertEqual(code, NOT_STARTED, err)
        self.assertEqual(kv(out).get("error"), "RuntimeError: the probe fell over", out)
        self.assertIsNone(self.fleet.pool.lease("ws1"), "the rollback still gave the lease back")

    def test_a_lease_the_rollback_had_to_keep_is_named_as_retained(self):
        self.seed_fails()
        #: A kill that does not end the session: the rollback must keep the lease, and say so in the row too.
        self.fleet.sessions.probes.kill_session = lambda name: (self.fleet.killed.append(name),
                                                                self.fleet.tmux_live.add(name))
        original_start = self.fleet.sessions.probes.start_session
        self.fleet.sessions.probes.start_session = lambda name, cwd, cmd: (original_start(name, cwd, cmd),
                                                                            self.fleet.tmux_live.add(name))
        code, out, err = self.dispatch()
        self.assertEqual(code, NOT_STARTED, err)
        rows = kv(out)
        self.assertEqual(rows.get("left_lease"), "retained", out)
        self.assertIn("still observable", rows.get("remedy", ""), out)
        self.assertIsNotNone(self.fleet.pool.lease("ws1"))

    def test_a_render_failure_keeps_the_code_its_dry_run_gives(self):
        #: An unresolved placeholder is the profile author's input: the dry-run answers 2, so the real call
        #: does too — still with the rows, and still after giving the lease back.
        profile = self.fleet.profile_with_charter("{{NOT_A_KEY}}")
        base = ["dispatch", "--profile", str(profile), "--title", "says what", "--cap", "9", "--porcelain"]
        dry, _, dry_err = self.fleet.run(base + ["--dry-run"])
        code, out, err = self.fleet.run(base)
        self.assertEqual(dry, EXIT_BAD_INPUT, dry_err)
        self.assertEqual(code, dry, err)
        rows = kv(out)
        self.assertTrue(rows.get("error", "").startswith("BadInput:"), out)
        self.assertEqual(rows.get("step"), "render", out)
        self.assertEqual(rows.get("left_instant"), "(none)", out)
        self.assertEqual(rows.get("left_record"), "none", out)
        self.assertIsNone(self.fleet.pool.lease("ws1"))

    def test_a_refusal_at_a_step_the_dry_run_asks_is_a_refused_row(self):
        #: RV-C1. The claim lands on a DIFFERENT slot than the candidate the gates judged, and that slot is
        #: refused at `slot settings` (a codex linked-worktree slot). D-2 keeps the cause's exit 4, so the
        #: row must be `refused` too: a wrapper branching on the row kind must not read a rule as a crash.
        original_claim = self.fleet.pool.claim
        self.fleet.pool.claim = lambda **kw: original_claim(**{**kw, "slot": "ws2"})

        def refuse(runtime, path, verb):
            if str(path).endswith("ws2"):
                raise Refused("a codex worker cannot run in a linked-worktree slot",
                              clears_when="another slot", clears_who="the operator")
        with mock.patch.object(cli, "_refuse_codex_worktree_slot", refuse):
            code, out, err = self.dispatch()
        self.assertEqual(code, EXIT_REFUSED, err)
        rows = kv(out)
        self.assertTrue(rows.get("refused", "").startswith("Refused: a codex worker cannot run"), out)
        self.assertNotIn("error", rows, out)
        self.assertEqual(rows.get("step"), "slot settings", out)
        self.assertEqual(rows.get("clears_who"), "the operator", out)

    def test_a_rollback_whose_store_read_fails_still_answers_not_started(self):
        #: RV-C4. The rollback's own reads must not replace the launch error: the store read failing inside
        #: the rollback used to escape before the conversion, with no rows and the secondary error's code.
        self.seed_fails()
        original_all = self.fleet.store.all

        def all_records():
            if self.fleet.started:
                raise FleetError("records/x.json is not valid JSON")
            return original_all()
        self.fleet.store.all = all_records
        code, out, err = self.dispatch()
        self.assertEqual(code, NOT_STARTED, err)
        rows = kv(out)
        self.assertTrue(rows.get("error", "").startswith("FleetError: Seed delivery"), out)
        self.assertEqual(rows.get("left_record"), "unknown", out)
        self.assertIn("records/x.json is not valid JSON", rows.get("remedy", ""), out)
        self.assertEqual(rows.get("left_lease"), "given-back", out)

    def test_a_release_that_raises_an_os_error_is_a_retained_lease_not_a_new_answer(self):
        self.seed_fails()

        def release(slot, force=False, **kw):
            raise PermissionError(13, "Permission denied", "pool/leases/ws1")
        self.fleet.pool.release = release
        code, out, err = self.dispatch()
        self.assertEqual(code, NOT_STARTED, err)
        rows = kv(out)
        self.assertTrue(rows.get("error", "").startswith("FleetError: Seed delivery"), out)
        self.assertEqual(rows.get("left_lease"), "retained", out)
        self.assertIn("Permission denied", rows.get("remedy", ""), out)

    def test_an_interrupt_during_the_launch_still_rolls_back_and_stays_an_interrupt(self):
        #: RV-C5. A SIGINT (a wrapper's timeout, a Ctrl-C) in `tmux new-session` or the seed poll skipped the
        #: rollback entirely: the lease stayed claimed. It is rolled back now, and the interrupt is re-raised
        #: unchanged, so the caller's own interrupt handling still sees an interrupt.
        self.start_raises(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.dispatch()
        self.assertIsNone(self.fleet.pool.lease("ws1"), "an interrupted launch must still give the lease back")

    def test_human_output_carries_the_same_rows(self):
        self.seed_fails()
        code, out, err = self.fleet.run(["dispatch", "--profile", str(self.fleet.profile()),
                                         "--title", "says what", "--cap", "9"])
        self.assertEqual(code, NOT_STARTED, err)
        self.assertEqual([line.split()[0] for line in out.splitlines()][:2], ["error", "step"], out)


class TestALostMilestoneClaimNamesTheRecordAsItIs(CliCase):
    """RV-C2. The claim is the LAST step, after `launch record` stamped `launched_at` — so a lost claim race
    rolls back a record that reads launched, not PENDING-LAUNCH. The row must say what the store holds."""

    def test_the_record_row_reads_launched_after_a_lost_claim(self):
        fleet = self.loaded()
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id="M9", title="carried work", status="ready", deps=[], evidence=[]))

        def lose(self_, milestone_id, owner):
            raise FleetError("milestone 'M9' was claimed by another instant first")
        with mock.patch.object(Roadmap, "claim", lose):
            code, out, err = fleet.run(["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                                        "--title", "claim race", "--base", "00000000", "--optype", "append",
                                        "--cap", "99", "--from", str(coordinator), "--milestone", "M9"])
        self.assertEqual(code, NOT_STARTED, err)
        rows = kv(out)
        self.assertEqual(rows.get("step"), "milestone claim", out)
        self.assertEqual(rows.get("left_record"), "launched", out)
        self.assertNotIn("PENDING-LAUNCH", rows.get("remedy", ""), out)
        self.assertNotIn("PENDING-LAUNCH", err, "stderr must not call a launched record pending either")


class TestANonStartBeforeTheClaimKeepsItsCodeAndSaysSo(DispatchCase):
    """The v2-05/v2-14 field shape (a named slot already leased), the lock, and plain bad input."""

    def test_a_named_slot_already_leased_prints_a_refused_row_real_and_dry(self):
        code, out, err = self.dispatch("--slot", "ws1", title="holder")
        self.assertEqual(code, EXIT_OK, err)
        for extra in ((), ("--dry-run",)):
            with self.subTest(extra=extra):
                code, out, err = self.dispatch("--slot", "ws1", *extra)
                self.assertEqual(code, EXIT_NO_CAPACITY, err)
                rows = kv(out)
                self.assertTrue(rows.get("refused", "").startswith("NoCapacity: slot 'ws1' is already leased"),
                                out)
                self.assertNotIn("error", rows)
                self.assertEqual(rows.get("title_as_used"), "saysWhat", out)
                self.assertNotIn("step", rows, "nothing was claimed, so there is no launch step to name")

    def test_the_admission_lock_timeout_prints_a_refused_row(self):
        lock = self.fleet.home / ".runtime-admission.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a+") as holder:
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
            with mock.patch.object(cli, "ADMISSION_WAIT_S", 0.05):
                code, out, err = self.dispatch()
        self.assertEqual(code, EXIT_REFUSED, err)
        rows = kv(out)
        self.assertTrue(rows.get("refused", "").startswith("Refused: Another operation holds"), out)
        self.assertIn("clears_when", rows)
        self.assertIn("clears_who", rows)
        self.assertEqual(self.fleet.started, [])

    def test_bad_input_prints_an_error_row_and_keeps_exit_2(self):
        code, out, err = self.dispatch("--milestone", "M9")
        self.assertEqual(code, EXIT_BAD_INPUT, err)
        rows = kv(out)
        self.assertTrue(rows.get("error", "").startswith("BadInput: --milestone 'M9' names a row"), out)
        self.assertEqual(rows.get("title_as_used"), "saysWhat", out)

    def test_an_argument_error_prints_an_error_row_too(self):
        #: RV-C3. Refused by the parser, before any context exists: it used to be 0 stdout bytes.
        code, out, err = self.dispatch("--bogus-flag")
        self.assertEqual(code, EXIT_BAD_INPUT, err)
        rows = kv(out)
        self.assertTrue(rows.get("error", "").startswith("BadInput:"), out)
        self.assertIn("--bogus-flag", rows["error"], out)
        self.assertEqual(rows.get("title_as_used"), "saysWhat", out)
        self.assertIn("usage", err.lower(), "stderr keeps the usage text")

    def test_an_argument_error_with_no_title_says_no_title_was_used(self):
        code, out, err = self.fleet.run(["dispatch", "--porcelain", "--profile", str(self.fleet.profile())])
        self.assertEqual(code, EXIT_BAD_INPUT, err)
        rows = kv(out)
        self.assertIn("error", rows, out)
        self.assertEqual(rows.get("title_as_used"), "(none)", out)

    def test_a_refusing_dry_run_and_its_real_call_print_the_same_refused_rows(self):
        #: RV-C7. The WIP cap refuses both: one caller comparing them must read one answer, not two shapes.
        code, out, err = self.dispatch("--slot", "ws1", title="holder")
        self.assertEqual(code, EXIT_OK, err)
        answers = []
        for extra in (("--dry-run",), ()):
            code, out, err = self.fleet.run(["dispatch", "--profile", str(self.fleet.profile()), "--title",
                                             "says what", "--cap", "1", "--porcelain", *extra])
            self.assertEqual(code, EXIT_REFUSED, err)
            rows = kv(out)
            answers.append({key: rows.get(key) for key in ("refused", "clears_when", "clears_who")})
        self.assertTrue(answers[1]["refused"].startswith("Refused: "), answers)
        self.assertEqual(answers[0], answers[1])

    def test_every_row_value_is_one_line(self):
        #: A refusal is a paragraph; as a FIELD it must stay one line, or `cut -f2` reads the wrong row.
        code, out, err = self.dispatch("--slot", "wsNope")
        self.assertEqual(code, EXIT_BAD_INPUT, err)
        self.assertIn("error", kv(out), "a non-start with no row cannot be judged one-line")
        for line in out.splitlines():
            self.assertEqual(len(line.split("\t")), 2, line)


class TestTitleAsUsed(DispatchCase):
    """v2-19/v3-01: the name the verb actually used, on every dispatch."""

    def test_a_rewritten_title_is_named_on_the_real_dispatch(self):
        code, out, err = self.dispatch(title="gdwsites-09240324")
        self.assertEqual(code, EXIT_OK, err)
        rows = kv(out)
        self.assertEqual(rows.get("title_as_used"), "gdwsites09240324", out)
        self.assertIn("'gdwsites-09240324'", rows.get("title_rewritten", ""), out)
        self.assertTrue(rows["todo_id"].startswith("gdwsites09240324-"), out)
        self.assertTrue(rows["instant"].endswith("-inflight-append-gdwsites09240324"), out)

    def test_the_dry_run_names_it_too(self):
        code, out, err = self.dispatch("--dry-run", title="gdwsites-09240324")
        self.assertEqual(code, EXIT_OK, err)
        rows = kv(out)
        self.assertEqual(rows.get("title_as_used"), "gdwsites09240324", out)
        self.assertIn("title_rewritten", rows, out)
        self.assertEqual(self.fleet.started, [])

    def test_a_title_used_verbatim_says_so_and_prints_no_rewrite_row(self):
        code, out, err = self.dispatch(title="plain")
        self.assertEqual(code, EXIT_OK, err)
        rows = kv(out)
        self.assertEqual(rows.get("title_as_used"), "plain", out)
        self.assertNotIn("title_rewritten", rows, out)

    def test_case_folding_alone_is_a_rewrite_too(self):
        #: `identity.camel` folds case (`ANSI` -> `ansi`), so `plainTitle` is used as `plaintitle`.
        code, out, err = self.dispatch(title="plainTitle")
        self.assertEqual(code, EXIT_OK, err)
        rows = kv(out)
        self.assertEqual(rows.get("title_as_used"), "plaintitle", out)
        self.assertIn("title_rewritten", rows, out)


class TestTheRewriteRuleIsStatedWhole(unittest.TestCase):
    """RV-C8. `identity.camel` has two rules beyond word breaks and case folding. A row naming the rule must
    name the rule that fired."""

    def test_a_digit_first_title_names_the_x_prefix(self):
        rows = dict(cli._title_rows("9 lives"))
        self.assertEqual(rows["title_as_used"], "x9Lives")
        self.assertIn("prefixed with x", rows["title_rewritten"])

    def test_a_title_with_no_letters_or_digits_names_todo(self):
        rows = dict(cli._title_rows("---"))
        self.assertEqual(rows["title_as_used"], "todo")
        self.assertIn("no letters or digits becomes todo", rows["title_rewritten"])


class TestTheNotStartedCodeIsRegisteredForDispatchOnly(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(getattr(cli, "DISPATCH_NOT_STARTED", None), NOT_STARTED)
        self.assertNotIn(5, EXIT_CODES, "the base registry is unchanged; 5 is dispatch's own extension")
        self.assertIn(5, cli.registered_codes("dispatch"))
        self.assertIn(5, cli.EXIT_CODES_ALL)
        for verb in sorted(cli.VERBS):
            if verb != "dispatch":
                self.assertNotIn(5, cli.registered_codes(verb), verb)


if __name__ == "__main__":
    unittest.main()
