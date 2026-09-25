"""Direct launch and exact-session recovery, with explicit non-secret settings."""
import os
import json
from pathlib import Path
import shlex
import uuid

from fleet.atomic import atomic_write
from fleet.codex_skills import load_instruction
from fleet.errors import BadInput, Refused
from fleet.runtime import LaunchSettings, validate_model, validate_runtime


def fleet_executable() -> str:
    return str(Path(__file__).resolve().parents[3] / 'bin/fleet')


def seed_cli_header(runtime: str = 'claude', skills=None) -> str:
    """The lines every seed starts with. A codex seed also says how to load a skill on codex (FB-111): claude gets
    that from the superpowers plugin's SessionStart hook, and codex has no hook, because the skills reach it
    through a link in CODEX_HOME rather than a plugin install. A claude seed is unchanged, byte for byte."""
    header = (f'Fleet CLI for this dispatch: {fleet_executable()}\n'
              'The launcher exports this path as FLEET_BIN. For every fleet command in the task,\n'
              'charter, or skills, invoke "$FLEET_BIN" instead of the bare fleet command.\n'
              'Login shells may put an older fleet installation first on PATH.\n\n')
    if runtime == 'codex' and skills is not None:
        header += load_instruction(skills) + '\n\n'
    return header


def model_args(settings: LaunchSettings) -> list[str]:
    """pt2. The model on the argv — `claude --model <m>`, `codex -m <m>` (both verified against the CLIs' own
    `--help`, and `codex resume` takes `-m` too) — or nothing, which leaves the CLI's configured model."""
    if not settings.model:
        return []
    return ['--model' if settings.runtime == 'claude' else '-m', validate_model(settings.model)]


#: FB-110 (operator decision D-45). Every codex worker fleet starts or resumes runs with NO approval prompts, INSIDE the
#: workspace-write sandbox, with network on — never danger-full-access, never a bypass. It goes on the argv, the one
#: layer above every config file, so the operator's CODEX_HOME config.toml is never edited and cannot loosen it.
#: Measured on codex-cli 0.156.1 (both `codex` and `codex resume` take all of these):
#:  - `-a`/`-s` are flags because clap validates their values; a mistyped `-c` key is silently ignored.
#:  - `sandbox_workspace_write.network_access` has no flag. Without it, ssh `git ls-remote` and https fail in the sandbox.
#:  - `check_for_update_on_startup=false`: the "Update available" modal otherwise stops an unattended pane before
#:    its seed lands (FB-105).
#: There is deliberately no knob. A tightening would need a consumer (a read-only worker cannot write its own instant),
#: and a loosening is the operator's decision, not a profile's.
CODEX_POLICY = ('-a', 'never', '-s', 'workspace-write',
                '-c', 'sandbox_workspace_write.network_access=true',
                '-c', 'check_for_update_on_startup=false')


def codex_policy_args(writable_dirs=()) -> list[str]:
    """The policy and the writable roots, in that order — the only place a codex argv gets either."""
    args = list(CODEX_POLICY)
    for directory in dict.fromkeys(str(d) for d in writable_dirs):
        args += ['--add-dir', directory]
    return args


def codex_policy_summary(writable_dirs=()) -> str:
    """One line for `dispatch`, `revive` and `brief`: the effective policy, as fleet puts it on the argv. RV-33: roots that
    the operator's CODEX_HOME config.toml lists under `[sandbox_workspace_write] writable_roots` still apply on top of the
    argv, and fleet does not read that file, so the line says so rather than claiming to be the whole set."""
    roots = ', '.join(['the slot (cwd)', *dict.fromkeys(str(d) for d in writable_dirs),
                       'plus any [sandbox_workspace_write] writable_roots in CODEX_HOME/config.toml'])
    return (f'approval=never sandbox=workspace-write network=on update-check=off; writable: {roots} '
            f'(argv: {" ".join(CODEX_POLICY)})')


def writable_dirs(environ) -> tuple:
    """The codex writable roots beyond the slot (the sandbox cwd): the store and the instants directory — the worker
    writes its own instant and its coordinator's proposals there. Nothing else, and nothing derived from the slot's
    contents (D-51: every rule that derived git roots from state the worker can touch was forged in review, so a
    codex worker runs only in a CLONE slot, whose repositories commit inside the cwd)."""
    return tuple(dict.fromkeys(str(Path(environ[key]).resolve()) for key in ('FLEET_HOME', 'FLEET_INSTANTS')
                               if environ.get(key)))


