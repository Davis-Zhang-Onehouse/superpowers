from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from fleet.errors import FleetError, Refused
from fleet.messaging import send
from fleet.runtime import PaneObservation


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
            self.assertEqual(result,'submitted')
            self.assertEqual(events,[('literal','hello'),('submit',None)])

    def test_a_soft_wrapped_draft_is_the_same_message(self):
        """A line wider than the input box renders as two rows and `observe` joins them with a newline;
        the words are what the operator sent, the wrap is the TUI's."""
        with tempfile.TemporaryDirectory() as directory:
            text = 'please re-run the failing suite and paste the first assertion that fails'
            wrapped = 'please re-run the failing suite and paste the first\nassertion that fails'
            layer, events = self.fixture([PaneObservation('idle'), PaneObservation('queued', wrapped),
                                          PaneObservation('busy')])
            self.assertEqual(send(Path(directory), layer, SimpleNamespace(tmux='worker'), text), 'submitted')
            self.assertEqual(events, [('literal', text), ('submit', None)])
            layer, events = self.fixture([PaneObservation('idle'), PaneObservation('queued', 'please re-run it')])
            with self.assertRaises(FleetError):
                send(Path(directory), layer, SimpleNamespace(tmux='worker'), text, timeout_s=0)

    def test_nonidle_never_types(self):
        for state in ('queued','busy','dialog','unknown'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                layer,events=self.fixture([PaneObservation(state)])
                with self.assertRaises(Refused):
                    send(Path(directory),layer,SimpleNamespace(tmux='worker'),'hello')
                self.assertEqual(events,[])

    def test_transient_redraw_is_observed_without_reinserting_or_resubmitting(self):
        with tempfile.TemporaryDirectory() as directory:
            layer, events = self.fixture([
                PaneObservation('idle'), PaneObservation('unknown'),
                PaneObservation('queued', 'hello'), PaneObservation('unknown'),
                PaneObservation('busy')])
            result = send(Path(directory), layer, SimpleNamespace(tmux='worker'), 'hello',
                          sleep=lambda _: None)
            self.assertEqual(result, 'submitted')
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
