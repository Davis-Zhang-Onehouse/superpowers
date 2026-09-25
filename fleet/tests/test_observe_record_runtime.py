"""v23-k (FB-113): each pane is observed as the runtime of the agent that OWNS it, judged with its RECORD's layer.

Measured on the first codex worker (`v23ainstantpath`, fleet 0.6.10): `fleet board` flapped the record to BLOCKED
"live runtime claude differs from record runtime codex" for the 76 s its hermetic suite ran, and `pane-guard --id`
read `0 safe` for a codex pane drawing "• Working (… • esc to interrupt) · 1 background terminal running · …".

Two causes, both pinned here:

1. The inventory attributed EVERY recognised claude/codex process under a pane to that pane, and the runtime checks
   asked "is any of them another runtime". The suite (and `fleet peers`) runs the REAL `claude agents --json`, so a
   codex worker's pane briefly held a genuine claude process — its CHILD, not its agent. A row is now `nested` when an
   ancestor below the pane root is itself an inventoried agent, and runtime identity is read from the outer rows.
2. codex 0.156's busy row was matched only as a bare `• Working (… esc to interrupt)` directly above the caret. The
   live row carries a ` · 1 background terminal running · …` tail, and a `└ <command>` row can sit under it.

The inventory is built by the REAL `default_probes` over a fake `/proc`, and the verbs run through `cli.main`, so the
verb tests fail on the base for the reason the pilot did (BLOCKED, 14, 0, a refused send or resume). The four
`InventoryNamesTheOwningAgent` tests are the exception: they read `LiveSession.nested`, which the base does not have, so
there they fail with AttributeError — a structural RED; the behavioural RED for the same fault is the verb tests' (RV-27).
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fleet.runtime import observe, plain
from fleet.session import default_probes
from fleet.store import Declarations
from tests.test_cli import Fleet

FRAMES = Path(__file__).resolve().parents[1] / 'it' / 'fixtures' / 'runtime'
CLAUDE_EXE = '/home/u/.local/share/claude/versions/2.1.282'
CODEX_EXE = '/home/u/.local/node/lib/node_modules/@openai/codex/vendor/bin/codex'


def fake_inventory(proc_root: Path, rows, owners):
    """`list_processes()` of the real probes over a fake /proc.

    rows: (pid, ppid, comm, exe, cwd, argv); owners: {pane pid: session}. `pgrep -x <name>` answers the pids whose
    comm is <name>, `tmux list-panes -a` answers `owners`, exactly the two commands the real probe runs."""
    for pid, ppid, comm, exe, cwd, argv in rows:
        proc = proc_root / str(pid)
        proc.mkdir(parents=True)
        (proc / 'comm').write_text(comm + '\n')
        (proc / 'cmdline').write_text('\0'.join(argv) + '\0')
        (proc / 'stat').write_text(f'{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 4194304 0 0 0 0')
        (proc / 'exe').symlink_to(exe)
        (proc / 'cwd').symlink_to(cwd)

    def run(argv, **kw):
        if argv[0] == 'pgrep':
            pids = [str(pid) for pid, _, comm, *_ in rows if comm == argv[-1]]
            return subprocess.CompletedProcess(argv, 0 if pids else 1, ''.join(p + '\n' for p in pids), '')
        return subprocess.CompletedProcess(argv, 0, ''.join(f'{p} {s}\n' for p, s in owners.items()), '')

    with patch('subprocess.run', run):
        return default_probes(tmux_socket='itfleet-v23k', both_runtimes=True, proc_root=proc_root).list_processes()


def codex_pane(pane_pid, cwd, *, nested_claude=True):
    """node (the pane) -> codex -> zsh -> python3 -> claude agents --json: the pilot's tree during its suite run."""
    rows = [(pane_pid, 1, 'node', '/usr/bin/node', cwd, ['node', '/home/u/.local/node/bin/codex']),
            (pane_pid + 1, pane_pid, 'codex', CODEX_EXE, cwd, [CODEX_EXE, '-a', 'never'])]
    if nested_claude:
        rows += [(pane_pid + 2, pane_pid + 1, 'zsh', '/usr/bin/zsh', cwd, ['/usr/bin/zsh', '-c', 'fleet selftest']),
                 (pane_pid + 3, pane_pid + 2, 'python3', '/usr/bin/python3', cwd, ['python3', '-m', 'unittest']),
                 (pane_pid + 4, pane_pid + 3, 'claude', CLAUDE_EXE, '/tmp', ['/home/u/.local/bin/claude', 'agents',
                                                                            '--json'])]
    return rows


