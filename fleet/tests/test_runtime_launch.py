import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from fleet.errors import BadInput
from fleet.runtime import LaunchSettings
from fleet.runtime_launch import launch_argv, resume_argv, prepare, resolve_settings
from tests.test_store import rec


class LaunchTests(unittest.TestCase):
    def test_argument_boundaries_and_exact_resume(self):
        prompt = "line one\n'quoted' `literal` $(literal)"
        for runtime in ('claude', 'codex'):
            settings = LaunchSettings(runtime, '/opt/bin/' + runtime, '/cfg')
            argv = launch_argv(settings, prompt)
            self.assertEqual(argv[-1], prompt)
            self.assertEqual(shlex.split(shlex.join(argv)), argv)
            self.assertNotIn('--model', argv)
            self.assertFalse(any('dangerously' in x for x in argv))
            uuid = '12345678-1234-1234-1234-123456789abc'
            resumed = resume_argv(settings, uuid)
            self.assertIn(uuid, resumed)
            self.assertNotIn('--last', resumed)
            for invalid in ('--last', '', 'newest', '../file'):
                with self.assertRaises(BadInput):
                    resume_argv(settings, invalid)

    def test_launcher_delivers_literal_seed_and_explicit_environment(self):
        with tempfile.TemporaryDirectory(prefix='fleet launch ') as directory:
            root = Path(directory)
            binary = root / 'stub agent'
            binary.write_text('#!/usr/bin/env python3\nimport json,os,sys\nprint(json.dumps([sys.argv[1:],os.environ["CODEX_HOME"],os.environ["FLEET_HOME"]]))\n')
            binary.chmod(0o700)
            child = root / 'instant'
            seed = child / '.fleet/seed.txt'
            seed.parent.mkdir(parents=True)
            prompt = "task\n'quoted' `echo BAD` $(touch BAD)"
            seed.write_text(prompt)
            record = rec(child_instant=str(child),runtime='codex',root=str(root),tmux_socket='private')
            settings = LaunchSettings('codex', str(binary), str(root / 'config'))
            launcher = prepare(settings,record,seed,{'FLEET_HOME':str(root/'store'),'FLEET_INSTANTS':str(root)})
            done = subprocess.run(['bash',str(launcher)],capture_output=True,text=True,check=True)
            argv,config,home=json.loads(done.stdout)
            self.assertEqual(argv[-1],prompt)
            self.assertEqual(config,settings.config_dir)
            self.assertEqual(home,str(root/'store'))
            self.assertFalse((root/'BAD').exists())
            seed.write_text('')
            self.assertNotEqual(subprocess.run(['bash',str(launcher)],capture_output=True).returncode,0)

    def test_missing_executable_and_config_refuse(self):
        with self.assertRaises(BadInput):
            resolve_settings('codex',Path('/slot'),{},lambda x:None,lambda *a:None)

    def test_launch_and_resume_preserve_terminal_attributes_for_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'agent'
            binary.write_text('#!/usr/bin/env python3\nimport json,os\nprint(json.dumps(dict(os.environ)))\n')
            binary.chmod(0o700)
            seed = root / '.fleet/seed.txt'
            seed.parent.mkdir()
            seed.write_text('task')
            inherited = dict(os.environ, NO_COLOR='1', TERM='screen', FLEET_TEST_SENTINEL='kept')
            for runtime in ('claude', 'codex'):
                for session_id in (None, '12345678-1234-1234-1234-123456789abc'):
                    with self.subTest(runtime=runtime, session_id=session_id):
                        record = rec(child_instant=str(root), runtime=runtime)
                        settings = LaunchSettings(runtime, str(binary), str(root))
                        launcher = prepare(settings, record, seed, inherited, session_id=session_id)
                        done = subprocess.run(['bash', str(launcher)], env=inherited,
                                              capture_output=True, text=True, check=True)
                        environment = json.loads(done.stdout)
                        self.assertFalse('NO_COLOR' in environment)
                        self.assertEqual(environment['TERM'], 'screen')
                        self.assertEqual(environment['FLEET_TEST_SENTINEL'], 'kept')

    def test_claude_launch_preserves_executable_alias_for_process_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version = root / '2.1.268'
            version.write_text('#!/bin/sh\nexit 0\n')
            version.chmod(0o700)
            alias = root / 'claude'
            alias.symlink_to(version)
            config = root / '.claude'
            config.mkdir()
            settings = resolve_settings('claude', root, {}, lambda name: str(alias),
                                        lambda command: (0, str(config), ''))
            self.assertEqual(settings.executable, str(alias))
            self.assertEqual(launch_argv(settings, 'task')[0], str(alias))
