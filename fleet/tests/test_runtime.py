"""Runtime decisions against attributed captures and hostile lookalikes."""
import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
import json
from pathlib import Path
import unittest

from fleet.errors import BadInput
from fleet.runtime import observe, paste_placeholder, recognizes_process, validate_runtime


#: D-85: the four drafts review 2 of fix/v23-f found reading as an EMPTY box on an escape-free real capture.
LOOKALIKE_FIRST_LINES = ('Ask him first:', 'ask the reviewer to rerun RV-3', 'Try "pytest -k foo" next',
                         'new task? no, keep going')


def box_variant(box_rows, busy: bool = False) -> str:
    """`claude-multiline.frame` (real 2.1.268, escape-free) with its input box rows replaced by `box_rows`."""
    root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
    lines = (root / 'claude-multiline.frame').read_text().splitlines()
    caret = max(i for i, row in enumerate(lines) if row.startswith('\u276f'))
    frame = '\n'.join(lines[:caret] + list(box_rows) + lines[caret + 2:]) + '\n'
    if busy:
        frame = frame.replace('auto mode on (shift+tab to cycle)', 'auto mode on (shift+tab to cycle) \u00b7 esc to interrupt', 1)
    return frame


def escape_free_multiline(first: str, busy: bool = False) -> str:
    """`claude-multiline.frame` (a real 2.1.268 capture with no escape codes) with only the draft's first line
    changed; `busy` adds the live-turn hint to its status row, the way 2.1.282 draws it."""
    root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
    frame = (root / 'claude-multiline.frame').read_text()
    assert '\x1b' not in frame
    frame = frame.replace('Reply with these two words only:', first, 1)
    if busy:
        frame = frame.replace('auto mode on (shift+tab to cycle)', 'auto mode on (shift+tab to cycle) \u00b7 esc to interrupt', 1)
    return frame


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

    def test_busy_claude_tall_drafts_never_look_empty(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        original = (root / 'claude-busy.frame').read_text()
        lines = original.splitlines()
        caret = max(i for i, row in enumerate(lines) if row.startswith('❯'))
        for count in (7, 12, 30):
            for wrapped in (False, True):
                with self.subTest(count=count, wrapped=wrapped):
                    body = [f'line {i}' for i in range(count)] if not wrapped else [('word ' * 12).strip()] * count
                    frame = '\n'.join(lines[:caret] + ['❯ ' + body[0]] +
                                      ['  ' + row for row in body[1:]] + lines[caret + 1:]) + '\n'
                    actual = observe('claude', frame)
                    self.assertEqual(('busy', '\n'.join(body)), (actual.state, actual.draft))

    def test_busy_claude_without_located_caret_is_unknown(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        frame = (root / 'claude-busy.frame').read_text()
        lines = frame.splitlines()
        caret = max(i for i, row in enumerate(lines) if row.startswith('❯'))
        lines[caret] = '  editor redraw in progress'
        self.assertEqual('unknown', observe('claude', '\n'.join(lines)).state)

    def test_styled_literal_suggestion_lookalikes_are_drafts(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        for state in ('idle', 'busy'):
            original = (root / f'claude-{state}.frame').read_text()
            lines = original.splitlines()
            caret = max(i for i, row in enumerate(lines) if row.startswith('❯'))
            for draft in ('ask the reviewer to rerun RV-3', 'Try "pytest -k foo" next',
                          'Ask him first:\nthen proceed', 'new task? no, keep going'):
                with self.subTest(state=state, draft=draft):
                    body = draft.splitlines()
                    frame = '\n'.join(lines[:caret] + ['❯\u00a0\x1b[1m' + body[0] + '\x1b[0m'] +
                                      ['  ' + row for row in body[1:]] + lines[caret + 1:]) + '\n'
                    actual = observe('claude', frame)
                    self.assertEqual((state if state == 'busy' else 'queued', draft),
                                     (actual.state, actual.draft))

    def test_escape_free_real_capture_lookalike_drafts_are_drafts(self):
        """D-85. Real `capture-pane -e` frames often carry NO escape at all (claude-multiline.frame, 2.1.268;
        both 2.1.282 frames). A suggestion is SGR-dim; plain text in the box is somebody's draft, whatever it
        looks like, so a stripped capture never makes a lookalike vanish."""
        for state in ('idle', 'busy'):
            for first in LOOKALIKE_FIRST_LINES:
                with self.subTest(state=state, first=first):
                    actual = observe('claude', escape_free_multiline(first, busy=state == 'busy'))
                    self.assertEqual((state if state == 'busy' else 'queued', first + '\nMULTILINE READY'),
                                     (actual.state, actual.draft))

    def test_only_exact_measured_chrome_reads_as_an_empty_box_without_sgr(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        lines = (root / 'claude-multiline.frame').read_text().splitlines()
        caret = max(i for i, row in enumerate(lines) if row.startswith('\u276f'))
        for body, draft in (('Press up to edit queued messages', None),
                            ('press up to edit queued messages', None),
                            ('Press up to edit queued messages, then rerun', 'Press up to edit queued messages, then rerun')):
            with self.subTest(body=body):
                frame = '\n'.join(lines[:caret] + ['\u276f\u00a0' + body] + lines[caret + 2:]) + '\n'
                self.assertEqual(draft, observe('claude', frame).draft)

    def test_a_blank_caret_row_above_real_continuation_text_is_a_draft(self):
        """RV-18. A draft that starts with a newline (Shift+Enter first, or a paste beginning with one) leaves
        the caret row blank and the text on the continuation rows. It is a draft, idle or busy."""
        for busy in (False, True):
            with self.subTest(busy=busy):
                frame = box_variant(['\u276f\u00a0', '  Delete the release branch now'], busy=busy)
                actual = observe('claude', frame)
                self.assertEqual(('busy' if busy else 'queued', 'Delete the release branch now'),
                                 (actual.state, actual.draft))

    def test_an_unlocatable_box_under_a_transcript_caret_is_unknown_when_idle(self):
        """RV-19a. Idle, like busy, needs the LOCATED caret: a caret echoed in the transcript above a box whose
        caret row cannot be read is not an empty box."""
        border = '\u2500' * 40
        frame = '\n'.join(['\u276f earlier prompt', '', '\u25cf Done.', '', border,
                            '\u00b7 unrecognised box row', border, '  \u23f5\u23f5 auto mode on']) + '\n'
        self.assertEqual('unknown', observe('claude', frame).state)

    def test_the_draft_runs_to_the_located_border_not_to_any_rule_character(self):
        """RV-20. Inside a bordered box every row down to the bottom border is the draft: a markdown rule or a
        table row with a box-drawing character does not end it, and chrome followed by text is not chrome."""
        cases = ((['\u276f\u00a0Press up to edit queued messages', '  \u2500\u2500\u2500\u2500', '  real text'],
                  'Press up to edit queued messages\n\u2500\u2500\u2500\u2500\nreal text'),
                 (['\u276f\u00a0compare a \u2500 b', '  | x \u2502 y |', '  done'],
                  'compare a \u2500 b\n| x \u2502 y |\ndone'))
        for busy in (False, True):
            for rows, draft in cases:
                with self.subTest(busy=busy, draft=draft):
                    actual = observe('claude', box_variant(rows, busy=busy))
                    self.assertEqual(('busy' if busy else 'queued', draft), (actual.state, actual.draft))

    def test_capture_label_agrees_with_the_guard_on_chrome_followed_by_text(self):
        """RV-22. The [placeholder] label is decided on the whole box, like the guard."""
        from fleet.runtime import annotate_placeholders
        frame = box_variant(['\u276f\u00a0Press up to edit queued messages', '  more text'])
        self.assertTrue(observe('claude', frame).draft)
        self.assertNotIn('[placeholder]', annotate_placeholders(frame))
        chrome_only = box_variant(['\u276f\u00a0Press up to edit queued messages'])
        self.assertIn('[placeholder] ', annotate_placeholders(chrome_only))

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

    def test_capture_labels_measured_chrome_but_not_plain_lookalikes(self):
        """D-85: without SGR only measured whole-box chrome is labelled; a plain lookalike is a draft."""
        from fleet.runtime import annotate_placeholders
        legacy = '❯ try "fix the failing test"\n? for shortcuts\n'
        self.assertNotIn('[placeholder]', annotate_placeholders(legacy))
        self.assertEqual(observe('claude', legacy).draft, 'try "fix the failing test"')
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        queued = (root / 'claude-queued-behind-turn-282.frame').read_text()
        self.assertIn('[placeholder] ❯\u00a0Press up to edit queued messages', annotate_placeholders(queued))
        styled = '❯\x1b[1mTry "pytest -k foo" next\x1b[0m\n? for shortcuts\n'
        self.assertNotIn('[placeholder]', annotate_placeholders(styled))
        self.assertEqual(observe('claude', styled).draft, 'Try "pytest -k foo" next')

    def test_real_claude_282_busy_empty_box_then_queued_message_display(self):
        root = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        after_enter = (root / 'claude-after-busy-enter-282.frame').read_text()
        queued = (root / 'claude-queued-behind-turn-282.frame').read_text()
        self.assertEqual('busy', observe('claude', after_enter).state)
        self.assertFalse(observe('claude', after_enter).draft)
        self.assertIn('After this turn, reply with exactly QUEUED PROBE.', queued)
        self.assertIn('ctrl+x ctrl+s to send now', queued)
        self.assertEqual('busy', observe('claude', queued).state)
        self.assertFalse(observe('claude', queued).draft)

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
        # Codex's caret walk is already unbounded by the eight-row tail. Keep
        # that property explicit beside the new Claude safety regression.
        captured = (root / 'codex-tall-draft.frame').read_text()
        for count in (12, 30):
            with self.subTest(count=count):
                extended = captured.replace('  line 7\n', '  line 7\n' +
                    ''.join(f'  line {i}\n' for i in range(8, count + 1)))
                observed = observe('codex', extended)
                self.assertEqual('queued', observed.state)
                self.assertIn(f'line {count}', observed.draft)
        # An empty box under scrollback prose that happens to be indented stays what it was.
        prose_then_idle = "\n".join(["  some indented prose from the transcript", "  more of it", "",
                                     "\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m", "",
                                     "gpt-6-sol medium · ~/project"])
        self.assertEqual('idle', observe('codex', prose_then_idle).state)


if __name__ == '__main__':
    unittest.main()
