import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace

from fleet.errors import BadInput, FleetError, Refused
from fleet.messaging import (CONFIRMED_BY_DRAFT, CONFIRMED_BY_PLACEHOLDER, CONFIRMED_BY_PLACEHOLDER_UNCOUNTED, SUBMITTED, confirms, UNCERTAIN_AFTER_ENTER, line_count,
                             UNCERTAIN_AFTER_INSERTION, SendRecord, read_sends, record_send, send, sends_path)
from fleet.runtime import PaneObservation, observe


class MessagingTests(unittest.TestCase):
    def fixture(self, states):
        states = iter(states)
        events = []
        layer = SimpleNamespace(socket='test', observe=lambda name: next(states),
                                send_literal=lambda name,text: events.append(('literal',text)),
                                submit=lambda name: events.append(('submit',None)))
        return layer, events

    def test_only_matching_draft_is_submitted_once(self):
        with tempfile.TemporaryDirectory() as directory:
            layer, events = self.fixture([PaneObservation('idle'), PaneObservation('queued','hello'), PaneObservation('busy')])
            result=send(Path(directory),layer,SimpleNamespace(tmux='worker'),'hello')
            self.assertEqual(result,(SUBMITTED, CONFIRMED_BY_DRAFT))
            self.assertEqual(events,[('literal','hello'),('submit',None)])

    def test_a_soft_wrapped_draft_is_the_same_message(self):
        """A line wider than the input box renders as two rows and `observe` joins them with a newline;
        the words are what the operator sent, the wrap is the TUI's."""
        with tempfile.TemporaryDirectory() as directory:
            text = 'please re-run the failing suite and paste the first assertion that fails'
            wrapped = 'please re-run the failing suite and paste the first\nassertion that fails'
            layer, events = self.fixture([PaneObservation('idle'), PaneObservation('queued', wrapped),
                                          PaneObservation('busy')])
            self.assertEqual(send(Path(directory), layer, SimpleNamespace(tmux='worker'), text), (SUBMITTED, CONFIRMED_BY_DRAFT))
            self.assertEqual(events, [('literal', text), ('submit', None)])
            layer, events = self.fixture([PaneObservation('idle'), PaneObservation('queued', 'please re-run it')])
            with self.assertRaises(FleetError):
                send(Path(directory), layer, SimpleNamespace(tmux='worker'), text, timeout_s=0)

    def test_nonidle_never_types(self):
        for state in ('queued','dialog','unknown'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                layer,events=self.fixture([PaneObservation(state)])
                with self.assertRaises(Refused):
                    send(Path(directory),layer,SimpleNamespace(tmux='worker'),'hello')
                self.assertEqual(events,[])

    def test_empty_busy_pane_queues_on_both_runtimes(self):
        for runtime in ('claude', 'codex'):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as directory:
                layer, events = self.runtime_fixture(runtime, [PaneObservation('busy'),
                    PaneObservation('busy', 'hello'), PaneObservation('busy')])
                self.assertEqual(send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello'),
                                 ('queued-behind-turn', CONFIRMED_BY_DRAFT))
                self.assertEqual(events, [('literal', 'hello'), ('submit', None)])

    def test_busy_pane_with_draft_or_dialog_never_types(self):
        for runtime in ('claude', 'codex'):
            for state, draft in (('busy', 'someone else'), ('queued', 'someone else'),
                                 ('unknown', None), ('dialog', None)):
                with self.subTest(runtime=runtime, state=state), tempfile.TemporaryDirectory() as directory:
                    layer, events = self.runtime_fixture(runtime, [PaneObservation(state, draft)])
                    with self.assertRaises(Refused):
                        send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello')
                    self.assertEqual(events, [])

    def test_real_frames_gate_busy_and_protect_drafts_and_dialogs(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        cases = [('claude', 'claude-busy.frame', True),
                 ('codex', 'codex-busy-bgterm-0156.frame', True),
                 ('claude', 'claude-queued.frame', False),
                 ('codex', 'codex-queued.frame', False),
                 ('claude', 'claude-dialog.frame', False),
                 ('codex', 'codex-approval-0156.frame', False)]
        for runtime, filename, admitted in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                before = observe(runtime, (root / filename).read_text())
                layer, events = self.runtime_fixture(runtime, [before] +
                    ([PaneObservation('busy', 'hello'), PaneObservation('busy')] if admitted else []))
                if admitted:
                    self.assertEqual(send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello')[0],
                                     'queued-behind-turn')
                    self.assertEqual(events, [('literal', 'hello'), ('submit', None)])
                else:
                    with self.assertRaises(Refused):
                        send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello')
                    self.assertEqual(events, [])

    def test_visible_draft_after_enter_gets_one_retry_then_distinct_failure(self):
        for runtime, draft in (('claude', '[Pasted text #1 +3 lines]'),
                               ('codex', '[Pasted Content 9 chars]'), ('claude', 'hello')):
            text = 'a\nb\nc\nd' if runtime == 'claude' and draft.startswith('[') else 'x' * 9 if runtime == 'codex' else 'hello'
            with self.subTest(runtime=runtime, draft=draft), tempfile.TemporaryDirectory() as directory:
                layer, events = self.runtime_fixture(runtime, [PaneObservation('idle'),
                    PaneObservation('queued', draft), PaneObservation('queued', draft),
                    PaneObservation('queued', draft)])
                recorded = []
                with self.assertRaisesRegex(FleetError, 'inserted-not-submitted'):
                    send(Path(directory), layer, SimpleNamespace(tmux='worker'), text, timeout_s=0,
                         recorder=lambda outcome, confirmation: recorded.append(outcome))
                self.assertEqual(events, [('literal', text), ('submit', None), ('submit', None)])
                self.assertEqual(recorded, ['inserted-not-submitted'])

    def test_transient_redraw_is_observed_without_reinserting_or_resubmitting(self):
        with tempfile.TemporaryDirectory() as directory:
            layer, events = self.fixture([
                PaneObservation('idle'), PaneObservation('unknown'),
                PaneObservation('queued', 'hello'), PaneObservation('unknown'),
                PaneObservation('busy')])
            result = send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello',
                          sleep=lambda _: None)
            self.assertEqual(result, (SUBMITTED, CONFIRMED_BY_DRAFT))
            self.assertEqual(events, [('literal', 'hello'), ('submit', None)])

    def test_competing_draft_and_failed_capture_never_retry(self):
        for after in (PaneObservation('queued','someone else'),PaneObservation('unknown')):
            with tempfile.TemporaryDirectory() as directory:
                layer,events=self.fixture([PaneObservation('idle'),after])
                with self.assertRaises(FleetError):
                    send(Path(directory),layer,SimpleNamespace(tmux='worker'),'hello',timeout_s=0)
                self.assertEqual(events,[('literal','hello')])

    def test_failed_observation_after_submit_is_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            layer,events=self.fixture([PaneObservation('idle'),PaneObservation('queued','hello'),PaneObservation('unknown')])
            with self.assertRaisesRegex(FleetError,'uncertain'):
                send(Path(directory),layer,SimpleNamespace(tmux='worker'),'hello',timeout_s=0)
            self.assertEqual(events,[('literal','hello'),('submit',None)])

    def test_control_characters_are_refused_before_typing(self):
        with tempfile.TemporaryDirectory() as directory:
            layer,events=self.fixture([])
            for text in ('', '\x1b[A', 'x\ry', '\x7f', '\x00'):
                with self.assertRaises(FleetError):
                    send(Path(directory),layer,SimpleNamespace(tmux='worker'),text)
            self.assertEqual(events,[])

    # ---- FB-27: a paste the TUI shows as a placeholder ----------------------------------------------

    def runtime_fixture(self, runtime, states):
        layer, events = self.fixture(states)
        layer.runtime = runtime
        return layer, events

    def test_a_multiline_message_confirmed_by_the_paste_placeholder_is_submitted(self):
        """Measured on Claude Code 2.1.281: a paste of 4+ lines renders as `[Pasted text #N +M lines]`
        (M = newlines) and codex 0.156.1 shows `[Pasted Content C chars]` above ~1000 characters. Before
        the fix `send` waited for the draft to equal the text, timed out, and left the paste unsubmitted
        (FB-27, every multi-line coordinator send)."""
        text = 'Reply OK.\nsecond line\nthird line\nfourth line\nfifth line'
        for runtime, placeholder in (('claude', '[Pasted text #3 +4 lines]'),
                                     ('codex', f'[Pasted Content {len(text)} chars]')):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as directory:
                layer, events = self.runtime_fixture(runtime, [
                    PaneObservation('idle'), PaneObservation('queued', placeholder), PaneObservation('busy')])
                outcome, confirmation = send(Path(directory), layer, SimpleNamespace(tmux='worker'), text,
                                             sleep=lambda _: None)
                self.assertEqual((SUBMITTED, CONFIRMED_BY_PLACEHOLDER), (outcome, confirmation))
                self.assertEqual(events, [('literal', text), ('submit', None)])

    def test_the_exact_draft_is_still_the_strong_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            layer, events = self.runtime_fixture('claude', [
                PaneObservation('idle'), PaneObservation('queued', 'hello'), PaneObservation('busy')])
            self.assertEqual((SUBMITTED, CONFIRMED_BY_DRAFT),
                             send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello'))

    def test_a_placeholder_whose_counts_disagree_is_never_submitted(self):
        """Somebody else's paste, or ours concatenated onto a draft: the counts are not the message's, so
        Enter is never sent and the send is uncertain — the FB-27 fix must not become a blind submit."""
        text = 'Reply OK.\nsecond line\nthird line\nfourth line\nfifth line'
        for runtime, placeholder in (('claude', '[Pasted text #1 +9 lines]'),
                                     ('claude', '[Pasted text #1]'),
                                     ('codex', '[Pasted Content 9999 chars]'),
                                     ('codex', '[Pasted text #1 +4 lines]'),      # the other TUI's shape
                                     ('claude', '[Pasted Content 55 chars]')):
            with self.subTest(runtime=runtime, placeholder=placeholder), tempfile.TemporaryDirectory() as directory:
                layer, events = self.runtime_fixture(runtime, [PaneObservation('idle'),
                                                               PaneObservation('queued', placeholder)])
                with self.assertRaisesRegex(FleetError, 'uncertain after insertion'):
                    send(Path(directory), layer, SimpleNamespace(tmux='worker'), text, timeout_s=0)
                self.assertEqual(events, [('literal', text)])

    def test_a_placeholder_already_in_the_box_refuses_before_typing(self):
        """The guarded-messaging rule survives: a box holding somebody's unsubmitted paste is a draft."""
        with tempfile.TemporaryDirectory() as directory:
            layer, events = self.runtime_fixture('claude', [PaneObservation('queued', '[Pasted text #1 +4 lines]')])
            with self.assertRaises(Refused):
                send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'a\nb\nc\nd\ne')
            self.assertEqual(events, [])

    # ---- B13: every attempt that reached the pane is recorded --------------------------------------

    def test_every_attempt_that_touched_the_pane_reaches_the_recorder_once(self):
        cases = [
            ('submitted', [PaneObservation('idle'), PaneObservation('queued', 'hello'), PaneObservation('busy')],
             (SUBMITTED, CONFIRMED_BY_DRAFT)),
            ('uncertain after insertion', [PaneObservation('idle'), PaneObservation('queued', 'other')],
             (UNCERTAIN_AFTER_INSERTION, '')),
            ('uncertain after Enter', [PaneObservation('idle'), PaneObservation('queued', 'hello'),
                                       PaneObservation('unknown')],
             (UNCERTAIN_AFTER_ENTER, CONFIRMED_BY_DRAFT)),
        ]
        for label, states, want in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                layer, _ = self.runtime_fixture('claude', states)
                recorded = []
                try:
                    send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello', timeout_s=0,
                         recorder=lambda outcome, confirmation: recorded.append((outcome, confirmation)))
                except FleetError:
                    pass
                self.assertEqual([want], recorded)

    def test_a_refusal_before_the_paste_records_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            layer, _ = self.runtime_fixture('claude', [PaneObservation('busy', 'someone else')])
            recorded = []
            with self.assertRaises(Refused):
                send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello',
                     recorder=lambda *args: recorded.append(args))
            self.assertEqual([], recorded)

    def test_send_records_round_trip_and_a_malformed_log_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            instant = Path(directory) / 'inst'
            self.assertEqual([], read_sends(instant))
            first = SendRecord(at='2026-09-24T00:00:00Z', by='coord', todo_id='w-1', tmux='dt-w', runtime='claude',
                               message_file='/tmp/m.txt', sha256='ab' * 32, chars=5, lines=1, head='hello',
                               outcome=SUBMITTED, confirmation=CONFIRMED_BY_DRAFT)
            second = SendRecord(**{**first.__dict__, 'outcome': UNCERTAIN_AFTER_INSERTION, 'confirmation': ''})
            record_send(instant, first)
            record_send(instant, second)
            self.assertEqual([first, second], read_sends(instant))
            with sends_path(instant).open('a') as handle:
                handle.write('{ not json\n')
            with self.assertRaises(BadInput):
                read_sends(instant)

    def test_a_raising_recorder_never_changes_the_delivery_verdict(self):
        """RV-38. The recorder ran unguarded in `finally`: an OSError from the send log replaced a
        SUBMITTED verdict with a raw traceback — the operator reads a failure for a delivered message and
        retries, which is the duplicate send FI-9/FI-15 exist to prevent — and on the uncertain paths it
        replaced the 'inspect before retrying' FleetError. The delivery verdict always wins; the recording
        failure is reported through `unrecorded`, never raised over the verdict."""
        def boom(outcome, confirmation):
            raise PermissionError('sends.jsonl is read-only')
        with tempfile.TemporaryDirectory() as directory:
            layer, events = self.runtime_fixture('claude', [
                PaneObservation('idle'), PaneObservation('queued', 'hello'), PaneObservation('busy')])
            reported = []
            self.assertEqual((SUBMITTED, CONFIRMED_BY_DRAFT),
                             send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello',
                                  recorder=boom, unrecorded=reported.append))
            self.assertEqual(events, [('literal', 'hello'), ('submit', None)])
            self.assertEqual(1, len(reported))
            self.assertIsInstance(reported[0], PermissionError)
        with tempfile.TemporaryDirectory() as directory:
            layer, _ = self.runtime_fixture('claude', [PaneObservation('idle'), PaneObservation('queued', 'other')])
            reported = []
            with self.assertRaisesRegex(FleetError, 'uncertain after insertion'):
                send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello', timeout_s=0,
                     recorder=boom, unrecorded=reported.append)
            self.assertEqual(1, len(reported))
        #: With no `unrecorded` hook the failure is not swallowed silently: it is raised — but only AFTER a
        #: verdict that was NOT a success, never over a submitted one.
        with tempfile.TemporaryDirectory() as directory:
            layer, _ = self.runtime_fixture('claude', [
                PaneObservation('idle'), PaneObservation('queued', 'hello'), PaneObservation('busy')])
            with self.assertRaisesRegex(FleetError, 'submitted.*NOT recorded'):
                send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello', recorder=boom)

    def test_read_sends_refuses_bad_bytes_and_wrong_field_types_as_bad_input(self):
        """RV-39 (an FB-74 member). `read_text` sat outside the per-line try, so a torn multibyte append
        raised UnicodeDecodeError past `brief`'s `except BadInput`; and a line with the right keys but
        `"sha256": 5` was returned and crashed `brief` at `sha256[:8]`."""
        with tempfile.TemporaryDirectory() as directory:
            instant = Path(directory) / 'inst'
            good = SendRecord(at='2026-09-24T00:00:00Z', by='coord', todo_id='w-1', tmux='dt-w', runtime='claude',
                              message_file='/tmp/m.txt', sha256='ab' * 32, chars=5, lines=1, head='hello…',
                              outcome=SUBMITTED, confirmation=CONFIRMED_BY_DRAFT)
            record_send(instant, good)
            with sends_path(instant).open('ab') as handle:
                handle.write(b'{"torn": "\xe2\x80')          # a multibyte sequence cut mid-append
            with self.assertRaises(BadInput):
                read_sends(instant)
            sends_path(instant).unlink()
            record_send(instant, good)
            wrong = dict(good.__dict__, sha256=5)
            with sends_path(instant).open('a') as handle:
                handle.write(json.dumps(wrong) + '\n')
            with self.assertRaises(BadInput):
                read_sends(instant)
            #: An unreadable log (a directory in its place) is refused the same way, never an OSError.
            sends_path(instant).unlink()
            sends_path(instant).mkdir()
            with self.assertRaises(BadInput):
                read_sends(instant)

    def test_line_count_is_newline_separated_lines_only(self):
        """RV-46. `str.splitlines` also splits on CR, VT, FF and U+2028, so `lines` could disagree with the
        newline count the TUI's placeholder states; the record counts what the confirmation counts."""
        self.assertEqual(1, line_count('a\x0cb c'))
        self.assertEqual(2, line_count('a\r\nb'))
        self.assertEqual(3, line_count('a\nb\nc'))
        self.assertEqual(3, line_count('a\nb\nc\n'))
        self.assertEqual(0, line_count(''))

    def test_a_single_line_claude_placeholder_is_recorded_as_uncounted(self):
        """RV-47. `[Pasted text #N]` states no length: it confirms only that a paste with no newline sits
        in the box, which any single-line message of 800+ characters would also produce. It is accepted
        (the box was observed empty before this paste) but the record must say how weak that is."""
        text = 'x' * 900
        with tempfile.TemporaryDirectory() as directory:
            layer, events = self.runtime_fixture('claude', [
                PaneObservation('idle'), PaneObservation('queued', '[Pasted text #4]'), PaneObservation('busy')])
            self.assertEqual((SUBMITTED, CONFIRMED_BY_PLACEHOLDER_UNCOUNTED),
                             send(Path(directory), layer, SimpleNamespace(tmux='worker'), text, sleep=lambda _: None))
            self.assertEqual(events, [('literal', text), ('submit', None)])
        # codex's placeholder always states the length, so it is never uncounted
        self.assertEqual(CONFIRMED_BY_PLACEHOLDER, confirms('codex', f'[Pasted Content {len(text)} chars]', text))
        # a claude placeholder WITH a line count is the counted kind
        self.assertEqual(CONFIRMED_BY_PLACEHOLDER, confirms('claude', '[Pasted text #1 +2 lines]', 'a\nb\nc'))