#: FB-117. The names codex's workspace-write sandbox protects inside EVERY writable root (measured, codex-cli 0.156.1):
#: each is bind-mounted read-only, and when it does not exist codex creates an EMPTY host directory as the mount target.
#: codex removes its targets when the sandboxed command ends cleanly; after a SIGKILL of the command's group they stay,
#: and the next clean run drops them from its registry without removing them, so they are permanent. The only codex
#: setting that avoids them grants WRITE on these names — a sandboxed worker could then create a real `.git` (config,
#: hooks) in the store or the instants tree — so fleet keeps the argv and sweeps instead (v23-n D-2).
MOUNT_RESIDUE = ('.agents', '.codex', '.git')
#: argv[0] basenames that run a codex sandbox: the TUI, its sandbox helper, and the bwrap it execs.
_CODEX_PROCESSES = ('codex', 'codex-linux-sandbox', 'bwrap')


def _names_root(argv, root) -> bool:
    """Whether a codex argv names `root` as a root: `--add-dir <root>` / `--bind <root> <root>` as a whole argument,
    or the sandbox helper's policy JSON carrying `"<root>"`."""
    quoted = json.dumps(root)
    return any(arg == root or quoted in arg for arg in argv[1:])


def codex_sandboxes_under(root, proc_root=Path('/proc')):
    """Live pids of a codex process whose argv names `root` — the only processes that can hold a protection mount
    there, or start one. None when the process table cannot be read: the caller must then keep everything."""
    root = str(Path(root).resolve())
    try:
        entries = [entry for entry in Path(proc_root).iterdir() if entry.name.isdigit()]
        init = os.path.basename(os.fsdecode((Path(proc_root) / '1' / 'cmdline').read_bytes().split(b'\0')[0]))
    except OSError:
        return None
    if init in _CODEX_PROCESSES:
        #: A caller inside a codex sandbox sees only its own PID namespace (docs/README.fleet-runtimes.md), so an
        #: empty answer there would say nothing about the codex workers outside it.
        return None
    pids = []
    for entry in entries:
        try:
            argv = [os.fsdecode(a) for a in (entry / 'cmdline').read_bytes().split(b'\0') if a]
        except OSError:
            continue                                     # exited between the listing and the read
        if not argv:
            continue
        names = [os.path.basename(argv[0])] + ([os.path.basename(argv[1])] if len(argv) > 1 else [])
        if names[0] in _CODEX_PROCESSES or names[1:] == ['codex']:
            if _names_root(argv, root):
                pids.append(int(entry.name))
    return sorted(pids)


def _not_residue(path: Path):
    """Why `path` is NOT provably codex mount residue, or None when it is: a real, empty directory that is not a mount
    point. A non-empty directory, a file, a symlink or a mount is never removed."""
    if path.is_symlink():
        return 'a symlink'
    if not path.is_dir():
        return 'not a directory'
    if os.path.ismount(path):
        return 'a mount point'
    try:
        count = len(os.listdir(path))
    except OSError as exc:
        return f'unreadable ({exc.strerror})'
    return f'not empty ({count} entries)' if count else None


def sweep_mount_residue(roots, proc_root=Path('/proc'), dry_run=False) -> list:
    """FB-117. Remove the codex mount-point residue from each writable root fleet gave a codex worker (the store and
    the instants tree). `[(path, verdict)]`, one row per candidate and one for a root with none, so an empty answer
    is never silence. A root is left alone while any codex naming it is alive, since an rmdir there would detach a
    live sandbox's protection mount — which `os.path.ismount` cannot see, being in the sandbox's namespace — so the
    census is repeated immediately before each rmdir. That narrows the race; it cannot close it. `os.rmdir` itself
    refuses a directory that gained an entry."""
    rows = []
    for root in dict.fromkeys(str(Path(r).resolve()) for r in roots):
        found = [Path(root) / name for name in MOUNT_RESIDUE if os.path.lexists(Path(root) / name)]
        if not found:
            rows.append((root, f'examined: none of {", ".join(MOUNT_RESIDUE)} present'))
            continue
        holders = codex_sandboxes_under(root, proc_root)
        if holders is None or holders:
            why = ('the process table is unreadable' if holders is None else
                   'a codex naming this root is alive (pid ' + ', '.join(map(str, holders)) + ')')
            rows += [(str(path), f'kept: {why}; swept by the next close or harvest of a codex worker')
                     for path in found]
            continue
        for path in found:
            reason = _not_residue(path)
            if reason:
                rows.append((str(path), f'kept: {reason}'))
            elif dry_run:
                rows.append((str(path), 'would remove: empty codex mount residue'))
            elif (late := codex_sandboxes_under(root, proc_root)) != []:
                #: RV-33. Asked again immediately before the rmdir: a sandbox that started after the first look has just
                #: made this directory its mount target, and the host's `os.path.ismount` cannot see a mount in the
                #: sandbox's namespace, while an rmdir there would lazily detach it.
                rows.append((str(path), 'kept: a codex naming this root started during the sweep'
                             + (f' (pid {", ".join(map(str, late))})' if late else ' (process table unreadable)')))
            else:
                try:
                    os.rmdir(path)
                    rows.append((str(path), 'removed: empty codex mount residue'))
                except OSError as exc:
                    rows.append((str(path), f'kept: {exc.strerror}'))
    return rows


