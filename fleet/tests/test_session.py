import os, pathlib, shutil, subprocess, time, unittest, uuid
from fleet.session import (TMUX_SOCKET_ENV, LiveSession, Probes, SessionLayer, default_probes,
                           exact_pane_target, exact_session_target)

#: The bytes a REAL claude pane draws its caret with, measured rather than guessed:
#: `e2 9d af c2 a0` — U+276F then a NO-BREAK SPACE, not an ASCII space
#: (`evidence/04-integration/N/N3-caret-line.hex`). Every pane fixture below is assembled from these so
#: a fixture cannot pass on a character a real pane never emits.
CARET, NBSP = "\u276f", "\u00a0"


def box(text: str = "") -> str:
    """One input-box row exactly as a real pane renders it: caret, NBSP, then whatever is in the box."""
    return f"{CARET}{NBSP}{text}"


def layer(procs=(), panes=None, sessions=()):
    started, killed = [], []
    p = Probes(list_processes=lambda: list(procs),
               capture_pane=lambda n: (panes or {}).get(n, ""),
               has_session=lambda n: n in sessions,
               start_session=lambda n, cwd, cmd: started.append((n, cwd, cmd)),
               kill_session=lambda n: killed.append(n))
    return SessionLayer(p), started, killed

class TestLiveness(unittest.TestCase):
    def test_alive_prefers_the_process_then_falls_back_to_tmux(self):
        s, _, _ = layer(procs=[LiveSession(1, pathlib.Path("/ws1"), "dt-a")])
        self.assertTrue(s.alive("dt-a"))
        s2, _, _ = layer(sessions=("dt-b",))
        self.assertTrue(s2.alive("dt-b"))
        self.assertFalse(s2.alive("dt-c"))

    def test_enumeration_is_process_first_so_an_unrecorded_session_is_visible(self):
        # OBS-48: a `SCREEN` session with NO dispatch record sat idle 8d20h, invisible to every
        # records-first sweep. Starting from processes is the only direction that can see it.
        s, _, _ = layer(procs=[LiveSession(9, pathlib.Path("/elsewhere"), None)])
        self.assertEqual([x.pid for x in s.live()], [9])

class TestPanePredicates(unittest.TestCase):
    def test_unsubmitted_text_is_detected_from_the_LAST_lines_only(self):
        # Anchored to the tail: a prompt earlier in the buffer is scrollback, and treating history as
        # current state is how a watcher re-alarms its whole past on every restart.
        tail = "\n".join(["❯ scrollback from an hour ago"] + ["output"] * 40 + ["❯ ship it"])
        s, _, _ = layer()
        self.assertEqual(s.unsubmitted(tail), "ship it")

    def test_an_empty_box_with_placeholder_text_is_not_unsubmitted(self):
        s, _, _ = layer()
        for placeholder in ('❯ Try "fix the bug"', "❯ / for commands", "❯ # for memory"):
            with self.subTest(p=placeholder):
                self.assertIsNone(s.unsubmitted("output\n" + placeholder))

    def test_a_placeholder_in_the_box_with_a_real_prompt_in_SCROLLBACK_is_not_queued(self):
        """Strengthens M-15 (whole-buffer scan). The plan's original fixture put the stale prompt FIRST
        and the live one LAST, so any implementation keying on the LAST caret in its window is immune —
        tail and whole-buffer give the same answer, and the anchoring is unobservable. Task 4's
        implementer proved that by making a last-match variant survive M-15. This fixture inverts it:
        the real prompt is in scrollback and the current box is empty (placeholder), so a scan that
        looks outside the tail reports a queued instruction that does not exist — which would hold a
        resume forever on a pane nobody ever typed into. Filed as FI-12.
        """
        buf = "\n".join(["❯ a real instruction from an hour ago"] + ["output"] * 40 + ['❯ Try "fix the bug"'])
        s, _, _ = layer()
        self.assertIsNone(s.unsubmitted(buf))

    def test_no_prompt_means_nothing_queued(self):
        s, _, _ = layer()
        self.assertIsNone(s.unsubmitted("just output\nmore output"))

    def test_busy_is_detected_from_the_tail(self):
        s, _, _ = layer()
        self.assertTrue(s.busy("working…\nesc to interrupt"))
        self.assertFalse(s.busy("done"))


