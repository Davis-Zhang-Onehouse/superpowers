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


# --- FI-208: the DIM ghost suggestion is not typed text -------------------------------------------
#
# EVERY constant below is a byte sequence a REAL Claude Code pane emitted, captured with
# `tmux capture-pane -p -e` on 2026-08-08 and archived in the `i7` instant's `evidence/01-red/`. None of
# them is authored. That distinction is the point of these cases: the defect they cover survived because
# the one bit that mattered was an ATTRIBUTE nobody had looked at, and a fixture invented at a desk
# reproduces the author's idea of a pane rather than a pane.
#
# Three DIFFERENT caret-line shapes appear here because three different shapes were measured, and a fix
# that handled one would have been flaky against the others:
#   * `\x1b[39m❯\xa0…`  — attribute BEFORE the caret        (`dt-w22…`, 01:57Z)
#   * `❯\xa0\x1b[39m`   — attribute AFTER the caret          (`dt-i7…`, own pane, 02:05Z)
#   * `❯\xa0\x1b[2m…`   — attribute opening the BODY         (the ghost, re-rendered through real tmux)

#: `dt-w22RetainedTestsNeedRestructuring`, the pane FI-208 was measured on. The box is EMPTY and the
#: suggestion is drawn in SGR 2. Recorded in the coordinator's `ISSUES.md` at 01:40Z and reproduced
#: byte-for-byte through a real tmux round-trip at 02:00Z (`evidence/01-red/07-…`).
LIVE_GHOST_BOX = "\x1b[39m❯ \x1b[2mkeep watching and triage anything red\x1b[0m\x1b[39m\x1b[49m"
#: The SAME pane fifteen minutes later, box still empty, ghost not currently drawn. The caret is preceded
#: by an attribute here too — which is what makes it the false-safe control below.
LIVE_EMPTY_BOX = "\x1b[39m❯ "
#: A second live pane's empty box, with the attribute on the OTHER side of the caret.
LIVE_EMPTY_BOX_TRAILING_SGR = "❯ \x1b[39m"
#: An auditor's control probe: genuinely TYPED text renders at normal intensity, no SGR 2 anywhere.
LIVE_TYPED_BOX = "\x1b[39m❯ REAL-TYPED-TEXT-GAMMA"
#: A live idle Claude Code footer. Note `auto mode on` and `(shift+tab to cycle)` are ONE phrase split by
#: a colour change — measured, not hypothetical, and the reason marker matching runs on `plain`.
LIVE_FOOTER = ("\x1b[39m  \x1b[93m⏵⏵ auto mode on\x1b[37m (shift+tab to cycle) · "
               "← for agents\x1b[39m")
LIVE_BUSY_FOOTER = ("\x1b[39m  \x1b[93m⏵⏵ auto mode on\x1b[37m (shift+tab to cycle) · "
                    "esc to interrupt · ← for agents\x1b[39m")
#: tmux pads a capture to the pane height, and with `-e` a padding row is not the empty string.
LIVE_STYLED_BLANK = "\x1b[39m\x1b[49m"


def pane(*rows) -> str:
    """A capture: the rows, then the styled-blank padding a real `-e` capture carries."""
    return "\n".join(list(rows) + [LIVE_STYLED_BLANK] * 6)


