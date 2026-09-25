import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from fleet.errors import BadInput, Refused
from fleet.runtime_config import admission_lock, pane_lock, read_runtime, write_runtime


def hold_lock(home, ready, finish):
    with admission_lock(Path(home)):
        ready.send(True)
        finish.recv()


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'store'

    def test_absence_is_read_only_legacy_default(self):
        self.assertEqual(read_runtime(self.home), ('claude', 'legacy-default'))
        self.assertFalse(self.home.exists())

    def test_round_trip(self):
        with admission_lock(self.home):
            write_runtime(self.home, 'codex')
        self.assertEqual(read_runtime(self.home), ('codex', 'saved'))

    def test_invalid_configuration_never_defaults(self):
        self.home.mkdir()
        values = ['{', 'null', '[]', 'true', '{}']
        for runtime in ([], {}, None, True, 1, 'typo'):
            values.append(json.dumps(dict(schema_version=1, runtime=runtime)))
        values += [json.dumps(dict(schema_version=version, runtime='claude'))
                   for version in (True, 1.0, 2, None)]
        values.append('{"schema_version":1,"runtime":"codex","extra":1}')
        for raw in values:
            with self.subTest(raw=raw):
                (self.home / 'runtime.json').write_text(raw)
                with self.assertRaises(BadInput):
                    read_runtime(self.home)

    def test_broken_link_and_unreadable_directory_refuse(self):
        self.home.mkdir()
        path = self.home / 'runtime.json'
        path.symlink_to(self.home / 'missing')
        with self.assertRaises(BadInput):
            read_runtime(self.home)
        path.unlink()
        path.mkdir()
        with self.assertRaises(BadInput):
            read_runtime(self.home)

    def test_process_death_releases_stable_lock(self):
        receive, ready = multiprocessing.Pipe(False)
        finish, send = multiprocessing.Pipe(False)
        proc = multiprocessing.Process(target=hold_lock, args=(str(self.home), ready, finish))
        proc.start()
        self.addCleanup(lambda: proc.kill() if proc.is_alive() else None)
        self.assertTrue(receive.poll(5))
        receive.recv()
        lock = self.home / '.runtime-admission.lock'
        inode = lock.stat().st_ino
        with self.assertRaises(Refused), admission_lock(self.home, timeout_s=0):
            self.fail('contender acquired a held lock')
        proc.kill()
        proc.join(5)
        with admission_lock(self.home, timeout_s=1):
            self.assertEqual(lock.stat().st_ino, inode)
        for pipe in (receive, ready, finish, send):
            pipe.close()

    def test_roots_and_panes_are_independent(self):
        with admission_lock(self.home), admission_lock(self.home / 'other', timeout_s=0):
            with pane_lock(self.home, 'socket', 'one'), pane_lock(self.home, 'socket', 'two', timeout_s=0):
                with pane_lock(self.home, 'other', 'one', timeout_s=0):
                    with self.assertRaises(Refused), pane_lock(self.home, 'socket', 'one', timeout_s=0):
                        self.fail('same pane was not serialized')