def claude_pane(pane_pid, cwd, *, nested_codex=True):
    """claude IS the pane process; it runs a codex (a real `codex exec`, say) through a shell."""
    rows = [(pane_pid, 1, 'claude', CLAUDE_EXE, cwd, ['/home/u/.local/bin/claude', '--permission-mode', 'auto'])]
    if nested_codex:
        rows += [(pane_pid + 1, pane_pid, 'bash', '/usr/bin/bash', cwd, ['bash', '-c', 'codex exec']),
                 (pane_pid + 2, pane_pid + 1, 'codex', CODEX_EXE, cwd, [CODEX_EXE, 'exec'])]
    return rows


class InventoryNamesTheOwningAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='fleet-v23k-inv-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def inventory(self, rows, owners):
        return {s.pid: s for s in fake_inventory(self.tmp / 'proc', rows, owners)}

    def test_a_claude_started_under_a_codex_worker_is_nested_and_the_codex_is_not(self):
        rows = codex_pane(200, self.tmp)
        found = self.inventory(rows, {200: 'dt-coder'})
        self.assertEqual({pid: (s.name, s.runtime) for pid, s in found.items()},
                         {201: ('dt-coder', 'codex'), 204: ('dt-coder', 'claude')})
        self.assertFalse(found[201].nested, 'the codex under node IS the pane\'s agent')
        self.assertTrue(found[204].nested, 'the claude the codex worker started is its child, not the pane\'s agent')

    def test_a_codex_started_under_a_claude_pane_is_nested_and_the_pane_root_claude_is_not(self):
        found = self.inventory(claude_pane(300, self.tmp), {300: 'dt-writer'})
        self.assertFalse(found[300].nested)
        self.assertTrue(found[302].nested)

    def test_lone_agents_are_not_nested(self):
        """Without a nested agent every row stays outer: the plain claude pane, the plain codex pane, and a claude
        no pane owns at all (OBS-48's shape) — `nested` is not "unattributed"."""
        rows = (claude_pane(300, self.tmp, nested_codex=False) + codex_pane(200, self.tmp, nested_claude=False)
                + [(400, 1, 'claude', CLAUDE_EXE, self.tmp, ['claude'])])
        found = self.inventory(rows, {200: 'dt-coder', 300: 'dt-writer'})
        self.assertEqual(sorted(found), [201, 300, 400])
        self.assertEqual([s.nested for s in found.values()], [False, False, False])
        self.assertIsNone(found[400].name)

    def test_the_walk_stops_at_the_pane_so_a_neighbouring_pane_never_nests_another(self):
        """tmux's server is the common ancestor of every pane: a walk that ran past the pane root would find the
        agent of some OTHER pane above it only if that agent were an ancestor, which a pane never is — but a pane
        started FROM an agent (a worker's own `tmux new-session`) is, and it is its own pane, not nested."""
        rows = claude_pane(300, self.tmp, nested_codex=False) + [
            (500, 300, 'tmux: server', '/usr/bin/tmux', self.tmp, ['tmux']),
            (501, 500, 'codex', CODEX_EXE, self.tmp, [CODEX_EXE])]
        found = self.inventory(rows, {300: 'dt-writer', 501: 'dt-inner'})
        self.assertFalse(found[501].nested, 'a pane root is its own pane\'s agent, whoever started its server')


