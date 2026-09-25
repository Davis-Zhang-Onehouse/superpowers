"""Runtime decisions against attributed captures and hostile lookalikes."""
import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
import json
from pathlib import Path
import unittest

from fleet.errors import BadInput
from fleet.runtime import observe, paste_placeholder, recognizes_process, validate_runtime


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

    def test_claude_guard_reads_full_multiline_draft(self):
        from fleet.runtime import claude_unsubmitted
        frame = (Path(__file__).resolve().parents[1] / 'it/fixtures/runtime/claude-multiline.frame').read_text()
        self.assertEqual(claude_unsubmitted(frame), 'Reply with these two words only:\nMULTILINE READY')

    def test_dim_suggestions_are_marked_in_capture_and_never_drafts(self):
        from fleet.runtime import annotate_placeholders
        frames = (('claude', '❯\u00a0\x1b[2mfix RV-29 too\x1b[0m\n? for shortcuts\n'),
                  ('codex', '\x1b[1m›\x1b[0m \x1b[2mcontinue\x1b[0m\n\n  gpt-6-sol medium · /tmp/project\n'))
        for runtime, frame in frames:
            with self.subTest(runtime=runtime):
                self.assertEqual(observe(runtime, frame).draft, None)
                self.assertIn('[placeholder] ', annotate_placeholders(frame))

    def test_capture_labels_only_the_current_input_box(self):
        from fleet.runtime import annotate_placeholders
        frame = ('❯\u00a0\x1b[2mold suggestion\x1b[0m\n'
                 'finished answer\n'
                 '❯\u00a0\x1b[2mcontinue\x1b[0m\n? for shortcuts\n')
        marked = annotate_placeholders(frame)
        self.assertEqual(marked.count('[placeholder] '), 1)
        self.assertIn('[placeholder] ❯\u00a0\x1b[2mcontinue', marked)

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


    def test_paste_placeholders_are_recognised_with_their_counts(self):
        """FB-27. The shapes are MEASURED (w1sendrecords, evidence/02-rca): Claude Code 2.1.281 draws
        `[Pasted text #N +M lines]` for a paste of 4+ lines (M = newlines; no suffix without one) and codex
        0.156.1 draws `[Pasted Content C chars]` above ~1000 characters (C = characters, not bytes)."""
        claude = paste_placeholder('claude', '[Pasted text #1 +3 lines]')
        self.assertEqual(3, claude.newlines)
        self.assertTrue(claude.describes('a\nb\nc\nd'))
        self.assertTrue(claude.describes('a\nb\nc\n'), 'M counts newlines, a trailing one included')
        self.assertFalse(claude.describes('a\nb\nc'), 'two newlines is not three')
        self.assertFalse(claude.describes('a\nb\nc\n\n'), 'four newlines is not three')
        self.assertEqual(0, paste_placeholder('claude', '[Pasted text #5]').newlines)
        self.assertTrue(paste_placeholder('claude', '[Pasted text #5]').describes('x' * 1200))
        codex = paste_placeholder('codex', '[Pasted Content 1014 chars]')
        self.assertEqual(1014, codex.chars)
        self.assertTrue(codex.describes('Reply OK — ' + ('déjà·vu — ' * 100) + 'end'))
        self.assertFalse(codex.describes('x' * 1013))
        for runtime, draft in (('claude', 'Reply OK.\nsecond line'), ('claude', None), ('claude', ''),
                               ('codex', '[Pasted text #1 +3 lines]'), ('claude', '[Pasted Content 12 chars]'),
                               ('claude', 'see [Pasted text #1 +3 lines] above')):
            with self.subTest(runtime=runtime, draft=draft):
                self.assertIsNone(paste_placeholder(runtime, draft))

    def test_captured_placeholder_frames_observe_as_queued_placeholders(self):
        """The frames are real captures (`capture-pane -e`) of the probe panes; the draft the observer
        returns is what `messaging.confirms` then reads."""
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        for runtime, frame, want in (('claude', 'claude-paste-placeholder.frame', '[Pasted text #1 +3 lines]'),
                                     ('claude', 'claude-paste-placeholder-nolines.frame', '[Pasted text #5]'),
                                     ('codex', 'codex-paste-placeholder.frame', '[Pasted Content 1091 chars]')):
            with self.subTest(frame=frame):
                actual = observe(runtime, (root / frame).read_text())
                self.assertEqual(('queued', want), (actual.state, actual.draft))
                self.assertIsNotNone(paste_placeholder(runtime, actual.draft))

    def test_a_tall_inline_codex_draft_is_observed_not_unknown(self):
        """FB-27 (codex). Seven lines pasted inline put the caret above the 8-row window while the
        continuation rows fill it; the base answered `unknown` and `send` timed out on a draft it held."""
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        actual = observe('codex', (root / 'codex-tall-draft.frame').read_text())
        self.assertEqual('queued', actual.state)
        self.assertEqual('\n'.join(['Reply OK.'] + [f'line {i}' for i in range(2, 8)]), actual.draft)
        # An empty box under scrollback prose that happens to be indented stays what it was.
        prose_then_idle = "\n".join(["  some indented prose from the transcript", "  more of it", "",
                                     "\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m", "",
                                     "gpt-6-sol medium · ~/project"])
        self.assertEqual('idle', observe('codex', prose_then_idle).state)


if __name__ == '__main__':
    unittest.main()
