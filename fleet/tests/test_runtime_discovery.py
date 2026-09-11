import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fleet.errors import FleetError
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