class TestTheInputBoxIsFoundStructurally(unittest.TestCase):
    """`FI-24` — one cause, three measured false answers. The predicate took the FIRST caret within 8 RAW
    capture lines; both halves of that are wrong against a real pane, and they are wrong in opposite
    directions. Every fixture here is a transcription of bytes captured off real tmux in §M/§N, not a
    guess about what a pane might look like."""

    def setUp(self):
        self.s, _, _ = layer()

    def test_a_SUBMITTED_message_clears_the_alarm(self):
        """`N4`, verbatim shape (`evidence/04-integration/N/N4-pane.txt`): the operator did exactly what
        `pane-guard` asked — submitted the text — and the shell left the submitted prompt on screen with
        the new EMPTY box below it. The first caret in the window is the echo of what was just sent, so
        the predicate reported `draft message` forever and `status` stayed BLOCKED: the sixth
        unclearable alarm of this build. The box is the LAST caret, and its being empty is the answer,
        not a reason to look further up.
        """
        pane = "\n".join(["filler line %d" % i for i in range(190, 201)] + [
            "? for shortcuts",
            box("draft message"),                      # what was SUBMITTED, echoed above the new box
            "Command 'draft' not found, did you mean:",
            "  command 'kraft' from deb kraft (0.97-1)",
            "Try: sudo apt install <deb name>",
            box(),                                     # the new, EMPTY input box
        ])
        self.assertIsNone(self.s.unsubmitted(pane),
                          "a submitted message still reads as queued: the alarm cannot be cleared by "
                          "doing what it asks")

    def test_a_box_high_in_the_pane_with_tmux_PADDING_below_it_is_not_safe(self):
        """`M11b` (`evidence/04-integration/M/M11b-pane.txt` + `.hex`): identical bytes in the box to the
        `N3` case that correctly returned 10, but the pane was short and tmux padded the capture to the
        PANE HEIGHT — 31 blank rows below the box. Counting raw lines put the box outside its own window
        and the verb answered 0 = safe with text in the box. A FALSE SAFE: the direction that
        concatenates a send onto somebody's half-typed message.
        """
        pane = "? for shortcuts\n" + box("draft message") + "\n" + "\n" * 31
        self.assertEqual(self.s.unsubmitted(pane), "draft message",
                         "tmux's bottom padding hid the input box: this is a false-safe")

    def test_a_stale_caret_above_the_box_is_scrollback_at_13_rows_AND_at_3(self):
        """`N8` passed before this fix — and passed for the wrong reason. Its stale caret happened to sit
        13 rows above the bottom, i.e. outside a window that happened to be 8, so the guarantee was *an
        8-line accident, not a property*. The 3-row fixture is the one that makes it a property: the
        empty box is the last caret at ANY distance, so no arithmetic between 3 and 13 can change the
        answer. Both cases assert the same thing, which is the point.
        """
        for gap in (13, 3):
            with self.subTest(rows_above_the_bottom=gap):
                pane = "\n".join(
                    ["history line %d" % i for i in range(1, 101)]
                    + [box("an old draft nobody sent")]
                    + ["later output %d" % i for i in range(1, gap - 1)]
                    + ["? for shortcuts", box()])
                self.assertIsNone(self.s.unsubmitted(pane),
                                  f"a caret {gap} rows up with an empty box below it is scrollback")

    def test_the_last_non_blank_row_anchors_the_window_so_a_padded_scrollback_caret_stays_out(self):
        """The other side of the padding fix, and the reason it is not simply "scan the whole buffer":
        stripping the padding must not drag history INTO the window. The stale caret is 40 rows above the
        empty box and stays out of it whether or not tmux padded underneath.
        """
        content = ["❯ a real instruction from an hour ago"] + ["output"] * 40 + [box()]
        for padding in (0, 31):
            with self.subTest(padding=padding):
                self.assertIsNone(self.s.unsubmitted("\n".join(content) + "\n" * padding))

    def test_busy_survives_the_same_padding(self):
        """`busy` read the same raw-line window, so padding hid an interrupt hint exactly as it hid a
        box. Not a case §M reached, but the same measured tmux fact and the same false direction — a
        mid-turn pane reading idle is what puts a send in the middle of a turn (FD-10)."""
        self.assertTrue(self.s.busy("working…\nesc to interrupt\n" + "\n" * 31))


