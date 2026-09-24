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
from fleet.errors import BadInput
from tests.test_cli import Fleet

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
        self.assertEqual(rows.get("instant"), f"{child} (left in place; no verb deletes outward state)", out)
        self.assertTrue(rows.get("todo_id", "").startswith("saysWhat-"), out)
        self.assertIn("PENDING-LAUNCH", rows.get("record", ""), out)
        self.assertIn("fleet abort", rows.get("record", ""), out)
        self.assertTrue(rows.get("lease", "").startswith("given back"), out)
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
        self.assertTrue(rows.get("lease", "").startswith("given back"), out)

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
        self.assertTrue(rows.get("lease", "").startswith("retained"), out)
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
        self.assertEqual(rows.get("instant"), "(none created)", out)
        self.assertEqual(rows.get("record"), "(none written)", out)
        self.assertIsNone(self.fleet.pool.lease("ws1"))

    def test_human_output_carries_the_same_rows(self):
        self.seed_fails()
        code, out, err = self.fleet.run(["dispatch", "--profile", str(self.fleet.profile()),
                                         "--title", "says what", "--cap", "9"])
        self.assertEqual(code, NOT_STARTED, err)
        self.assertEqual([line.split()[0] for line in out.splitlines()][:2], ["error", "step"], out)


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
