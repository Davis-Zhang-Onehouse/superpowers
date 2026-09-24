"""FB-111. Which superpowers skills a codex worker can see, and the one link that makes a deploy move them.

A claude worker gets its skills from the marketplace entry in the root's `.claude/settings.json`, which names
`fleet-releases/current`, so every deploy moves them. Nothing did the same for codex: a codex worker that
`fleet dispatch --runtime codex` launched had no superpowers skills at all, while its seed told it to load
several.

**How codex-cli 0.156.1 finds skills — measured in private CODEX_HOMEs, not read from docs** (the instant's
`evidence/03-mechanism/`, decision W5-D1):

- `codex plugin marketplace add <releases>/current` CANONICALIZES the path. config.toml records `fleet-v0.6.6`,
  not `current`, so the next deploy would leave codex on the old release.
- `codex plugin add superpowers@superpowers-dev` runs `git clone` on the marketplace's `url: ./` source. It
  fails on a release tree, which is not a git repository. Where it succeeds it COPIES the plugin into
  `CODEX_HOME/plugins/cache`, which is a snapshot.
- codex scans `$CODEX_HOME/skills` recursively and follows symlinks, and it skips its own `.system` skills.
  With `CODEX_HOME/skills/superpowers -> <releases>/current/skills`, `codex debug prompt-input` lists every
  skill as `superpowers:<name>`, the same names claude uses, with `file: <root>/superpowers/<name>/SKILL.md`,
  a path THROUGH the link.

So the installer writes exactly one symlink and writes its target LITERALLY as `<releases>/current/skills`.
The model reads whatever `current` points at when it opens the file, and a deploy moves codex with claude
without refreshing anything. `follows_current` is the check that tells a link naming `current` apart from one
pinned to a single release, which works today and goes stale at the next deploy.

`visible_skills` is a filesystem proxy for codex's own scan: the dispatch check has to run in the hermetic
suite, and `codex debug prompt-input` spawns codex and writes into CODEX_HOME. The IT case
`fleet/it/run-codex-skills.sh` checks this proxy against codex itself.
"""
import argparse
from dataclasses import dataclass, field
import os
from pathlib import Path
import shlex
import sys

from fleet.atomic import atomic_symlink

#: The skills a fleet worker's seed, charter and method name. A CODEX_HOME that lacks any of them sends a
#: worker in to improvise the step the skill exists to discipline, which is the FB-111 defect. The full
#: set is reported as a count; only these gate.
CORE_SKILLS = ('using-superpowers', 'systematic-debugging', 'brainstorming', 'writing-plans',
               'subagent-driven-development', 'test-driven-development', 'verification-before-completion',
               'working-as-a-dispatched-instant', 'using-fleet', 'harvesting-an-instant', 'releasing-fleet')

#: `CODEX_HOME/skills/<LINK_NAME>`. codex derives the `superpowers:` prefix from the tree it finds the skill in.
LINK_NAME = 'superpowers'

#: codex's own bundled skills (imagegen, skill-installer, ...). They live under `skills/.system`, codex
#: re-seeds them, and they are never ours.
_SYSTEM_DIR = '.system'

#: How deep each scan goes. `skills/superpowers/<name>/SKILL.md` is depth 2. A plugin install is
#: `plugins/cache/<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md`, depth 6.
_SKILLS_DEPTH, _PLUGIN_DEPTH = 3, 6

_REPO = Path(__file__).resolve().parents[3]
SCRIPT = _REPO / 'scripts' / 'fleet-codex-skills.sh'

EXIT_OK, EXIT_FAILED, EXIT_BAD_INPUT, EXIT_REFUSED = 0, 1, 2, 4


@dataclass(frozen=True)
class Visibility:
    """What one CODEX_HOME shows codex. `found` maps a skill's directory name to its SKILL.md path as codex
    presents it, unresolved, so it names the link and not the release it resolves to today."""
    codex_home: str
    found: dict = field(default_factory=dict)
    missing: tuple = ()
    link_target: str = ''

    @property
    def ok(self) -> bool:
        return not self.missing

    @property
    def skills_root(self) -> str:
        bootstrap = self.found.get('using-superpowers')
        return str(Path(bootstrap).parent.parent) if bootstrap else ''