class TestTmuxTargetsAreExact(unittest.TestCase):
    """`FI-23`, the worst defect of the build. tmux resolves a BARE `-t name` by PREFIX, so with only
    `itfleet-N-pre-ab` alive, `has-session -t itfleet-N-pre-a` exits 0, `capture-pane` returns the longer
    session's screen and **`kill-session` destroys it** — another worker's live pane, through the tool
    whose job is the naming isolation that prevents exactly that.

    The hermetic suite could not have caught it: `Probes` is injected, so no test in the package had ever
    met tmux's argument grammar. That is why the first test here asserts the argument SHAPE — the bytes
    handed to tmux — and not just the behaviour of a fake. A seam that is always faked needs one test
    that looks at what would have crossed it.
    """

    def targets_of(self, call):
        """Every argv `default_probes` hands to a subprocess while `call` runs."""
        seen = []
        real = subprocess.run

        def spy(argv, *args, **kwargs):
            seen.append(list(argv))
            # rc 0: a probe that treats a failure as "absent" would otherwise swallow the call and this
            # test would assert over an empty list.
            return subprocess.CompletedProcess(argv, 0, "", "")

        subprocess.run = spy
        try:
            call(default_probes())
        finally:
            subprocess.run = real
        return seen

    def test_every_tmux_TARGET_argument_carries_the_exact_match_marker(self):
        for label, call in (
            ("has-session", lambda p: p.has_session("itfleet-x")),
            ("capture-pane", lambda p: p.capture_pane("itfleet-x")),
            ("kill-session", lambda p: p.kill_session("itfleet-x")),
        ):
            with self.subTest(command=label):
                argvs = [a for a in self.targets_of(call) if label in a]
                self.assertTrue(argvs, f"{label} was never invoked, so this cell is vacuous")
                for argv in argvs:
                    self.assertIn("-t", argv, f"{label} was given no target at all: {argv}")
                    target = argv[argv.index("-t") + 1]
                    self.assertTrue(target.startswith("="),
                                    f"{label} was handed the BARE target {target!r}; tmux resolves that "
                                    f"by prefix, so it can land on a different session")
                    self.assertNotEqual(target, "itfleet-x")

    def test_the_pane_target_carries_the_trailing_colon_a_pane_target_needs(self):
        """Measured on tmux 3.2a (`evidence/04-integration/N/N7b-tmux-target-forms.txt`):
        `capture-pane -t =name` fails with *can't find pane* even for a session that EXISTS, because a
        pane target is parsed as `session:window.pane`. Getting this wrong fails SILENTLY and passes the
        prefix test vacuously — with `=name`, `pane(long)` and `pane(prefix)` are both "" and "the prefix
        did not return the longer session's screen" holds because nothing returned a screen.
        """
        self.assertEqual(exact_session_target("itfleet-x"), "=itfleet-x")
        self.assertEqual(exact_pane_target("itfleet-x"), "=itfleet-x:")
        argv = [a for a in self.targets_of(lambda p: p.capture_pane("itfleet-x"))
                if "capture-pane" in a][0]
        self.assertEqual(argv[argv.index("-t") + 1], "=itfleet-x:")

    def test_start_session_names_rather_than_targets_so_it_carries_no_marker(self):
        """`new-session -s` is not a target: it NAMES the session being created. A marker there would be
        part of the name. Asserted so the fix is not applied by pattern-match to a fourth call site."""
        argv = [a for a in self.targets_of(
            lambda p: p.start_session("itfleet-x", pathlib.Path("/tmp"), "true"))
            if "new-session" in a][0]
        self.assertEqual(argv[argv.index("-s") + 1], "itfleet-x")