class TestTheDimGhostIsNotTypedText(unittest.TestCase):
    """`FI-208`, and BOTH directions of it, which is the whole requirement.

    Claude Code draws a model-generated suggestion into an EMPTY input box in SGR 2 (DIM). Captured
    without `-e` that attribute is gone, so the suggestion is indistinguishable from a message a human
    typed and never sent. `pane-guard` answered `10 queued-text` for every idle worker in a live effort
    for ten and a half hours, and `close` refused to close a finished one naming a remedy — *submit or
    clear the text* — that could not be performed, because there was no text.

    **The opposite direction is tested just as hard, and deliberately so.** Making the ghost read as empty
    is easy; doing it in a way that ALSO stops real queued text being seen is a worse defect than the one
    being fixed, because a `send-keys` then concatenates onto a draft nobody knew was there. That is
    `FI-180`'s rule — when a fix makes a failure stop being visible, it is not done until the visibility
    is replaced — so every case here has a twin.
    """

    def setUp(self):
        self.sessions, _, _ = layer()

    # --- direction 1: the ghost must read as an EMPTY box -----------------------------------------

    def test_the_live_ghost_suggestion_is_not_unsubmitted_text(self):
        self.assertIsNone(self.sessions.unsubmitted(pane("output", LIVE_GHOST_BOX, LIVE_FOOTER)),
                          "the DIM body is Claude Code's own suggestion in an EMPTY box. Reporting it as "
                          "queued text is FI-208: an alarm with no subject, and a close refusal whose "
                          "stated remedy nobody can perform")

    def test_the_ghost_is_classified_by_ATTRIBUTE_and_not_by_matching_its_TEXT(self):
        """`AC-6`. The suggestion is model-generated prose, so a denylist of texts can never be finished.

        Same DIM wrapper, arbitrary body — if this only passed for the one string that was measured, the
        fix would be a denylist with one entry and the next suggestion would re-open the defect.
        """
        for body in ("run the tests again", "ask me anything", "⌘ summarise the last hour",
                     "keep watching and triage anything red"):
            ghost = f"\x1b[39m❯ \x1b[2m{body}\x1b[0m\x1b[39m\x1b[49m"
            self.assertIsNone(self.sessions.unsubmitted(pane("output", ghost, LIVE_FOOTER)),
                              f"a DIM body must be a placeholder whatever it says: {body!r}")

    # --- direction 2: REAL typed text must still be seen ------------------------------------------

    def test_genuinely_typed_text_is_still_reported_as_queued(self):
        """The `FI-169` control. `send-keys` DOES concatenate onto an existing draft — proven by
        execution on a private socket, one user turn with no separator — so this guard is correct and the
        FI-208 fix must not weaken it."""
        self.assertEqual(self.sessions.unsubmitted(pane("output", LIVE_TYPED_BOX, LIVE_FOOTER)),
                         "REAL-TYPED-TEXT-GAMMA")

    def test_an_attribute_before_the_caret_does_not_HIDE_a_box_holding_real_text(self):
        """THE false-safe this fix could most easily have introduced, and it is not hypothetical: adding
        `-e` to the capture and stopping there was measured returning None for exactly this line, because
        `line.strip()[0]` is then `ESC` rather than the caret. Every pane with a styled caret — which is
        every live pane measured — would have reported an empty box while holding a real draft, and
        `pane-guard` would have said `0 safe`."""
        self.assertEqual(self.sessions.unsubmitted(pane("output", LIVE_TYPED_BOX, LIVE_FOOTER)),
                         "REAL-TYPED-TEXT-GAMMA",
                         "the caret is preceded by an SGR escape on every live pane measured; a predicate "
                         "that cannot find it reports every box as empty")

    def test_a_dim_HINT_beside_typed_text_does_not_swallow_the_typed_text(self):
        """Partially-dim bodies are the case that separates *drop the dim cells* from *any dim means
        placeholder*. The lazy rule would classify this whole box as empty and lose a real draft."""
        mixed = "\x1b[39m❯ ship it\x1b[2m  (press enter)\x1b[0m"
        self.assertEqual(self.sessions.unsubmitted(pane("output", mixed, LIVE_FOOTER)), "ship it")

    # --- the box shapes that are genuinely empty --------------------------------------------------

    def test_both_live_forms_of_an_EMPTY_box_read_as_empty(self):
        for label, row in (("attribute before the caret", LIVE_EMPTY_BOX),
                           ("attribute after the caret", LIVE_EMPTY_BOX_TRAILING_SGR)):
            self.assertIsNone(self.sessions.unsubmitted(pane("output", row, LIVE_FOOTER)),
                              f"an empty box must read empty: {label}")

    def test_the_five_legacy_placeholder_shapes_still_answer_for_a_terminal_that_STRIPS_attributes(self):
        """`AC-6`: attribute-absence is the primary signal and these remain the fallback. A terminal or a
        tmux that yields no SGR leaves the old shapes as the only evidence available, and deleting them
        would trade one blind spot for another."""
        for placeholder in ('❯ Try "fix the bug"', "❯ / for commands", "❯ # for memory",
                            "❯ new task?", "❯ ask about this repo"):
            self.assertIsNone(self.sessions.unsubmitted(pane("output", placeholder, "footer")),
                              f"the legacy fallback must still hold for {placeholder!r}")