def linked_worktrees(workspace) -> tuple:
    """D-51. The checkouts at the slot root or one level below whose `.git` is a FILE — a linked git worktree (ws5's shape:
    the shared checkout's repository is outside the slot). A codex worker cannot commit there, since its sandbox
    makes only the slot, the store and the instants writable, and the git roots it would need were shown forgeable (FB-110
    review). So codex dispatch, revive and resume refuse such a slot. A clone (`.git` a directory, ws8–ws10) needs nothing.
    Filesystem only, no git: a `.git` file is refused whatever it names. FAILS CLOSED (RV-52): a slot or child that
    cannot be inspected (an OSError such as an unsearchable directory) is returned too, so the caller refuses rather than
    crashes or admits."""
    slot = Path(workspace)
    try:
        candidates = [slot, *sorted(child for child in slot.iterdir() if child.is_dir())]
    except OSError:
        return (str(slot),)
    found = []
    for candidate in candidates:
        try:
            if (candidate / '.git').is_file():
                found.append(str(candidate))
        except OSError:
            found.append(str(candidate))
    return tuple(found)


def launch_argv(settings: LaunchSettings, prompt: str, writable_dirs=()) -> list[str]:
    validate_runtime(settings.runtime)
    args = [settings.executable]
    if settings.runtime == 'claude':
        args += ['--permission-mode', 'auto']
    else:
        args += codex_policy_args(writable_dirs)
    return args + model_args(settings) + ['--', prompt]


def resume_argv(settings: LaunchSettings, session_id: str, writable_dirs=()) -> list[str]:
    validate_runtime(settings.runtime)
    try:
        if str(uuid.UUID(session_id)) != session_id.lower():
            raise ValueError('not a canonical UUID')
    except (ValueError, AttributeError, TypeError) as exc:
        raise BadInput('Resume requires an explicit session UUID') from exc
    if settings.runtime == 'claude':
        return [settings.executable, '--permission-mode', 'auto', *model_args(settings), '--resume', session_id]
    return [settings.executable, 'resume', *codex_policy_args(writable_dirs), *model_args(settings), '--', session_id]


def resolve_settings(runtime, slot, environ, which, runner) -> LaunchSettings:
    validate_runtime(runtime)
    override = environ.get('FLEET_' + runtime.upper() + '_BIN')
    if runtime == 'claude':
        override = override or environ.get('REAL_CLAUDE')
    executable = which(override or runtime)
    if not executable or not os.access(executable, os.X_OK):
        raise BadInput(f'No executable for fleet runtime {runtime}')
    # Claude adopts argv[0]'s basename as comm. Resolving its executable symlink
    # changes comm to a version number and removes it from the process census.
    executable = str(Path(executable).absolute())
    # An old fleet PATH shim may recursively launch seeded workers. Reject its
    # recognizable contract; never modify the server PATH to make dispatch work.
    with open(executable, 'rb') as handle:
        prefix = handle.read(16384)
    if b'FLEET_SEED_DELIVERED' in prefix or b'seed-to-send.txt' in prefix:
        raise BadInput(f'{executable} is an old fleet shim; select the real {runtime} executable')
    if runtime == 'codex':
        config = environ.get('CODEX_HOME') or str(Path(environ.get('HOME', str(Path.home()))) / '.codex')
    else:
        resolver = Path(__file__).resolve().parents[3] / 'scripts/claude-config-dir.sh'
        code, output, error = runner(shlex.join([str(resolver), str(slot)]))
        if code:
            raise BadInput(f'Cannot resolve Claude owner for {slot}: {error.strip()}')
        config = output.strip()
    if not config or not Path(config).is_absolute() or not Path(config).is_dir():
        raise BadInput(f'Required {runtime} configuration directory is unavailable: {config!r}')
    return LaunchSettings(runtime, executable, str(Path(config).resolve()))