def link_path(codex_home) -> Path:
    return Path(codex_home) / 'skills' / LINK_NAME


def expected_target(releases) -> Path:
    """Deliberately NOT resolved: the whole mechanism is that this path names `current`."""
    return Path(releases) / 'current' / 'skills'


def _scan(top: Path, depth: int, skip=()) -> dict:
    found = {}
    #: `os.path.isdir`, not `Path.is_dir`: on 3.10 the latter re-raises EACCES, and an unreadable home must read
    #: as "sees nothing", not as a traceback.
    if not os.path.isdir(top):
        return found
    base = len(top.parts)
    for dirpath, dirnames, filenames in os.walk(top, followlinks=True, onerror=lambda _exc: None):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        if len(here.parts) - base >= depth:
            dirnames[:] = []
        if 'SKILL.md' in filenames and here != top:
            found.setdefault(here.name, str(here / 'SKILL.md'))
    return found


def visible_skills(codex_home) -> Visibility:
    """Every skill codex would list for `codex_home`. `skills/` wins over a plugin install for the same name.
    Never raises for a missing or unreadable home: it reports that home as seeing nothing."""
    home = Path(codex_home)
    found = _scan(home / 'plugins' / 'cache', _PLUGIN_DEPTH)
    found.update(_scan(home / 'skills', _SKILLS_DEPTH, skip=(_SYSTEM_DIR,)))
    link = link_path(home)
    try:
        target = os.readlink(link) if os.path.islink(link) else ''
    except OSError:
        target = ''
    return Visibility(str(home), found, tuple(name for name in CORE_SKILLS if name not in found), target)


def follows_current(codex_home, releases) -> tuple:
    """(True, why) only when `CODEX_HOME/skills/superpowers` is a link whose literal target is `<X>/skills`,
    where `<X>` is itself a symlink that resolves to where `<releases>/current` does. A link to
    `fleet-vN/skills` resolves fine today and is still wrong: the next deploy leaves it behind."""
    link = link_path(codex_home)
    if not os.path.islink(link):
        what = 'is a real directory or file' if os.path.exists(link) else 'does not exist'
        return False, f'{link} {what}; codex sees no link to {expected_target(releases)}'
    try:
        raw = os.readlink(link)
    except OSError as exc:
        return False, f'{link} cannot be read: {exc}'
    target = Path(raw) if os.path.isabs(raw) else link.parent / raw
    current = Path(releases) / 'current'
    if target.name != 'skills':
        return False, f'{link} -> {raw} does not name a release\'s skills directory'
    if not os.path.islink(target.parent):
        return False, (f'{link} -> {raw} is pinned to one release: {target.parent.name} is not the `current` '
                       f'symlink, so the next deploy leaves codex behind')
    if os.path.realpath(target.parent) != os.path.realpath(current):
        return False, (f'{link} -> {raw} follows {target.parent}, which resolves to '
                       f'{os.path.realpath(target.parent)}, not to {current} '
                       f'({os.path.realpath(current)})')
    if not os.path.isdir(target):
        return False, f'{link} -> {raw} does not resolve to a directory'
    return True, f'{link} -> {raw} follows {current} (today {os.path.realpath(current)})'


def install_command(codex_home) -> str:
    return (f'{shlex.quote(str(SCRIPT))} --codex-home {shlex.quote(str(codex_home))} '
            f'--releases "$FLEET_RELEASES"')


def load_instruction(vis: Visibility) -> str:
    root = vis.skills_root or str(link_path(vis.codex_home))
    return (f"Superpowers skills on codex: your session's Skills list names them superpowers:<name>. To use one, "
            f"read its SKILL.md in full with your shell (e.g. `cat <path>`) and follow it; the file is the skill. "
            f"Read superpowers:using-superpowers first. Where a skill names a Claude Code tool, use the codex "
            f"equivalent in {root}/using-superpowers/references/codex-tools.md. This CODEX_HOME "
            f"({vis.codex_home}) sees {len(vis.found)} skill(s) under {root}.")