class TestTheCaptureKeepsWhatTheseCasesDependOn(unittest.TestCase):
    """The attribute has to SURVIVE the probe, or every case above is asserting on a string the product
    never sees. `FI-208` is precisely that gap: the predicates were fine, the capture threw the input
    away, and the suite could not tell because it fed the predicates by hand."""

    def test_the_capture_argv_asks_tmux_for_escape_sequences(self):
        captured = []
        probes = default_probes(tmux_socket="itfleet-selftest-argv")
        import fleet.session as session_mod
        real_run = subprocess.run
        try:
            def spy(argv, *a, **kw):
                captured.append(argv)
                return subprocess.CompletedProcess(argv, 1, "", "")
            subprocess.run = spy
            probes.capture_pane("itfleet-nothing")
        finally:
            subprocess.run = real_run
        argv = [a for a in captured if "capture-pane" in a]
        self.assertTrue(argv, "no capture-pane argv was built at all")
        self.assertIn("-e", argv[0],
                      "the capture must ask tmux for the SGR attributes (FI-208). Without -e the DIM "
                      "ghost suggestion and text a human typed are the SAME STRING, and every consumer "
                      "above this line is deciding on a value the distinguishing bit was removed from")

    def test_styled_blank_padding_does_not_push_the_window_off_the_content(self):
        """`FI-24`, re-opened by the attributes. tmux pads a capture to the pane height; with `-e` those
        padding rows carry escapes, so a blank-check on the raw row stops trimming at the padding and
        anchors the tail window BELOW the content — a box with real text then falls outside its own
        window and reads safe."""
        sessions, _, _ = layer()
        deep = pane(*(["scrollback"] * 20 + [LIVE_TYPED_BOX, LIVE_FOOTER]))
        self.assertEqual(sessions.unsubmitted(deep), "REAL-TYPED-TEXT-GAMMA")

    def test_busy_survives_a_footer_whose_phrase_is_split_by_a_colour_change(self):
        """Marker matching runs on the visible characters. `auto mode on (shift+tab to cycle)` is ONE
        phrase interrupted by `\\x1b[37m` in the live capture — measured — so a raw substring match is one
        styling change away from reporting a mid-turn pane as idle."""
        sessions, _, _ = layer()
        self.assertTrue(sessions.busy(pane("working", LIVE_BUSY_FOOTER)))
        self.assertFalse(sessions.busy(pane("done", LIVE_FOOTER)))
        from fleet.session import plain as _plain
        self.assertNotIn("auto mode on (shift+tab to cycle)", LIVE_FOOTER,
                         "if the raw footer already contains the whole phrase this case proves nothing")
        self.assertIn("auto mode on (shift+tab to cycle)", _plain(LIVE_FOOTER))


class TestExtendedColourIsNotDim(unittest.TestCase):
    """`OI-1` — the false-safe the FI-208 fix introduced and a review caught before it shipped.

    `\\x1b[38;2;136;192;208m` is truecolor foreground. Read parameter-by-parameter it **contains a `2`**,
    and the first version of `_cells` scored that as SGR 2 = DIM. Measured consequence: a truecolor-styled
    input box made REAL TYPED TEXT VANISH — `_caret_content` returned `''`, `unsubmitted` returned None,
    `pane-guard` said `0 safe`, and a `send-keys` would concatenate onto somebody's live draft.

    That is the exact failure `AC-5` forbids and `FI-169` exists to prevent, reintroduced by the fix for
    `FI-208` — a fix trading one blind spot for a worse one, one layer down. It was latent rather than
    live (neither archived live capture contains `38;2`), which is precisely why it needed a control
    rather than a note: nothing in the fleet would have shown it until the day a TUI restyled its box.
    """

    def setUp(self):
        self.sessions, _, _ = layer()

    def test_a_truecolor_or_256_colour_body_is_TYPED_TEXT_not_a_placeholder(self):
        for label, sequence in (
                ("truecolor foreground", "\x1b[38;2;136;192;208m"),
                ("truecolor background", "\x1b[48;2;1;2;3m"),
                ("256-colour index 2 — the one that looks most like SGR 2", "\x1b[38;5;2m"),
                ("256-colour index 99", "\x1b[38;5;99m"),
                ("underline colour", "\x1b[58;2;1;2;3m")):
            row = f"\x1b[39m{CARET}{NBSP}{sequence}REAL-TYPED-TEXT-GAMMA"
            self.assertEqual(self.sessions.unsubmitted(pane("output", row, LIVE_FOOTER)),
                             "REAL-TYPED-TEXT-GAMMA",
                             f"{label}: an extended-colour introducer swallows its own arguments. Scoring "
                             f"one of them as SGR 2 makes a styled box read EMPTY while it holds a real "
                             f"draft, and a send then concatenates onto it")

    def test_real_DIM_still_wins_when_it_follows_an_extended_colour(self):
        """The twin. Skipping colour arguments must not also skip a genuine SGR 2 after them."""
        row = f"\x1b[38;2;1;2;3m{CARET}{NBSP}\x1b[2mkeep watching and triage anything red\x1b[0m"
        self.assertIsNone(self.sessions.unsubmitted(pane("output", row, LIVE_FOOTER)))

    def test_a_malformed_introducer_consumes_only_itself(self):
        """`\\x1b[38m` with no selector must not eat the rest of the sequence — a malformed escape that
        swallowed everything after it would be a second way to lose a draft."""
        row = f"\x1b[39m{CARET}{NBSP}\x1b[38mtyped after a malformed introducer"
        self.assertEqual(self.sessions.unsubmitted(pane("output", row, LIVE_FOOTER)),
                         "typed after a malformed introducer")
