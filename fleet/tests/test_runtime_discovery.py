import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fleet.errors import BadInput, FleetError
from fleet.session import default_probes
from fleet.peers import classify, from_live_sessions


class DiscoveryTests(unittest.TestCase):
    def test_both_native_workers_are_found_through_pane_ancestry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, comm, exe, ppid in ((101, 'claude', '/opt/claude/versions/2.1.268', 1),
                                         (102, 'codex', '/opt/vendor/bin/codex', 103),
                                         (103, 'node', '/bin/node', 1)):
                proc = root / str(pid)
                proc.mkdir()
                (proc / 'comm').write_text(comm)
                (proc / 'cmdline').write_text(comm + '\0')
                (proc / 'stat').write_text(f'{pid} ({comm}) S {ppid} 0')
                (proc / 'exe').symlink_to(exe)
                (proc / 'cwd').symlink_to(root)
            def run(argv, **kw):
                output = ('101\n' if argv[-1] == 'claude' else '102\n') if argv[0] == 'pgrep' else '101 one\n103 two\n'
                return subprocess.CompletedProcess(argv, 0, output, '')
            with patch('subprocess.run', run):
                sessions = default_probes(both_runtimes=True, proc_root=root).list_processes()
            self.assertEqual([(s.name, s.runtime) for s in sessions], [('one', 'claude'), ('two', 'codex')])
            rows = from_live_sessions(sessions, socket='private')
            self.assertEqual(rows[1]['transport'], 'tmux')
            self.assertEqual(rows[1]['name'], 'two')
            lease = dict(golden=str(root), tmux='two', runtime='codex', tmux_socket='private')
            result = classify(rows, [lease], self_pid=-1, proc_root=str(root))
            self.assertTrue(all(r['verdict'] == 'FOREIGN' for r in result))

    def test_discovery_failure_is_not_empty_inventory(self):
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 2, '', 'denied')):
            with self.assertRaises(FleetError):
                default_probes(both_runtimes=True).list_processes()

    def test_denied_tmux_access_is_not_an_empty_server(self):
        def run(argv, **kw):
            error = 'error connecting to /tmp/tmux-1000/test (Operation not permitted)' if argv[0] == 'tmux' else ''
            return subprocess.CompletedProcess(argv, 1, '', error)
        with patch('subprocess.run', run):
            with self.assertRaisesRegex(FleetError, 'Operation not permitted'):
                default_probes(both_runtimes=True).list_processes()

    def test_absent_tmux_server_allows_initial_dispatch_inventory(self):
        for error in ('no server running on /tmp/tmux-1000/test',
                      'error connecting to /tmp/tmux-1000/test (No such file or directory)'):
            def run(argv, **kw):
                return subprocess.CompletedProcess(argv, 1, '', error if argv[0] == 'tmux' else '')
            with patch('subprocess.run', run):
                self.assertEqual(default_probes(both_runtimes=True).list_processes(), [])

    def test_exited_workers_are_omitted_but_unreadable_live_workers_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / '101'
            proc.mkdir()
            (proc / 'comm').write_text('codex')
            def run(argv, **kw):
                return subprocess.CompletedProcess(argv, 0, '101\n' if argv[0] == 'pgrep' else '', '')
            with patch('subprocess.run', run):
                probes = default_probes(process_name='codex', proc_root=root)
                for state in ('Z', 'X'):
                    (proc / 'stat').write_text(f'101 (codex) {state} 1 0')
                    self.assertEqual(probes.list_processes(), [])
                (proc / 'stat').write_text('101 (codex) S 1 0')
                with self.assertRaises(FleetError):
                    probes.list_processes()