def _ours(link: Path) -> bool:
    """A link this installer may repoint: it resolves to a superpowers skills tree. Anything else at that
    path belongs to someone else, and is refused rather than overwritten."""
    return os.path.islink(link) and os.path.isfile(link / 'using-superpowers' / 'SKILL.md')


def _emit(state: str, detail: str, stream=None) -> None:
    print(f'codex-skills  {state}  {detail}', file=stream or sys.stdout)


def _check(home: Path, releases: Path) -> int:
    ok, why = follows_current(home, releases)
    _emit('ok' if ok else 'stale', why, None if ok else sys.stderr)
    vis = visible_skills(home)
    if vis.ok:
        _emit('ok', f'{len(vis.found)} skill(s) visible, every core skill among them')
    else:
        _emit('missing', f'{home} cannot see: {", ".join(vis.missing)}', sys.stderr)
    return EXIT_OK if ok and vis.ok else EXIT_FAILED


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='fleet-codex-skills.sh',
        description='Install or verify the superpowers skills for a codex CODEX_HOME: one symlink, '
                    '<codex-home>/skills/superpowers -> <releases>/current/skills, so a deploy moves them.')
    parser.add_argument('--codex-home', help='the CODEX_HOME to install into or verify (required)')
    parser.add_argument('--releases', help='the fleet release area (default: $FLEET_RELEASES)')
    parser.add_argument('--dry-run', action='store_true', help='say what would change; write nothing')
    parser.add_argument('--check', action='store_true', help='verify only; exit 1 when codex would not follow '
                                                             'current or cannot see a core skill')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_BAD_INPUT
    releases = args.releases or os.environ.get('FLEET_RELEASES')
    if not args.codex_home:
        _emit('bad-input', '--codex-home is required: the target is an operator\'s codex configuration, '
                           'and no default is safe to guess', sys.stderr)
        return EXIT_BAD_INPUT
    if not releases:
        _emit('bad-input', 'pass --releases, or source scripts/fleet-env.sh so FLEET_RELEASES is set',
              sys.stderr)
        return EXIT_BAD_INPUT
    home, releases = Path(args.codex_home).absolute(), Path(releases).absolute()
    if args.check:
        return _check(home, releases)

    link, target = link_path(home), expected_target(releases)
    if not os.path.isdir(target):
        _emit('refused', f'{target} is not a directory: this release area has no deployed `current` with '
                         f'skills to link to. Nothing was written.', sys.stderr)
        return EXIT_REFUSED
    if follows_current(home, releases)[0]:
        _emit('ok', f'{link} already follows {target}; nothing to do')
        return _check(home, releases) if not args.dry_run else EXIT_OK
    if os.path.islink(link) and not _ours(link):
        _emit('refused', f'{link} -> {os.readlink(link)} is a link this installer did not write (it does not '
                         f'resolve to a superpowers skills tree). Left untouched; remove it yourself if it '
                         f'should go.', sys.stderr)
        return EXIT_REFUSED
    if os.path.exists(link) and not os.path.islink(link):
        _emit('refused', f'{link} is a real directory or file. Left untouched: this installer only ever writes '
                         f'or repoints its own symlink.', sys.stderr)
        return EXIT_REFUSED

    if os.path.exists(link.parent) and not os.path.isdir(link.parent):
        _emit('refused', f'{link.parent} exists and is not a directory, so no skills link can live under it. Left '
                         f'untouched.', sys.stderr)
        return EXIT_REFUSED
    action = 'repoint' if os.path.islink(link) else 'create'
    if args.dry_run:
        _emit(f'would-{action}', f'{link} -> {target}')
        return EXIT_OK
    #: The one atomic publish in this package (`FI-20`): a reader sees the old link or the new one, never none.
    atomic_symlink(str(target), link)
    _emit(f'{action}d', f'{link} -> {target}')
    return _check(home, releases)


if __name__ == '__main__':
    raise SystemExit(main())