class TestThePrivateTmuxServer(unittest.TestCase):
    """`W-1`. tmux's default socket is a SHARED namespace: two IT groups, the hermetic suite and the
    operator's own coordinator all landed on it. §M's runner created `itfleet-M-worker` there and §E's
    server-wide isolation assertion correctly failed — cross-agent contamination, not a product defect.

    The fix is a `-L <socket>` prefix, and it is a **parameter** rather than a hard-code (`SD-1`): in
    production `fleet` must see the operator's real sessions, because that is what `pane-guard` and a real
    dispatch are for. A tool hard-wired to the test server would be blind to the sessions it exists to
    guard. So the seam gets the capability and the harness supplies the value.

    These cases assert the argument SHAPE for the same reason `TestTmuxTargetsAreExact` does: `Probes` is
    injected everywhere else, so nothing in the package would otherwise meet tmux's argument grammar.
    """

    SITES = (
        ("list-panes", lambda p: p.list_processes()),
        ("capture-pane", lambda p: p.capture_pane("itfleet-x")),
        ("has-session", lambda p: p.has_session("itfleet-x")),
        ("new-session", lambda p: p.start_session("itfleet-x", pathlib.Path("/tmp"), "true")),
        ("kill-session", lambda p: p.kill_session("itfleet-x")),
    )

    def argvs_of(self, call, **kwargs):
        """Every argv `default_probes(**kwargs)` hands to a subprocess while `call` runs."""
        seen = []
        real = subprocess.run

        def spy(argv, *args, **kw):
            seen.append(list(argv))
            # rc 0, and stdout that `pgrep`'s consumer can parse: a probe that treats failure as
            # "absent" would swallow the call and leave this test asserting over an empty list.
            return subprocess.CompletedProcess(argv, 0, "", "")

        subprocess.run = spy
        try:
            call(default_probes(**kwargs))
        finally:
            subprocess.run = real
        return seen

    def tmux_argvs(self, call, **kwargs):
        return [a for a in self.argvs_of(call, **kwargs) if a and a[0] == "tmux"]

    def test_the_socket_flag_is_on_EVERY_tmux_invocation_and_precedes_the_subcommand(self):
        """All five sites, named individually. A socket on four of five is not isolation — the one that
        escapes is the one that reaches the live server, and `new-session` is the one that creates."""
        for label, call in self.SITES:
            with self.subTest(site=label):
                argvs = [a for a in self.tmux_argvs(call, tmux_socket="itfleet") if label in a]
                self.assertTrue(argvs, f"{label} never reached tmux, so this cell is vacuous")
                for argv in argvs:
                    self.assertEqual(argv[:3], ["tmux", "-L", "itfleet"],
                                     f"{label} was not sent to the private server: {argv}. `-L` is a "
                                     f"SERVER option and tmux requires it before the subcommand.")

    def test_pgrep_does_not_get_a_tmux_socket_flag(self):
        """`list_processes` spawns `pgrep` as well as `tmux list-panes`. Pattern-matching `-L` onto every
        argv in the function would hand `pgrep` a flag that means something else entirely."""
        pgreps = [a for a in self.argvs_of(lambda p: p.list_processes(), tmux_socket="itfleet")
                  if a and a[0] == "pgrep"]
        self.assertTrue(pgreps, "pgrep was never invoked, so this cell is vacuous")
        for argv in pgreps:
            self.assertNotIn("-L", argv, f"pgrep was handed tmux's server flag: {argv}")

    def test_without_a_socket_the_argv_is_byte_identical_to_the_default_server_form(self):
        """The regression guard on my own change: unset must mean today's behaviour exactly, because the
        shipped tool talks to the default server and W-5 dispatches a real `claude` onto it."""
        for label, call in self.SITES:
            with self.subTest(site=label):
                argvs = [a for a in self.tmux_argvs(call, tmux_socket=None) if label in a]
                self.assertTrue(argvs, f"{label} never reached tmux, so this cell is vacuous")
                for argv in argvs:
                    self.assertEqual(argv[0], "tmux")
                    self.assertNotIn("-L", argv, f"{label} grew a socket flag with no socket set: {argv}")

    def test_the_targets_are_still_EXACT_on_the_private_server(self):
        """`FI-23` must survive `W-1`. A fix that reshuffles the argv is exactly how an unrelated
        property gets dropped, so it is re-asserted here rather than assumed from the other class."""
        for label, call in (("has-session", lambda p: p.has_session("itfleet-x")),
                            ("capture-pane", lambda p: p.capture_pane("itfleet-x")),
                            ("kill-session", lambda p: p.kill_session("itfleet-x"))):
            with self.subTest(site=label):
                argv = [a for a in self.tmux_argvs(call, tmux_socket="itfleet") if label in a][0]
                self.assertTrue(argv[argv.index("-t") + 1].startswith("="),
                                f"{label} lost its exact-match marker: {argv}")

    def _with_env(self, value, call, **kwargs):
        had = os.environ.get(TMUX_SOCKET_ENV)
        if value is None:
            os.environ.pop(TMUX_SOCKET_ENV, None)
        else:
            os.environ[TMUX_SOCKET_ENV] = value
        try:
            return self.tmux_argvs(call, **kwargs)
        finally:
            if had is None:
                os.environ.pop(TMUX_SOCKET_ENV, None)
            else:
                os.environ[TMUX_SOCKET_ENV] = had

    def test_the_environment_supplies_the_socket_when_the_caller_does_not_name_one(self):
        """How the harness reaches a `python3 -m fleet.cli` subprocess it does not construct the probes
        for. `FLEET_HOME` is already explicit-by-environment; this is the same contract for the server."""
        argv = [a for a in self._with_env("itfleet", lambda p: p.has_session("itfleet-x"))
                if "has-session" in a][0]
        self.assertEqual(argv[:3], ["tmux", "-L", "itfleet"])

    def test_an_explicit_socket_of_None_overrides_an_environment_that_names_one(self):
        """`None` means "the default server" and must not be silently re-read from the environment, or a
        caller that has explicitly asked for the live server would be redirected by an inherited var."""
        argv = [a for a in self._with_env("itfleet", lambda p: p.has_session("itfleet-x"),
                                          tmux_socket=None) if "has-session" in a][0]
        self.assertNotIn("-L", argv)

    def test_an_empty_environment_value_means_the_default_server_not_a_socket_named_empty(self):
        argv = [a for a in self._with_env("", lambda p: p.has_session("itfleet-x"))
                if "has-session" in a][0]
        self.assertNotIn("-L", argv)


