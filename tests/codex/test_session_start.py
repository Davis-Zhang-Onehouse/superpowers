"""Execute the Codex manifest's startup hook, including relocated installs."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]


class CodexBootstrap(unittest.TestCase):
    def hook(self):
        manifest = json.loads((REPO / '.codex-plugin/plugin.json').read_text())
        configured = manifest.get('hooks')
        self.assertIsInstance(configured, str,
                              'Codex must register its native bootstrap hook')
        config = json.loads((REPO / configured).read_text())
        return config['hooks']['SessionStart'][0]

    def run_hook(self, root, source='startup'):
        group = self.hook()
        self.assertIsNotNone(re.fullmatch(group['matcher'], source))
        handler = group['hooks'][0]
        self.assertFalse(handler.get('async', False))
        env = dict(os.environ, PLUGIN_ROOT=str(root))
        env.pop('CLAUDE_PLUGIN_ROOT', None)
        return subprocess.run(['bash', '-c', handler['command']], cwd=root.parent,
                              input=json.dumps({'source': source}), env=env,
                              capture_output=True, text=True)

    def test_start_resume_clear_and_compaction_receive_complete_bootstrap(self):
        bootstrap = (REPO / 'skills/using-superpowers/SKILL.md').read_text()
        for source in ('startup', 'resume', 'clear', 'compact'):
            with self.subTest(source=source):
                result = self.run_hook(REPO, source)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)['hookSpecificOutput']
                self.assertEqual(output['hookEventName'], 'SessionStart')
                self.assertIn(bootstrap, output['additionalContext'])
                self.assertEqual(result.stderr, '')

    def test_relocated_plugin_with_spaces_uses_its_own_bootstrap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'installed plugin with spaces'
            (root / 'hooks').mkdir(parents=True)
            (root / 'skills/using-superpowers').mkdir(parents=True)
            self.hook()  # fail on a missing registration before constructing the fixture
            shutil.copyfile(REPO / 'hooks/session-start-codex', root / 'hooks/session-start-codex')
            text = 'Bootstrap from the relocated install: "quotes" and \\slashes\n'
            (root / 'skills/using-superpowers/SKILL.md').write_text(text)
            result = self.run_hook(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(text, json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])

    def test_missing_bootstrap_fails_instead_of_reporting_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'hooks').mkdir()
            self.hook()
            shutil.copyfile(REPO / 'hooks/session-start-codex', root / 'hooks/session-start-codex')
            result = self.run_hook(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