class EmptyOrExitingTmuxServerTests(unittest.TestCase):
    """B26. Two server states that hold no pane, measured on tmux 3.2a, used to kill every observation verb.

    A: alive with ZERO sessions — `list-panes -a` answers `no current target` rc=1 because it needs a current
       session even with `-a`, while `list-sessions` answers rc=0 with no rows. Reached live when a stopped
       (`T`) `tmux attach` client outlived its session and held the server up.
    B: exiting but held — `kill-server` on such a server leaves it waiting for that client, and EVERY command
       answers `server exited unexpectedly`. It holds no session: `new-session` and `has-session` fail too.
    """

    @staticmethod
    def fake(panes, sessions=(0, '', ''), calls=None):
        def run(argv, **kw):
            if calls is not None:
                calls.append(argv)
            if argv[0] == 'pgrep':
                return subprocess.CompletedProcess(argv, 1, '', '')
            if 'list-panes' in argv:
                return subprocess.CompletedProcess(argv, *panes)
            if 'list-sessions' in argv:
                return subprocess.CompletedProcess(argv, *sessions)
            raise AssertionError(f'unexpected argv {argv}')
        return run

    def test_a_live_server_with_zero_sessions_is_an_empty_population(self):
        calls = []
        with patch('subprocess.run', self.fake((1, '', 'no current target\n'), calls=calls)):
            self.assertEqual(default_probes(both_runtimes=True, tmux_socket='priv').list_processes(), [])
        # Confirmed by a POSITIVE observation, not by the string alone.
        self.assertIn(['tmux', '-L', 'priv', 'list-sessions', '-F', '#{session_name}'], calls)

    def test_no_current_target_with_sessions_listed_is_not_read_as_empty(self):
        """The string alone is not the fact: if sessions DO exist and list-panes still cannot answer, refuse.

        A GUARD, and it passes on the base too (the base refused every such shape); it pins that the fix
        did not buy state A by reading every `no current target` as empty."""
        with patch('subprocess.run', self.fake((1, '', 'no current target'), sessions=(0, 'w1\n', ''))):
            with self.assertRaisesRegex(FleetError, 'no current target.*listing 1 session'):
                default_probes(both_runtimes=True, tmux_socket='priv').list_processes()

    def test_no_current_target_with_list_sessions_failing_otherwise_names_both_answers(self):
        with patch('subprocess.run', self.fake((1, '', 'no current target'), sessions=(1, '', 'weird'))):
            with self.assertRaisesRegex(FleetError, 'no current target.*list-sessions` then exited 1: weird'):
                default_probes(both_runtimes=True, tmux_socket='priv').list_processes()

    def test_a_server_that_is_exiting_under_the_call_is_an_empty_population(self):
        for answer in ('server exited unexpectedly\n', 'no server running on /tmp/tmux-1000/priv\n'):
            with patch('subprocess.run', self.fake((1, '', 'server exited unexpectedly\n'), sessions=(1, '', answer))):
                self.assertEqual(default_probes(both_runtimes=True, tmux_socket='priv').list_processes(), [])

    def test_one_lost_call_to_a_server_that_still_lists_sessions_is_not_read_as_empty(self):
        """`server exited unexpectedly` is tmux's generic lost-the-server message: a server that answers the
        confirming call with sessions is alive, and reading it as empty would mark every worker DEAD."""
        with patch('subprocess.run', self.fake((1, '', 'server exited unexpectedly'), sessions=(0, 'w1\n', ''))):
            with self.assertRaisesRegex(FleetError, 'server exited unexpectedly'):
                default_probes(both_runtimes=True, tmux_socket='priv').list_processes()

    def test_the_refusal_names_the_socket_the_command_the_stderr_and_what_clears_it(self):
        error = 'error connecting to /tmp/tmux-1000/priv (Operation not permitted)'
        with patch('subprocess.run', self.fake((1, '', error))):
            with self.assertRaises(FleetError) as raised:
                default_probes(both_runtimes=True, tmux_socket='priv').list_processes()
        message = str(raised.exception)
        for needle in ("socket 'priv'", '`tmux -L priv list-panes -a` exited 1', 'Operation not permitted',
                       'clears when:', 'clears who:'):
            self.assertIn(needle, message)
        # A permission failure is not a held client, so the refusal does not send the reader after one.
        self.assertNotIn('ps -o pid,stat,args', message)

    def test_the_default_server_is_named_as_such_in_the_refusal(self):
        with patch('subprocess.run', self.fake((1, '', 'boom'))):
            with self.assertRaisesRegex(FleetError, 'the default socket'):
                default_probes(both_runtimes=True, tmux_socket=None).list_processes()

    def test_starting_a_session_on_an_exiting_server_names_the_route(self):
        def run(argv, **kw):
            return subprocess.CompletedProcess(argv, 1, '', 'server exited unexpectedly\n')
        with patch('subprocess.run', run):
            with self.assertRaises(BadInput) as raised:
                default_probes(tmux_socket='priv').start_session('w', Path('/'), 'true')
        message = str(raised.exception)
        for needle in ('server exited unexpectedly', 'clears when:', 'ps -o pid,stat,args -C tmux', 'clears who:'):
            self.assertIn(needle, message)


@unittest.skipUnless(shutil.which('tmux'), 'tmux is not installed')
class EmptyTmuxServerAgainstRealTmux(unittest.TestCase):
    """State A on a REAL private server: `exit-empty off` keeps it alive after its only session is killed."""

    def setUp(self):
        self.socket = f'itfleet-selftest-b26-{os.getpid()}'
        self.directory = tempfile.TemporaryDirectory()
        config = Path(self.directory.name) / 'tmux.conf'
        config.write_text('set -g exit-empty off\n')
        tmux = ['tmux', '-L', self.socket]
        # Registered BEFORE the server exists: an `exit-empty off` server left behind by a failed setUp would
        # never exit. Cleanups run last-in first-out: kill the server, THEN remove the socket file it leaves.
        path = Path(os.environ.get('TMUX_TMPDIR') or '/tmp') / f'tmux-{os.getuid()}' / self.socket
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        self.addCleanup(subprocess.run, tmux + ['kill-server'], capture_output=True)
        self.addCleanup(self.directory.cleanup)
        subprocess.run(tmux + ['-f', str(config), 'new-session', '-d', '-s', 'x', 'sleep 60'], check=True)
        subprocess.run(tmux + ['kill-session', '-t', '=x'], check=True)

    def test_the_fixture_is_really_an_empty_live_server(self):
        panes = subprocess.run(['tmux', '-L', self.socket, 'list-panes', '-a'], capture_output=True, text=True)
        sessions = subprocess.run(['tmux', '-L', self.socket, 'list-sessions'], capture_output=True, text=True)
        self.assertEqual((panes.returncode, panes.stderr.strip()), (1, 'no current target'))
        self.assertEqual((sessions.returncode, sessions.stdout), (0, ''))

    def test_list_processes_reads_it_as_an_empty_population(self):
        probes = default_probes(process_name='fleet-b26-no-such-process', tmux_socket=self.socket)
        self.assertEqual(probes.list_processes(), [])