#: The suite's OWN private server. `W-1`/`SI-3`: this class used to create `itfleet-selftest-*` on the
#: DEFAULT socket, so every `python3 -m unittest discover` started and killed sessions on the operator's
#: live tmux server — the server a coordinator is attached to. It was never noticed because the harness's
#: isolation check only grepped that server for `dt-` names (`SI-1`), and these are not `dt-`.
#: Deliberately not `itfleet` (the IT harness's socket): the suite and an IT section must not share a
#: namespace either, which is the whole lesson of §M vs §E.
SELFTEST_TMUX_SOCKET = "itfleet-selftest"


def _tmux_is_available() -> bool:
    """Whether tmux is installed. Unlike the previous form, this does NOT require a server to already be
    running: on a private socket there is nothing to piggy-back on, and `new-session` starts that server
    itself. The old predicate asked the DEFAULT server whether it was up, which both coupled the case to
    the operator's machine state and made the skip silent precisely where isolation mattered most.

    The argument-SHAPE cases above hold with no tmux at all, so no property here is skip-dependent."""
    return bool(shutil.which("tmux"))


@unittest.skipUnless(_tmux_is_available(), "tmux is not installed")
class TestAgainstRealTmux(unittest.TestCase):
    """The one case in the suite that meets tmux itself. Everything else about a fleet is described
    through `Probes`; this asserts the thing a fake cannot assert, which is that tmux agrees.

    Isolation: every command here — including the fixture's own `new-session` and `kill-session` — goes to
    the private server `SELFTEST_TMUX_SOCKET`. The default server is not read, not written and not
    started, so no `dt-` session can be reached from this class even by a prefix accident. The session is
    also `itfleet-` prefixed, uniquely suffixed, and killed in `tearDown` whatever happens.
    """

    TMUX = ["tmux", "-L", SELFTEST_TMUX_SOCKET]

    def setUp(self):
        self.long = f"itfleet-selftest-{os.getpid()}-{uuid.uuid4().hex[:6]}ab"
        self.prefix = self.long[:-1]                   # ONE character shorter. Must not resolve.
        self.marker = f"itfleet-marker-{uuid.uuid4().hex[:8]}"
        # The pane PRINTS something, so "the prefix did not return the longer session's screen" can be
        # asserted on content rather than on two empty strings being equal.
        subprocess.run(self.TMUX + ["new-session", "-d", "-s", self.long, "-c", "/tmp",
                                    f"printf '%s\\n' {self.marker}; sleep 120"], capture_output=True)
        self.probes = default_probes(tmux_socket=SELFTEST_TMUX_SOCKET)
        deadline = time.monotonic() + 5
        while self.marker not in self.probes.capture_pane(self.long) and time.monotonic() < deadline:
            time.sleep(0.05)

    def tearDown(self):
        subprocess.run(self.TMUX + ["kill-session", "-t", exact_session_target(self.long)],
                       capture_output=True)

    def test_the_fixture_really_landed_on_the_private_server_and_not_the_default_one(self):
        """Without this the isolation claim in the docstring is prose. It is asserted the way `W-1`'s IT
        case asserts it: present on the private server, absent from the default one."""
        mine = subprocess.run(self.TMUX + ["ls"], capture_output=True, text=True)
        self.assertIn(self.long, mine.stdout,
                      "the fixture session is not on the private server, so every other assertion in "
                      "this class is either vacuous or running somewhere it must not")
        live = subprocess.run(["tmux", "ls"], capture_output=True, text=True)
        self.assertNotIn(self.long, live.stdout,
                         f"{self.long!r} is visible on the DEFAULT tmux server — the suite is creating "
                         f"sessions on the server the operator's coordinator is attached to (SI-3)")

    def test_a_one_character_prefix_does_not_resolve_to_a_longer_live_session(self):
        self.assertTrue(self.probes.has_session(self.long),
                        "the fixture session is not live, so every assertion below is vacuous")
        self.assertFalse(self.probes.has_session(self.prefix),
                         f"{self.prefix!r} does not exist and tmux said it does: the target is being "
                         f"resolved by PREFIX to {self.long!r}")
        layer_ = SessionLayer(self.probes)
        self.assertTrue(layer_.alive(self.long))
        self.assertFalse(layer_.alive(self.prefix))

    def test_the_pane_capture_of_a_prefix_is_not_the_longer_sessions_screen(self):
        of_long = self.probes.capture_pane(self.long)
        self.assertIn(self.marker, of_long,
                      "the REAL session's pane captured nothing recognisable, so the comparison below "
                      "would hold for the wrong reason — this is exactly what a pane target missing its "
                      "trailing colon looks like (FI-23's vacuity trap)")
        #: `FI-7` made a failed capture return None rather than `""`, and capturing a session that does
        #: not exist IS a failure — so the expected answer here is now None, which is strictly stronger
        #: than an empty string: it says tmux refused, rather than leaving the caller to infer it from
        #: emptiness. Both are accepted so this case keeps testing PREFIX TARGETING and does not quietly
        #: become a test of the probe's return convention.
        of_prefix = self.probes.capture_pane(self.prefix)
        self.assertNotIn(self.marker, of_prefix or "",
                         f"capturing {self.prefix!r}, which does not exist, returned {self.long!r}'s "
                         f"screen")
        self.assertIsNone(of_prefix,
                          "capturing a session that does not exist should FAIL, not return empty text — "
                          "that distinction is what FI-7 turned on")

    def test_killing_a_prefix_does_not_destroy_the_longer_session(self):
        """The hazard itself. Before the fix this call DID destroy `itfleet-repro-ab`
        (`evidence/04-integration/N/N7c-tmux-kill-prefix.txt`, rc 0)."""
        self.probes.kill_session(self.prefix)
        self.assertTrue(self.probes.has_session(self.long),
                        f"killing the non-existent {self.prefix!r} destroyed the live {self.long!r}")