class VerbsJudgeThePaneByItsOwningAgent(unittest.TestCase):
    """board, pane-guard, close, send and resume over a real-probe inventory, for a codex record on a claude box."""

    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)
        self.proc = self.f.tmp / 'proc'

    def worker(self, runtime, rows_for, frame, **tree):
        path = self.f.worker('coder', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['coder'])
        record.runtime = runtime
        self.f.store.write(record)
        self.f.procs.extend(fake_inventory(self.proc, rows_for(200 if rows_for is codex_pane else 300, path, **tree),
                                           {200 if rows_for is codex_pane else 300: record.tmux}))
        self.f.panes[record.tmux] = frame
        self.f.tmux_live.add(record.tmux)
        return record

    def board_row(self, record):
        code, out, err = self.f.run(['board', '--porcelain'])
        self.assertEqual(code, 0, err)
        return next(line for line in out.splitlines() if line.startswith(record.todo_id))

    def test_a_busy_codex_worker_running_a_claude_child_is_running_and_mid_turn(self):
        record = self.worker('codex', codex_pane, (FRAMES / 'codex-busy.frame').read_text())
        row = self.board_row(record)
        self.assertNotIn('differs from record runtime', row)
        self.assertIn('\tRUNNING\t', row)
        self.assertEqual(row.split('\t')[-2], '204', 'nested PID must remain visible on the worker row')
        code, out, err = self.f.run(['pane-guard', '--id', record.todo_id])
        self.assertEqual(code, 11, out + err)
        code, out, err = self.f.run(['close', '--id', record.todo_id])
        self.assertIn('mid-turn', out + err, 'close must refuse a busy codex pane as mid-turn, not as a mismatch')

    def test_pane_guard_reads_busy_in_short_and_long_excerpts(self):
        """These are excerpts, not captures proving terminal width; test_session pins launch argv."""
        for length in ("short", "long"):
            with self.subTest(length=length):
                self.f = Fleet()
                self.addCleanup(shutil.rmtree, self.f.tmp)
                self.proc = self.f.tmp / 'proc'
                frame = (FRAMES / f'v23e-codex-busy-{length}-excerpt.frame').read_text()
                record = self.worker('codex', codex_pane, frame, nested_claude=False)
                code, out, err = self.f.run(['pane-guard', '--id', record.todo_id])
                self.assertEqual(code, 11, out + err)

    def test_board_and_brief_agree_on_busy_parked_worker(self):
        record = self.worker('codex', codex_pane, (FRAMES / 'codex-busy.frame').read_text(),
                             nested_claude=False)
        question = 'which release carries this branch?'
        Declarations(self.f.paths['coder']).park(question)
        board = self.board_row(record)
        code, brief, err = self.f.run(['brief', '--instant', str(self.f.paths['coder']), '--porcelain'])
        self.assertEqual(code, 0, err)
        phase = next(line for line in brief.splitlines() if line.startswith('phase\t'))
        self.assertIn('\tPARKED\t', board)
        self.assertIn(question, board)
        self.assertIn('parked=' + question, phase)

    def refused_as_mid_turn(self, record, argv):
        code, out, err = self.f.run(argv)
        self.assertNotEqual(code, 0, out + err)
        self.assertIn('mid-turn', out + err)
        self.assertNotIn('runtime differs', out + err)
        self.assertEqual(self.f.killed, [], 'the busy pane was killed on a refusing path')

    def test_abort_refuses_a_busy_codex_worker_as_mid_turn_not_as_a_mismatch(self):
        """RV-17. `abort` kills the pane too and asks the same `_pane_refusal` as `close` (FB-88)."""
        record = self.worker('codex', codex_pane, (FRAMES / 'codex-busy-bgterm-0156.frame').read_text())
        self.refused_as_mid_turn(record, ['abort', '--instant', str(self.f.paths['coder']), '--reason', 'x'])

    def test_harvest_refuses_a_busy_codex_worker_as_mid_turn_not_as_a_mismatch(self):
        """RV-17. `harvest --id` of a completed, reviewed worker whose pane is still busy: the same `_pane_refusal`."""
        path = self.f.worker('done', state='complete', slot='ws1', live=False)
        self.f.reviewed(path)
        record = self.f.store.read(self.f.ids['done'])
        record.runtime = 'codex'
        self.f.store.write(record)
        self.f.procs.extend(fake_inventory(self.proc, codex_pane(200, path), {200: record.tmux}))
        self.f.panes[record.tmux] = (FRAMES / 'codex-busy-bgterm-0156.frame').read_text()
        self.f.tmux_live.add(record.tmux)
        self.refused_as_mid_turn(record, ['harvest', '--id', record.todo_id])

    def test_an_idle_codex_worker_running_a_claude_child_is_safe_to_message(self):
        record = self.worker('codex', codex_pane, (FRAMES / 'codex-idle.frame').read_text())
        self.assertEqual(self.f.run(['pane-guard', '--id', record.todo_id])[0], 0)
        self.assertEqual(self.f.run(['pane-guard', '--pane', record.tmux])[0], 0)
        message = self.f.tmp / 'msg.txt'
        message.write_text('hello')
        code, out, err = self.f.run(['send', '--id', record.todo_id, '--message-file', str(message)])
        self.assertNotIn('No matching live runtime process owns the recorded pane', out + err)

    def test_resume_adopts_a_codex_session_whose_worker_is_running_a_claude_child(self):
        record = self.worker('codex', codex_pane, (FRAMES / 'codex-idle.frame').read_text())
        code, out, err = self.f.run(['resume', '--instant', str(self.f.paths['coder'])])
        self.assertEqual(code, 0, out + err)

    def test_a_codex_dialog_reads_15_with_a_claude_child_running(self):
        record = self.worker('codex', codex_pane, (FRAMES / 'codex-approval-0156.frame').read_text())
        self.assertEqual(self.f.run(['pane-guard', '--id', record.todo_id])[0], 15)

    def test_the_slot_holder_named_for_a_record_is_the_outer_agent_not_its_nested_child(self):
        """RV-23. With no process attributed to the record's pane (its session answers nowhere), `evidence.pid` falls back
        to whatever live process holds the slot — in pgrep order, claude first. `scripts/fleet-finished-pids.sh` keys the
        auto-resume exclusion on that pid, so it must be the worker (codex 201), not its short-lived claude child (204)."""
        path = self.f.worker('coder', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['coder'])
        record.runtime = 'codex'
        self.f.store.write(record)
        slot = self.f.pool.slot_path('ws1')
        rows = [row[:4] + (slot,) + row[5:] for row in codex_pane(200, slot)]      # every process sits in the slot
        inventory = fake_inventory(self.proc, rows, {})                            # and no pane owns any of them
        self.assertEqual(sorted((s.pid, s.runtime, s.nested) for s in inventory),
                         [(201, 'codex', False), (204, 'claude', True)])
        self.assertEqual([s.pid for s in inventory], [204, 201], 'pgrep lists claude first — the order that misled')
        self.f.procs.extend(inventory)
        code, out, err = self.f.run(['status', '--id', record.todo_id, '--porcelain'])
        self.assertEqual(code, 0, err)
        self.assertIn('pid\t201', out, out)

    def test_unowned_pane_keeps_nested_child_visible_and_marked(self):
        self.f.worker('holder', slot='ws1', live=False)
        slot = self.f.pool.slot_path('ws1')
        self.f.procs.extend(fake_inventory(self.proc, codex_pane(200, slot), {200: 'dt-unowned'}))
        code, out, err = self.f.run(['board', '--porcelain'])
        self.assertEqual(code, 0, err)
        rows = [row.split('\t') for row in out.splitlines() if '\tunknown-session\t' in row]
        self.assertEqual(len(rows), 1, out)
        self.assertEqual(rows[0][-1], '204', 'child outside the slot is folded into its live parent row')
        self.assertEqual(rows[0][-2], 'fixture-server', out)

    # --- the mismatch that IS real still reads as one -------------------------------------------------------------

    def test_a_codex_record_whose_pane_agent_is_claude_is_still_a_mismatch(self):
        """The pane's OWN agent is claude (a nested codex under it changes nothing): board BLOCKED, pane-guard 14,
        send and resume refused."""
        record = self.worker('codex', claude_pane, (FRAMES / 'claude-idle.frame').read_text())
        row = self.board_row(record)
        self.assertIn('\tBLOCKED\t', row)
        self.assertIn('live runtime claude differs from record runtime codex', row)
        self.assertEqual(self.f.run(['pane-guard', '--id', record.todo_id])[0], 14)
        message = self.f.tmp / 'msg.txt'
        message.write_text('hello')
        code, out, err = self.f.run(['send', '--id', record.todo_id, '--message-file', str(message)])
        self.assertNotEqual(code, 0, out + err)
        self.assertEqual(self.f.run(['resume', '--instant', str(self.f.paths['coder'])])[0], 4)

    def test_a_claude_record_whose_pane_agent_is_codex_is_still_a_mismatch(self):
        record = self.worker('claude', codex_pane, (FRAMES / 'codex-idle.frame').read_text())
        row = self.board_row(record)
        self.assertIn('live runtime codex differs from record runtime claude', row)
        self.assertEqual(self.f.run(['pane-guard', '--id', record.todo_id])[0], 14)

    def test_a_claude_record_with_a_nested_codex_is_judged_as_claude(self):
        record = self.worker('claude', claude_pane, (FRAMES / 'claude-busy.frame').read_text())
        self.assertNotIn('differs from record runtime', self.board_row(record))
        self.assertEqual(self.f.run(['pane-guard', '--id', record.todo_id])[0], 11)


