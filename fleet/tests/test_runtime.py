"""Runtime decisions against attributed captures and hostile lookalikes."""
import json
from pathlib import Path
import unittest

from fleet.errors import BadInput
from fleet.runtime import observe, recognizes_process, validate_runtime


class RuntimeTests(unittest.TestCase):
    def test_captured_frames(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        for case in json.loads((root / 'manifest.json').read_text()):
            with self.subTest(runtime=case['runtime'], frame=case['frame']):
                actual = observe(case['runtime'], (root / case['frame']).read_text())
                self.assertEqual(actual.state, case['state'])
                if case['runtime'] == 'codex':
                    self.assertEqual(actual.watcher, '')

    def test_observed_multiline_drafts_match_the_complete_message(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        for runtime in ('claude', 'codex'):
            with self.subTest(runtime=runtime):
                actual = observe(runtime, (root / (runtime + '-multiline.frame')).read_text())
                self.assertEqual(actual.state, 'queued')
                self.assertEqual(actual.draft, 'Reply with these two words only:\nMULTILINE READY')

    def test_invalid_runtime_is_always_bad_input(self):
        for value in (None, [], {}, True, 1, '', 'gpt', 'Claude'):
            with self.subTest(value=value), self.assertRaises(BadInput):
                validate_runtime(value)

    def test_a_dialog_is_a_measured_row_not_a_quoted_hint(self):
        """A single "esc to cancel" over a joined tail classified an idle pane whose last answer merely
        quoted that hint as `dialog` — which `send`/`close` refuse and nothing clears by waiting. Every
        dialog is several fragments on ONE row, per runtime, inside the input-box window."""
        prose_then_idle = "\n".join([
            "Done. The trust screen's hint reads Esc to cancel, and Enter to confirm accepts it.",
            "",
            "❯ ",
            "? for shortcuts · auto mode on",
        ])
        self.assertEqual(observe('claude', prose_then_idle).state, 'idle')
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        self.assertEqual(observe('claude', (root / 'claude-dialog.frame').read_text()).state, 'dialog')
        self.assertEqual(observe('codex', (root / 'codex-dialog.frame').read_text()).state, 'dialog')
        ask = "\n".join(["Delete it on this lineage, or carry it?", "  1. Delete it on this lineage",
                         "  2. Keep it and carry the note", "",
                         "Enter to select · Tab/Arrow keys to navigate · Esc to cancel"])
        self.assertEqual(observe('claude', ask).state, 'dialog')
        self.assertEqual(observe('codex', (root / 'codex-trust.frame').read_text()).state, 'dialog',
                         'the directory-trust screen was measured in-tree and must stay a dialog')
        # Claude's rows are not Codex's and vice versa: a Codex pane quoting Claude's hint is not a dialog.
        self.assertNotEqual(observe('codex', ask).state, 'dialog')

    def test_blank_or_prose_is_not_idle(self):
        for runtime in ('claude', 'codex'):
            for frame in ('', '$ echo codex\n', 'The agent is idle.\n', '›\n'):
                with self.subTest(runtime=runtime, frame=frame):
                    self.assertEqual(observe(runtime, frame).state, 'unknown')

    def test_codex_input_requires_current_footer(self):
        frame = '\x1b[1m›\x1b[0m draft\n\n  gpt-6-astra default · /tmp/project\n'
        self.assertEqual(observe('codex', frame).draft, 'draft')
        self.assertEqual(observe('codex', frame + 'unfamiliar modal\n').state, 'unknown')
        # An unstyled caret in assistant prose does not establish a live input.
        self.assertEqual(observe('codex', frame.replace('\x1b[1m', '')).state, 'unknown')

    def test_codex_dim_suggestion_does_not_hide_real_input(self):
        frame = '\x1b[1m›\x1b[0m actual\x1b[2m suggestion\x1b[0m\n\n  gpt-6-astra default · /tmp/project\n'
        self.assertEqual(observe('codex', frame).draft, 'actual')

    def test_process_identity_is_not_prompt_text(self):
        self.assertTrue(recognizes_process('claude', 'claude', '/opt/claude/versions/2.1.268', ['claude']))
        self.assertTrue(recognizes_process('codex', 'codex', '/opt/vendor/bin/codex', ['codex']))
        for comm, exe, argv in (
            ('bash', '/bin/bash', ['bash', '-c', 'codex prompt']),
            ('node', '/bin/node', ['node', '/opt/codex/bin/codex.js']),
            ('sleep', '/bin/sleep', ['codex']),
            ('codex', '/bin/bash', ['codex']),
        ):
            with self.subTest(comm=comm):
                self.assertFalse(recognizes_process('codex', comm, exe, argv))


if __name__ == '__main__':
    unittest.main()