class TestControl(unittest.TestCase):
    def test_start_and_kill_go_through_the_probes(self):
        s, started, killed = layer()
        s.start("dt-a", pathlib.Path("/ws1"), "claude --foo")
        s.kill("dt-a")
        self.assertEqual(started, [("dt-a", pathlib.Path("/ws1"), "claude --foo")])
        self.assertEqual(killed, ["dt-a"])

class TestTrustModalIsNotBusy(unittest.TestCase):
    """`SI-37`. The folder-trust modal is a pane WAITING ON A HUMAN, not a pane doing work.

    Both states offer an escape key and the strings read alike, which is exactly why this was wrong for as
    long as it was. The distinction is not cosmetic: "busy" means a send queues behind a turn that will
    finish on its own, and "waiting" means nothing happens until somebody answers. Measured on the first
    production dispatch, where a coordinator sat at an unanswered trust prompt while `board` said RUNNING.
    """

    TRUST_MODAL = (
        "Quick safety check: Is this a project you created or one you trust? (Like your\n"
        "own code, a well-known open source project, or work from your team).\n"
        "Claude Code'll be able to read, edit, and execute files here.\n"
        "> 1. Yes, I trust this folder\n"
        "  2. No, exit\n"
        "Enter to confirm . Esc to cancel"
    )

    def setUp(self):
        self.sessions, _, _ = layer()

    def test_the_trust_modal_is_not_busy(self):
        self.assertFalse(self.sessions.busy(self.TRUST_MODAL),
                         "'Esc to cancel' is a modal affordance; treating it as work makes an unanswered "
                         "prompt read as a turn in flight, and the wait never ends")

    def test_the_trust_modal_IS_unsubmitted_text(self):
        self.assertIsNotNone(self.sessions.unsubmitted(self.TRUST_MODAL),
                             "the selected line sits in the input position, which is what makes this "
                             "reachable as 'waiting on a human' rather than needing a new rule")

    def test_a_working_pane_is_still_busy(self):
        self.assertTrue(self.sessions.busy("* Actioning... (1m 5s)\n  esc to interrupt"),
                        "the fix must not cost us the case busy() exists for")


class TestIsClaudeProcess(unittest.TestCase):
    """`SI-38`. Process evidence outranks screen scraping for 'is this a claude pane'."""

    def test_a_live_claude_session_is_a_claude_pane(self):
        sessions, _, _ = layer(procs=[LiveSession(42, pathlib.Path("/w"), "dt-x")])
        self.assertTrue(sessions.is_claude_process("dt-x"))

    def test_an_unrelated_session_name_is_not(self):
        sessions, _, _ = layer(procs=[LiveSession(42, pathlib.Path("/w"), "dt-x")])
        self.assertFalse(sessions.is_claude_process("dt-other"))

    def test_an_empty_name_is_not_a_claude_pane(self):
        sessions, _, _ = layer(procs=[LiveSession(42, pathlib.Path("/w"), "dt-x")])
        self.assertFalse(sessions.is_claude_process(""),
                         "an unnamed pane must never be asserted to be anything")