class CodexBusyAsDrawnBy0156(unittest.TestCase):
    """Real codex-cli 0.156 frames (`it/fixtures/runtime/*-0156.frame`, captured by §OR on a private server).

    `codex-busy-bgterm-0156`: `• Working (8s • esc to interrupt) · 1 background terminal running · /ps to view…` — codex
    runs even a foreground command as an exec session, so this tail is on the spinner row of every tool turn.
    `codex-waiting-bgterm-0156`: `◦ Waiting for background terminal (35s • esc to interrupt) · …` with `  └ sleep 41`
    beneath it. Both read `idle` on the base, so pane-guard said `0 safe` for a worker mid-turn."""

    BUSY = ('codex-busy-bgterm-0156', 'codex-waiting-bgterm-0156')

    def frame(self, name):
        return (FRAMES / f'{name}.frame').read_text()

    def test_both_live_busy_frames_are_busy(self):
        for name in self.BUSY:
            with self.subTest(frame=name):
                self.assertEqual(observe('codex', self.frame(name)).state, 'busy')

    def test_control_the_idle_frame_after_those_turns_is_idle(self):
        self.assertEqual(observe('codex', self.frame('codex-idle-after-turns-0156')).state, 'idle')
        self.assertEqual(observe('codex', self.frame('codex-idle')).state, 'idle')
        self.assertEqual(observe('codex', self.frame('codex-busy')).state, 'busy')

    def test_a_spinner_above_a_finished_answer_is_scrollback_not_a_turn(self):
        """The detail rows skipped on the way up are INDENTED rows; an unindented row (the agent's answer) ends the
        walk, so a stale spinner above it is never read as the current turn."""
        text = self.frame('codex-waiting-bgterm-0156').replace('  └ sleep 41', '• DONE2')
        self.assertIn('• DONE2', text)
        self.assertEqual(observe('codex', text).state, 'idle')

    def test_prose_that_quotes_the_hint_is_not_a_spinner(self):
        for prose in ('• Pressing esc to interrupt (any time) stops a turn',
                      '• The status row reads (esc to interrupt)'):
            with self.subTest(prose=prose):
                text = self.frame('codex-waiting-bgterm-0156').replace('  └ sleep 41', prose)
                self.assertEqual(observe('codex', text).state, 'idle')

    def with_spinner_row(self, row):
        """The real `codex-busy-bgterm-0156` frame with its spinner row replaced by `row`, drawn DIM as codex draws it.
        Everything else — the blank rows, the bold caret, the footer — is the capture's own."""
        lines = self.frame('codex-busy-bgterm-0156').split('\n')
        spinner = [i for i, line in enumerate(lines) if 'esc' in line and plain(line).startswith(('•', '◦'))]
        self.assertEqual(len(spinner), 1, 'the fixture has exactly one spinner row')
        lines[spinner[0]] = f'\x1b[2m{row}\x1b[0m\x1b[39m\x1b[49m'
        return '\n'.join(lines)

    def test_a_header_with_parentheses_is_still_a_turn(self):
        """RV-21. codex writes reasoning titles into the header; a paren in one read `idle` (the base regex matched it)."""
        text = self.with_spinner_row('• Inspecting list_processes (nested walk) (8s • esc to interrupt) · 1 background '
                                     'terminal running · /ps to view…')
        self.assertEqual(observe('codex', text).state, 'busy')

    def test_a_row_cut_at_the_pane_edge_inside_its_paren_is_still_a_turn(self):
        """RV-21. fleet starts panes 80 columns wide and codex cuts the row with `…`, as the committed frames show; a long
        header pushes the cut into the paren group."""
        for row in ('• Running tests for the new inventory walk and the reconcile ordering (1m 05s • esc to inte…',
                    '◦ Running tests for the new inventory walk and the reconcile ordering, all of them (1m…',
                    '• Running tests for the new inventory walk and the reconcile ordering (12s…'):
            with self.subTest(row=row):
                self.assertEqual(observe('codex', self.with_spinner_row(row)).state, 'busy')

    def test_a_row_cut_at_the_pane_edge_just_after_its_paren_is_still_a_turn(self):
        """RV-29. The cut can also land just AFTER the closed elapsed-time paren, on the ` · ` separator or right at the
        paren; the elapsed time is whole, so it proves a turn and reads busy (11), not unknown (14)."""
        for row in ('• Running tests for the new inventory walk and the reconcile order (8s • esc to interrupt)…',
                    '• Running tests for the new inventory walk and the reconcile (8s • esc to interrupt) …',
                    '• Running tests for the new inventory walk and the reconcil (8s • esc to interrupt) ·…',
                    '◦ Waiting for background terminal and the reconcile ordering (1m 05s • esc to interrupt)·…'):
            with self.subTest(row=row):
                self.assertEqual(observe('codex', self.with_spinner_row(row)).state, 'busy')

    def test_a_spinner_row_cut_before_its_paren_fails_closed(self):
        """RV-21. Cut before the paren there is no elapsed time to prove a turn and no way to rule one out: `unknown`
        (pane-guard 14, wait) rather than `idle` (0, send)."""
        row = ('• Running the whole hermetic suite, the scripts/tests near the change and the live codex integration run…')
        self.assertEqual(observe('codex', self.with_spinner_row(row)).state, 'unknown')

    def test_neighbours_of_the_widened_spinner_stay_idle(self):
        """What the widened spinner must still turn away: prose with a paren but no elapsed time, a finished answer
        ending in a paren note, and an answer cut mid-word without a spinner shape."""
        for row in ('• The status row reads (esc to interrupt)',
                    '• Inspecting list_processes (nested walk)',
                    '• DONE (see evidence/INDEX.md)',
                    '• DONE2'):
            with self.subTest(row=row):
                self.assertEqual(observe('codex', self.with_spinner_row(row)).state, 'idle')

    def test_pane_guard_reads_a_busy_codex_pane_as_mid_turn_on_a_claude_box(self):
        for name in self.BUSY:
            with self.subTest(frame=name):
                f = Fleet()
                self.addCleanup(shutil.rmtree, f.tmp)
                path = f.worker('coder', slot='ws1', live=False)
                record = f.store.read(f.ids['coder'])
                record.runtime = 'codex'
                f.store.write(record)
                f.procs.extend(fake_inventory(f.tmp / 'proc', codex_pane(200, path, nested_claude=False),
                                              {200: record.tmux}))
                f.panes[record.tmux] = self.frame(name)
                f.tmux_live.add(record.tmux)
                self.assertEqual(f.run(['pane-guard', '--id', record.todo_id])[0], 11)
                self.assertEqual(f.run(['pane-guard', '--pane', record.tmux])[0], 11)
                code, out, err = f.run(['close', '--id', record.todo_id])
                self.assertNotEqual(code, 0, out + err)
                self.assertIn('mid-turn', out + err)


if __name__ == '__main__':
    unittest.main()