def prepare(settings, record, seed_path, environ, *, session_id=None) -> Path:
    child = Path(record.child_instant)
    writable = writable_dirs(environ)
    env = {key: environ[key] for key in ('FLEET_HOME', 'FLEET_INSTANTS', 'PATH') if environ.get(key)}
    env.update(FLEET_ROOT=record.root, FLEET_TMUX_SOCKET=record.tmux_socket,
               INSTANT=str(child), FLEET_INSTANT=str(child), FLEET_BIN=fleet_executable())
    env['CODEX_HOME' if settings.runtime == 'codex' else 'CLAUDE_CONFIG_DIR'] = settings.config_dir
    # Shell tools may set NO_COLOR for their own output. Native TUIs need SGR
    # attributes so pane guards can distinguish suggested text from real drafts.
    lines = ['#!/usr/bin/env bash', 'set -euo pipefail', 'unset NO_COLOR']
    lines += ['export ' + key + '=' + shlex.quote(str(value)) for key, value in env.items()]
    #: FB-110: codex too. Measured in the sandbox: GH_TOKEN reaches the shell, and without it `gh` acts as whatever
    #: account ~/.config/gh/hosts.yml names — not this root's.
    slug = Path(settings.config_dir).parent.name.removesuffix('_root')
    token_file = Path(environ.get('HOME', str(Path.home()))) / ('.gh-token-' + slug)
    lines += ['token_file=' + shlex.quote(str(token_file)),
              'if [ -r "$token_file" ]; then GH_TOKEN="$(cat -- "$token_file")"; export GH_TOKEN; fi']
    if session_id is not None:
        command = shlex.join(resume_argv(settings, session_id, writable))
    else:
        lines += ['seed_file=' + shlex.quote(str(seed_path)),
                  '[ -s "$seed_file" ] || { echo "Missing or empty fleet seed" >&2; exit 2; }']
        args = launch_argv(settings, '', writable)[:-1]
        if settings.runtime == 'claude':
            args[-1:-1] = ['--remote-control', record.tmux]
        command = shlex.join(args) + ' "$(cat -- "$seed_file")"'
    lines.append('exec ' + command)
    path = child / '.fleet' / ('resume-worker.sh' if session_id else 'launch-worker.sh')
    atomic_write(path, '\n'.join(lines) + '\n')
    return path


def session_transcript(settings, session_id, slot) -> Path:
    resume_argv(settings, session_id)  # Validate before constructing a glob.
    config = Path(settings.config_dir)
    if settings.runtime == 'codex':
        candidates = list((config / 'sessions').rglob('*-' + session_id + '.jsonl'))
    else:
        candidates = list((config / 'projects').rglob(session_id + '.jsonl'))
    if len(candidates) != 1:
        raise Refused(f'Expected one transcript for {session_id} under the recorded configuration; '
                      f'found {len(candidates)}',
                      clears_when=f'`--session-id` names a session with exactly one transcript under {config}',
                      clears_who='the caller')
    path = candidates[0]
    try:
        with path.open() as handle:
            for line in handle:
                row = json.loads(line)
                if settings.runtime == 'codex':
                    if row.get('type') != 'session_meta':
                        continue
                    data = row.get('payload', {})
                    identity = data.get('id')
                else:
                    data = row
                    identity = row.get('sessionId')
                if identity == session_id and data.get('cwd'):
                    if Path(data['cwd']).resolve() != Path(slot).resolve():
                        raise Refused('The requested transcript belongs to a different workspace',
                                      clears_when=f'`--session-id` names a session that ran in {slot}',
                                      clears_who='the caller')
                    return path
    except (OSError, ValueError, TypeError) as exc:
        raise Refused(f'Cannot verify transcript {path}: {exc}',
                      clears_when=f'{path} is readable JSON lines, or `--session-id` names another session',
                      clears_who='the operator') from exc
    raise Refused(f'Transcript {path} has no matching session/workspace metadata',
                  clears_when=f'`--session-id` names a session whose transcript records its id and cwd',
                  clears_who='the caller')
