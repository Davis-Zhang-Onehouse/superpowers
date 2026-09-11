# Fleet Runtime Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing fleet reliably with either Claude Code or Codex CLI, selected once per fleet between runs.

**Architecture:** Keep fleet's leases, roadmap, proposals, capacity rules, and tmux sessions. Isolate CLI-specific launch, process, terminal, and recovery behavior behind two built-in runtime adapters. Persist the fleet choice and serialize changes with dispatch/adoption/revival admission.

**Tech Stack:** Python standard library, Linux `/proc` and `fcntl.flock`, tmux, Bash, installed Claude Code and Codex CLI. Quorum is external evaluation tooling, not a fleet dependency.

**Spec:** `docs/superpowers/specs/2026-09-11-fleet-runtime-selection-design.md` — approved on 2026-09-11; read before executing.

## Global Constraints

- "Simple and reliably working".
- "Each CLI uses its configured model."
- "There is no runtime environment override or separate coordinator setting."
- "An absent file means `claude`, explicitly reported as the legacy default; an invalid or unreadable file is an error, never a fallback."
- "A read and a dry run leave the store unchanged."
- "Keep that lock file stable; do not unlink or steal it based on age."
- "Preserve numeric exit codes."
- "No automatic resend after ambiguous submission; inspect before retrying."
- "Use private test sockets and temporary fleet stores throughout."
- "Release readiness requires the real lifecycle evidence as well as infrastructure tests."
- No mixed-runtime scheduling, central model selection, new daemon, direct model API integration, or restoration of retired dispatch tools.
- No changes to live fleet settings, credentials, production sessions, deployment pointers, or external communications during implementation tests.
- Do not submit a PR from this plan. Submission separately requires the contributor template, duplicate search, complete human diff review, environment disclosure, and `dev` target.

---

## Execution context and file boundaries

Baseline: design commit `31f2c2b`. Preserve subsequent changes and use
`using-git-worktrees` at execution time before creating an isolated implementation
checkout. Do not automatically rebase this customized checkout onto upstream `dev`.
Commands below run from that checkout unless a working directory is stated.

| File | Responsibility |
| --- | --- |
| New `fleet/src/fleet/runtime.py` | Runtime identities, immutable launch settings, terminal observation contract, two built-in adapters. |
| New `fleet/src/fleet/runtime_config.py` | Strict saved selection and stable store/pane advisory locks. |
| New `fleet/src/fleet/runtime_launch.py` | Resolve non-secret launch settings and prepare the direct launch/resume command through injected I/O. |
| New `fleet/src/fleet/messaging.py` | Serialized, observed tmux delivery; no auto-resume and no ambiguous retry. |
| `fleet/src/fleet/session.py` | Machine probes, both-runtime census, exact tmux targets, adapter-backed observations. |
| `fleet/src/fleet/cli.py` | Compose adapters with existing handlers; register runtime/send/revive verbs. |
| `fleet/src/fleet/store.py` | Backward-readable runtime and recovery metadata on records. |
| `fleet/src/fleet/seedcheck.py` | Runtime-aware process identity while retaining existing delivery verdicts. |
| `fleet/src/fleet/peers.py` | Runtime inventory normalization followed by the existing provenance rules. |
| `fleet/src/fleet/reconcile.py`, `guards.py`, `render.py` | Consume normalized state and show recorded runtime; retain shared policies. |
| New `hooks/hooks-codex.json`, `hooks/session-start-codex` | Native Codex bootstrap for startup/resume/clear/compact. |
| `.codex-plugin/plugin.json` | Point Codex at its lifecycle configuration. |
| Active `scripts/fleet-*.sh`, `bin/fleet-view` | Delegate runtime decisions to fleet; preserve root/socket behavior. |
| `fleet/tests/test_runtime*.py`, `test_messaging.py` | Hermetic behavioral and concurrency coverage. |
| `fleet/it/fixtures/runtime/`, new `fleet/it/run-runtime.sh` | Attributed terminal frames and isolated integration coverage. |
| New `docs/README.fleet-runtimes.md` | Installation, hook trust, switch procedure, supported versions, recovery, compatibility. |

Existing suites use `unittest`, not pytest. Run a targeted fleet suite with:

```bash
PYTHONPATH=fleet/src:fleet python3 -m unittest tests.test_store -v
```

`tests.test_cli.Fleet` provides `home`, `store`, `pool`, `sessions`, `worker(...)`,
`run(argv) -> (exit_code, stdout, stderr)`, and `snapshot(path)` in that module.
Its process/session/runner objects are fakes. Extend this fixture with explicit
runtime/launch probes; never make hermetic tests invoke the installed agent CLIs.

New CLI helpers are `fleet send --id ID --message-file PATH` and
`fleet revive --id ID --session-id UUID`. They centralize the lock and observation
contracts currently spread across shell recipes. Neither creates a second
communication system. `fleet resume` keeps its existing meaning: adopt an instant.

## Execution status — 2026-09-11

Implemented in `.worktrees/fleet-runtime` on `feat/fleet-runtime-selection`. The commits include
native Codex bootstrap, saved fleet selection, direct launch, exact-session recovery, both-runtime
discovery, guarded messaging, and the six fleet skill updates. The original task checklists below
remain the implementation plan; the following evidence is the execution record.

| Area | Outcome and evidence |
| --- | --- |
| Native bootstrap and terminal fixtures | Both exact react-todo prompts triggered brainstorming before implementation; captured terminal fixtures cover both CLIs. |
| Runtime selection, locks and lifecycle | 1,849 unit tests passed before `b3516c7`; exported commit also passed all 1,849. Multiprocessing checks cover dispatch/switch and send/close serialization. |
| Dispatch, communication and harvest | Real Claude and Codex two-worker lifecycles passed, including proposals/apply and switch-back. Standard real-Claude P1–P4 passed separately. |
| Recovery and debugging | Both CLIs resumed explicit UUIDs, rejected invalid recovery, and automatically used systematic-debugging on captured failing tests. |
| Native coordinator dispatch | Codex issued the prepared dispatch itself. A sandbox-denial pending-record leak was reproduced, fixed, and the approved retry passed. |
| Skills | Twelve baseline/candidate reference sessions support the mechanism changes. External Quorum evaluation was unavailable. |
| Final integration gate | The full default batch ran on `b3516c7`: 250 passes, ten skips, and one outdated E1 timeout expectation. The corrected E1 passed its targeted 20-iteration retest; the original batch exit 1 is retained. |

The [validation report](../specs/evidence/2026-09-11-fleet-runtime-validation.md) attributes the native
runs to source revisions and records limitations. Codex CI wake is unsupported and refuses; Claude's
external watcher-positive path was not re-evaluated. Resume verifies the exact session without claiming
new seed-delivery attestation. No deployment, live-fleet migration or PR submission is part of this work.


## Task 1: Establish terminal and bootstrap evidence

**Files:** Create `fleet/it/fixtures/runtime/README.md`, frame files and
`manifest.json` in that directory; create
`docs/superpowers/specs/evidence/2026-09-11-fleet-runtime-baseline.md`.

**Interfaces:** Produces a manifest array whose entries contain `runtime`,
`cli_version`, `state`, `frame`, `columns`, `rows`, and `evidence`. States are
`idle`, `queued`, `busy`, `dialog`, and `unknown`. Frame paths are relative to the
manifest. Evidence names a retained capture/transcript and the action that produced
the state. No fabricated Codex UI strings enter the regression suite.

- [ ] Read `skills/using-git-worktrees/SKILL.md` and create the implementation checkout under the authorized workspace. Record `git rev-parse HEAD`, `claude --version`, `codex --version`, and `tmux -V` in the baseline report.
- [ ] Run the existing relevant unit baseline, preserving failures with their output:

```bash
PYTHONPATH=fleet/src:fleet python3 -m unittest tests.test_session tests.test_seedcheck tests.test_peers tests.test_store tests.test_root_resolution -v
```

- [ ] Create a dedicated test directory and a unique `itfleet-runtime-` socket. Start one CLI at a time using its existing authenticated configuration in an empty test project. Use explicit runtime-specific config paths; do not modify shell-wide `HOME` or `CODEX_HOME`. Capture only these test sessions. A capture uses:

```python
def capture_frame(run, socket, session):
    done = run(["tmux", "-L", socket, "capture-pane", "-e", "-p",
                "-t", f"={session}:"], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(done.stderr)
    return done.stdout
```

- [ ] Produce each state by a real action: a finished response for idle; literal text without Enter for queued; a small coding request for busy; an actual approval/trust screen for dialog. Capture autocomplete/suggestion, resized/padded terminal, and scrollback cases. A failed capture is separately simulated by returning `None`; an empty string is a successfully captured blank pane.
- [ ] Start a clean installed-plugin Codex session and send exactly `Let's make a react todo list`. Record whether bootstrap and brainstorming trigger, without inserting skill instructions into the test prompt. Keep the complete transcript and report failure honestly if installation alone does not bootstrap.
- [ ] Observe the CLI process ancestry, executable identity, and exact-session resume metadata for these sessions. Compare `/proc/PID/comm`, `/proc/PID/exe`, `/proc/PID/cmdline`, and pane ancestry; do not assume the Node launcher is the long-lived Codex process. Record which values are usable for positive identity.
- [ ] Commit only sanitized, reproducible test evidence and the manifest. Exclude credentials, unrelated session inventory, and full config files. If terminal state or resume identity cannot be established, record the actual limitation before continuing dependent adapter work.

## Task 2: Load the Codex bootstrap through native hooks

**Files:** Create `hooks/hooks-codex.json`, `hooks/session-start-codex`,
`tests/codex/test_session_start.py`; modify `.codex-plugin/plugin.json`,
`tests/codex/test-marketplace-manifest.sh`, and
`tests/codex/test-package-codex-plugin.sh` where they assert packaged hook content.

**Interfaces:** The manifest points to `./hooks/hooks-codex.json`. The command emits
one `SessionStart` JSON context object. It loads the checked-in bootstrap verbatim,
with a Codex-specific introduction explaining file-based skill loading.

- [ ] Add this failing subprocess test; supply the repo path from `Path(__file__).resolve().parents[2]` and use a temporary cwd containing spaces:

```python
done = subprocess.run(["bash", str(repo / "hooks/session-start-codex")],
                      cwd=other_cwd, capture_output=True, text=True, check=True)
body = json.loads(done.stdout)["hookSpecificOutput"]
self.assertEqual(body["hookEventName"], "SessionStart")
self.assertIn((repo / "skills/using-superpowers/SKILL.md").read_text(),
              body["additionalContext"])
```

- [ ] Run `python3 -m unittest discover -s tests/codex -p 'test_session_start.py' -v`; verify the missing hook fails.
- [ ] Implement the hook by deriving the plugin root from the script location, reading the bootstrap, and emitting JSON with Python's `json.dumps`. A missing bootstrap exits nonzero. Do not invoke another agent CLI from the hook. Register:

```bash
#!/usr/bin/env bash
set -euo pipefail
plugin_root="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 - "$plugin_root" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
bootstrap = (root / "skills/using-superpowers/SKILL.md").read_text()
intro = ("You have Superpowers. In Codex, load a named skill by reading its "
         "SKILL.md with the available file tools. Follow the Codex platform "
         "reference and your actual tool inventory.\n\n")
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart", "additionalContext": intro + bootstrap
}}))
PY
```

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "^(startup|resume|clear|compact)$",
      "hooks": [{
        "type": "command",
        "command": "bash \"${PLUGIN_ROOT}/hooks/session-start-codex\"",
        "async": false,
        "additionalContextLimit": 0
      }]
    }]
  }
}
```

Codex's official [hooks documentation](https://learn.chatgpt.com/docs/hooks)
documents this manifest path mechanism, plugin-root variable, context output, and
session sources. Hook definitions require trust during setup; do not add a trust
bypass to worker launch. These are documented capabilities, not proof the local
integration passes. Retain the existing Claude/Cursor hook behavior.

- [ ] Run the new test plus `bash tests/hooks/test-session-start.sh`, `bash tests/codex/test-marketplace-manifest.sh`, and `bash tests/codex/test-package-codex-plugin.sh`.
- [ ] Install the candidate through the native plugin mechanism in the test configuration, review its hook definition, and repeat Task 1's exact prompt. Then test resume and compaction. Capture the bootstrap context and skill invocation, not just a plausible final answer.
- [ ] Commit as `feat: bootstrap fleet skills in Codex sessions`.

## Task 3: Define the runtime observation boundary

**Files:** Create `fleet/src/fleet/runtime.py`, `fleet/tests/test_runtime.py`;
modify `fleet/src/fleet/session.py`, `fleet/tests/test_session.py`, and
`fleet/tests/test_structure.py`.

**Interfaces:** Define the following types and functions in `runtime.py`:

```python
from dataclasses import dataclass
from typing import Literal

RuntimeName = Literal["claude", "codex"]
PaneState = Literal["idle", "queued", "busy", "dialog", "unknown"]

@dataclass(frozen=True)
class PaneObservation:
    state: PaneState
    draft: str | None = None
    watcher: str = ""

```

Implement `validate_runtime(value: str) -> RuntimeName`,
`observe(runtime: RuntimeName, frame: str) -> PaneObservation`, and
`recognizes_process(runtime: RuntimeName, comm: str, executable: str, argv: list[str]) -> bool`.
`SessionLayer(probes, runtime="claude")` adds `observe(name)` and
`is_agent_process(name)` while keeping existing methods for callers during migration.

- [ ] Write the frame-manifest regression test:

```python
for case in manifest:
    with self.subTest(runtime=case["runtime"], frame=case["frame"]):
        frame = (fixture_dir / case["frame"]).read_text()
        actual = observe(case["runtime"], frame)
        self.assertEqual(actual.state, case["state"])
```

- [ ] Run `PYTHONPATH=fleet/src:fleet python3 -m unittest tests.test_runtime -v`; expect failure because the boundary is missing.
- [ ] Move Claude terminal predicates behind `observe`, preserving their real-frame regression behavior. Implement Codex predicates from Task 1's captured structure. A current prompt plus positive runtime chrome can establish idle; an absent busy marker alone cannot. `dialog` and unfamiliar layouts are never idle. Watcher text is empty unless runtime evidence proves a wakeup-capable watcher.
- [ ] Add negative process tests using a shell or Node process whose argv merely quotes `codex`, and a worker's descendant shell carrying a long prompt. Use the executable/ancestry evidence from Task 1 for Codex identity. Keep Claude's positive-process tests.
- [ ] Make `validate_runtime` reject non-string values as `BadInput`, including JSON arrays, objects, null, and booleans; do not let a set-membership `TypeError` escape through config loading.
- [ ] Introduce adapter delegation in `SessionLayer`; remove its assumption that any runtime process is Claude. Update `test_structure.py` explicitly: `runtime` is a leaf importing only primitives; `session` now depends on it. Keep the import-cycle test and do not weaken unrelated structure assertions.
- [ ] Run `tests.test_runtime`, `tests.test_session`, and `tests.test_structure`; commit as `refactor: isolate fleet runtime observations`.

## Task 4: Persist the runtime and serialize admission

**Files:** Create `fleet/src/fleet/runtime_config.py`,
`fleet/tests/test_runtime_config.py`; modify `fleet/src/fleet/store.py` and
`fleet/tests/test_store.py`. Do not expose the setting CLI until Task 8.

**Interfaces:** `read_runtime(home: Path) -> tuple[RuntimeName, str]` returns runtime
and `saved`/`legacy-default`; `write_runtime(home: Path, name: RuntimeName) -> None`
is called only under admission lock. `admission_lock(home: Path, timeout_s=5.0)`
and `pane_lock(home: Path, socket: str, session: str, timeout_s=5.0)` are context
managers. Pane lock filenames use a hash of the socket/session tuple.

- [ ] Write tests for absent config without directory creation, corrupt JSON, non-object payloads, unknown version/runtime/keys, and round-trip persistence. Assert invalid data is never read as Claude:

```python
home.mkdir()
(home / "runtime.json").write_text('{"schema_version":1,"runtime":"typo"}')
with self.assertRaises(BadInput):
    read_runtime(home)
```

- [ ] Run `PYTHONPATH=fleet/src:fleet python3 -m unittest tests.test_runtime_config -v` and confirm failure.
- [ ] Implement strict JSON parsing and the exact spec schema using `atomic_write`. Implement bounded `LOCK_EX | LOCK_NB` acquisition on a stable file, a monotonic deadline, and release in `finally`. Do not use `atomic.held_for_update`, whose stale-lock policy is for short file updates. Read-only and dry-run handlers never acquire a creating lock.

The strict read has this shape; import `json`, `BadInput`, and `validate_runtime`
from their owning modules:

```python
def read_runtime(home):
    path = home / "runtime.json"
    try:
        raw = path.read_text()
    except FileNotFoundError:
        if path.is_symlink():
            raise BadInput(f"Broken runtime configuration link at {path}")
        return "claude", "legacy-default"
    except OSError as exc:
        raise BadInput(f"Cannot read {path}: {exc}") from exc
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise BadInput(f"Invalid runtime JSON at {path}: {exc}") from exc
    if (not isinstance(body, dict)
            or set(body) != {"schema_version", "runtime"}
            or type(body["schema_version"]) is not int
            or body["schema_version"] != 1):
        raise BadInput(f"Unsupported runtime configuration at {path}")
    return validate_runtime(body["runtime"]), "saved"
```

Use the following bounded acquisition inside the context manager, after creating
the parent for a real mutation. Import `fcntl`, `time`, and `Refused`. The outer
`with` closes the descriptor on every error; it must never unlink the file:

```python
with lock_path.open("a+") as handle:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise Refused(f"Another operation holds {lock_path}; retry when it finishes")
            time.sleep(0.02)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
```
- [ ] Test the lock in separate processes: contender times out while the holder lives; killing the holder releases it; the same inode remains. Synchronize with pipes/events, not sleeps chosen to win races. Test separate roots and separate panes do not block each other.
- [ ] Add defaulted `Record.runtime="claude"`, `Record.runtime_executable=""`, and `Record.runtime_config_dir=""`. These last two are non-secret recovery settings, not copied config contents. Reject an unknown runtime in `from_json`; old records lacking all three fields remain readable. Do not increase the existing record schema merely to add defaulted fields.
- [ ] Run `tests.test_runtime_config`, `tests.test_store`, and `tests.test_atomic`; commit as `feat: persist fleet runtime and lock admission`.

## Task 5: Discover both runtimes and normalize peer inventory

**Files:** Modify `fleet/src/fleet/session.py`, `fleet/src/fleet/peers.py`,
`fleet/src/fleet/reconcile.py`, `fleet/src/fleet/cli.py`,
`fleet/tests/test_session.py`, `fleet/tests/test_peers.py`,
`fleet/tests/test_reconcile.py`, and `fleet/tests/test_cli.py`.

**Interfaces:** Append `runtime: str = "claude"` to `LiveSession` for existing
fixtures. `default_probes` gains an explicit both-runtime discovery mode;
`SessionLayer.live()` never silently hides the other CLI in that mode.
Add `peers.from_live_sessions(live, observe) -> list[dict]` to produce validated
rows for Codex. Rows carry `runtime`, `pid`, `cwd`, `name`, `status`, `tmux`, and
`tmux_socket`; a tmux address is not mislabeled as a native agent session UUID.

- [ ] Add a session fixture containing one Claude worker, one Codex worker in an enrolled slot, and an unrelated Node process. Assert the first two are discovered and the third is excluded. Inject a failed process census and assert it raises an attention/refusal result, not an empty success.
- [ ] Run the three targeted unit modules and confirm the new cases fail.
- [ ] Implement one process census using Task 3 identity checks and existing exact tmux attribution. Distinguish a successful empty census from unreadable probes. Preserve process-first discovery of unclaimed workers and full cwd information.
- [ ] Keep Claude's native inventory path for existing callers. Use the observed process/tmux rows for Codex instead of guessing that `codex agents` has Claude's JSON schema. Pass both through existing provenance validation and lease classification. Unknown ancestry/address/socket remains unaddressable. Add tests:

```python
results = peers.classify(rows, leases, self_pid=coordinator_pid,
                         proc_root=str(fake_proc))
self.assertEqual(results[0]["verdict"], peers.OURS)
```

`classify` returns a list of dictionaries, so the existing `verdict` accessor above
is the required assertion. Extend its output mappings to preserve runtime and
address transport; retain the existing eight porcelain columns, with transport and
socket details on human output and `fleet status`.

- [ ] Add regressions for closed lease, reused slot, stale PID, wrong cwd, other socket/root, missing native session ID, and failed inventory. Codex peer output identifies tmux as its address transport; native `SendMessage` names are never invented.
- [ ] Include the other runtime's process rows in ownership checks regardless of the saved selection, so a Claude-native inventory cannot hide a Codex co-tenant in the same slot. Require the row's runtime/socket to match the dispatch record before marking it addressable. Preserve the classifier's duplicate-row refusal; do not deduplicate ambiguous rows into an apparent single owner.
- [ ] Change `Ctx.sessions_for(record)` and `layer_for` composition to select both recorded socket and runtime. Update fake factories alongside production. Include runtime in status evidence and preserve existing porcelain columns where downstream scripts expect them.
- [ ] Run `tests.test_session`, `tests.test_peers`, `tests.test_reconcile`, and `tests.test_cli`; commit as `feat: discover Codex workers and fleet peers`.

## Task 6: Make dispatch own launch and seed delivery

**Files:** Create `fleet/src/fleet/runtime_launch.py`,
`fleet/tests/test_runtime_launch.py`; modify `fleet/src/fleet/cli.py`,
`fleet/src/fleet/session.py`, `fleet/src/fleet/seedcheck.py`,
`fleet/tests/test_cli.py`, `fleet/tests/test_concurrency.py`,
`fleet/tests/test_seedcheck.py`, `fleet/it/bin/claude`, and the stub setup in
`fleet/it/lib.sh`.

**Interfaces:** In `runtime.py`, add:

```python
@dataclass(frozen=True)
class LaunchSettings:
    runtime: RuntimeName
    executable: str
    config_dir: str

```

Implement `launch_argv(settings: LaunchSettings, prompt: str, writable_dirs: tuple[str, ...] = ()) -> list[str]`
and `resume_argv(settings: LaunchSettings, session_id: str, writable_dirs: tuple[str, ...] = ()) -> list[str]`.
`runtime_launch.resolve_settings(runtime, slot, environ, which, run) -> LaunchSettings`
resolves the executable/config through injected helpers.
`runtime_launch.prepare(settings, record, seed_path, environ) -> Path` writes the
worker's uniquely located launcher. It uses non-secret paths and reads any existing
operator token file at execution time. It is never named `claude` or `codex`.

- [ ] Add argv round-trip tests, including a prompt containing quotes, newlines, backticks, and `$()`:

```python
prompt = "line one\n'quoted' `literal` $(literal)"
argv = launch_argv(LaunchSettings("codex", "/opt/bin/codex", "/cfg"), prompt)
self.assertEqual(argv[-1], prompt)
self.assertEqual(shlex.split(shlex.join(argv)), argv)
self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
```

- [ ] Run `tests.test_runtime_launch` and confirm missing implementation fails.
- [ ] Build direct launch/resume argv using CLI help and Task 1 evidence. Codex gets explicit config and the additional writable paths its fleet role needs; do not inject a model flag. Resolve Claude config with the existing `claude-config-dir.sh` runner and preserve owner/token-file behavior. Honor existing executable overrides; add `FLEET_CODEX_BIN` only as an executable-path override, not a runtime selector. Reject a detected old fleet shim rather than recursively selecting it.

Keep the command builder pure. Configuration environment is applied by `prepare`,
not hidden in a shell string returned by this function:

```python
def launch_argv(settings, prompt, writable_dirs=()):
    validate_runtime(settings.runtime)
    argv = [settings.executable]
    if settings.runtime == "codex":
        for path in writable_dirs:
            argv.extend(["--add-dir", path])
    else:
        argv.extend(["--permission-mode", "auto"])
    argv.extend(["--", prompt])
    return argv

def resume_argv(settings, session_id, writable_dirs=()):
    validate_runtime(settings.runtime)
    if not session_id or session_id.startswith("-"):
        raise BadInput("Resume requires an explicit session identifier")
    if settings.runtime == "claude":
        return [settings.executable, "--permission-mode", "auto", "--resume", session_id]
    argv = [settings.executable, "resume"]
    for path in writable_dirs:
        argv.extend(["--add-dir", path])
    return argv + ["--", session_id]
```

Verify the `--` terminator on both installed CLIs in Task 1 before adopting these
builders; use the measured positional parsing if a CLI rejects it. Preserve existing
Claude remote-control naming when composing its final launch settings, with the
same exact tmux session name. No Codex remote-control feature is required here.
- [ ] Generate the launcher under the child instant's `.fleet/` directory. Quote each path/argument using `shlex.quote`; read the seed file into one argument when launching. Never write credential values into the launcher or tmux command. Export resolved root/store/socket/instant/config paths explicitly rather than inheriting them from the tmux server. If the seed is absent/empty, exit; do not fall back to an unbriefed interactive agent.
- [ ] Inside `_do_dispatch`, acquire admission lock, reread the selection, resolve settings, apply existing gates, render seed and persist metadata, then start the exact launcher path. Ensure exception rollback retains leases until the launched process exits, and records attention if cleanup cannot be confirmed. Do not release a slot merely because `kill-session` returned success.
- [ ] Extend `seedcheck.Probes` with an explicit worker-identity callback while retaining current required `comm_of` compatibility. Use runtime/executable evidence to inspect the agent process and bounded descendant traversal. Test actual worker seed, a shell descendant with a foreign long argv, failed `/proc`, startup delay, foreign seed, and resumed attestation. Mark launch ready only after verified/attested delivery; a timeout remains attention and never a ready verdict.
- [ ] Update hermetic launch probes to simulate executable/config and seed evidence. Replace IT stubs that only `exec sleep` with a stub that records delivered prompt evidence and stays alive; label the result as attested, never pretend the stub is a real agent process. Real-agent identity remains covered by the live gate.
- [ ] Run `tests.test_runtime_launch`, `tests.test_seedcheck`, `tests.test_cli`, and `tests.test_concurrency`; commit as `feat: launch fleet workers with the selected runtime`.

## Task 7: Centralize guarded messaging

**Files:** Create `fleet/src/fleet/messaging.py`, `fleet/tests/test_messaging.py`;
modify `fleet/src/fleet/session.py`, `fleet/src/fleet/cli.py`, `fleet/tests/test_cli.py`.

**Interfaces:** Add injected `send_literal(name, text)` and `submit(name)` probes,
implemented only in `default_probes` using exact tmux pane targets. Expose matching
methods on `SessionLayer`.
`messaging.send(home, sessions, record, text, *, timeout_s=10.0) -> str` returns
`submitted` only after a single submission and observed consumption; otherwise it
raises `Refused` before insertion or an attention error after ambiguous delivery.

- [ ] Test that queued/busy/dialog/unknown initial state sends nothing; idle → exact queued draft → busy sends literal text once and Enter once. A competing draft is never submitted. Use these explicit transition assertions:

```python
self.assertEqual(events, [("literal", message), ("submit", None)])
self.assertEqual(result, "submitted")
```

- [ ] Run `tests.test_messaging`; expect the missing module to fail.
- [ ] Implement per-pane locking and an idle recheck after acquiring it. During insertion, wait for the observed draft to match this message before sending Enter. Reject empty messages and terminal control characters; allow ordinary multiline text through literal/bracketed-paste behavior verified in Task 1. Bound each wait with a monotonic deadline. If capture fails after insertion or submission, report delivery as uncertain and never resend automatically.

Use a small shared poll helper inside `messaging.py`; callers supply the condition
and the specific pre-send refusal or post-send attention error. Inject clock and
sleep in unit tests, so timeout cases require no wall-clock delay:

```python
def wait_for(read, accept, timeout_s, clock, sleep, timeout_error):
    deadline = clock() + timeout_s
    while True:
        observation = read()
        if accept(observation):
            return observation
        if clock() >= deadline:
            raise timeout_error
        sleep(0.02)
```

Do not suppress a failed `read`. After literal insertion, match only the current
draft. After Enter, accept busy or a verified consumed input; disappearance of a pane
or failed observation is not consumption. This helper waits on a condition, not a
fixed post-insertion delay.
- [ ] Register `fleet send --id ID --message-file PATH --dry-run`. Resolve an open record and its actual lease/runtime/socket; refuse a closed/harvested subject, unknown session, or runtime mismatch. Dry run reads/validates but acquires no creating lock and types nothing. Use the existing `Refused`/attention exit categories.
- [ ] Add the new verb to the shared CLI test argument table so generic missing-value, dry-run, porcelain, and cadence tests execute its admissible path. Repeat this table update when registering runtime and revive in Tasks 8 and 9.
- [ ] Test two concurrent senders against one pane and a simultaneous close. Close/harvest must acquire the same pane lock and recheck state before termination. Test different panes do not serialize. Native runtime messaging APIs remain outside this helper.
- [ ] Run `tests.test_messaging` and `tests.test_cli`; commit as `feat: send fleet messages through guarded tmux delivery`.

## Task 8: Expose safe switching and complete lifecycle guards

**Files:** Create `fleet/tests/test_runtime_cli.py`;
modify `fleet/src/fleet/cli.py`, `fleet/src/fleet/reconcile.py`,
`fleet/src/fleet/guards.py`, `fleet/src/fleet/render.py`,
`fleet/tests/test_cli.py`, `fleet/tests/test_concurrency.py`,
`fleet/tests/test_guards.py`, `fleet/tests/test_reconcile.py`.

**Interfaces:** Register `_do_runtime` with optional `--set claude|codex` plus
standard flags. Implement `runtime_blockers(ctx) -> list[str]` in `cli.py` using
records, pool, and both-runtime observations. Human/porcelain output includes
`runtime`, `source`, and `home` fields. Read-only runtime mode is handled explicitly
even though the same verb has a mutating option.

- [ ] Add a real CLI fixture test for a saved selection blocked by a live worker:

```python
f = Fleet()
self.addCleanup(shutil.rmtree, f.tmp)
f.worker("active", slot="ws1")
before = snapshot(f.home)
code, out, err = f.run(["runtime", "--set", "codex"])
self.assertEqual(code, 4)
self.assertEqual(snapshot(f.home), before)
```

Because acquiring an advisory lock may create its stable file, initialize the lock
before taking this refusal snapshot. Separately assert that read/dry-run paths do
not create the lock. A refusal must preserve runtime, records, and leases; only the
first real mutation may initialize lock infrastructure.

- [ ] Run `tests.test_runtime_cli` and confirm the missing verb fails.
- [ ] Implement setting changes under admission lock, rereading current state there. Check every unharvested record, held/interrupted lease, and live in-scope agent. Preserve the current choice on refusal. Same-choice calls are no-ops even with work present. Foreign fleet sessions are not blockers. Unknown process/capture evidence blocks instead of proving emptiness.
- [ ] Wrap adoption in the same admission lock. If adopted evidence identifies a runtime that differs from the selection, refuse. For old records, use documented Claude compatibility; never relabel a live Codex process as Claude to make adoption succeed.
- [ ] Route pane-guard, awaiting-CI watcher gates, close/abort/harvest, reconcile, and pool release through the selected/recorded adapter. A known agent with an unfamiliar frame yields code 14; it cannot yield 12. Keep legacy numeric and porcelain compatibility. Codex watcher absence keeps capacity occupied; no fake background-shell evidence.
- [ ] Add multiprocessing race tests with explicit barriers for switch versus dispatch/adopt and stopped holders. Assert that launch uses the saved runtime or switching refuses; neither ordering creates mismatched ownership. Add a root-isolation test and a dry-run filesystem/mtime test for every new mutating command.
- [ ] Run `tests.test_runtime_cli`, `tests.test_concurrency`, `tests.test_guards`, `tests.test_reconcile`, and `tests.test_cli`; commit as `feat: switch fleet runtimes only between completed runs`.

## Task 9: Resume exact sessions and retire active shim assumptions

**Files:** Modify `fleet/src/fleet/runtime_launch.py`, `fleet/src/fleet/cli.py`,
`scripts/fleet-revive.sh`, `scripts/fleet-dispatch-launcher.sh`,
`scripts/fleet-env.sh`, `scripts/fleet-finished-pids.sh`, `bin/fleet-view`;
create `fleet/tests/test_runtime_revival.py`,
`scripts/tests/fleet-runtime-helpers.sh`; modify existing script tests.

**Interfaces:** `fleet revive --id ID --session-id UUID [--dry-run]` resolves
recorded launch settings and builds `resume_argv` from Task 6. Runtime-specific
transcript discovery only proposes candidates; the explicit UUID remains required.

- [ ] Add tests that a recorded Codex session resumes with `codex resume UUID`,
   not `--last`; a Claude record resumes with `claude --resume UUID`. Verify a
   session ID beginning with `-`, a wrong config directory, a mismatched runtime,
   an occupied pane, and a harvested/closed lease all refuse without launching:

```python
argv = resume_argv(LaunchSettings("codex", "/opt/bin/codex", "/cfg"),
                   "12345678-1234-1234-1234-123456789abc")
self.assertIn("resume", argv)
self.assertIn("12345678-1234-1234-1234-123456789abc", argv)
self.assertNotIn("--last", argv)
```

- [ ] Run `tests.test_runtime_revival` and confirm missing behavior fails.
- [ ] Implement revival under admission lock and pane lock, in that order. Check current selection against the record; use its recorded config/executable/socket/slot. Legacy records without config metadata require the existing explicit resolution procedure and a visible explanation. Do not silently choose a global newest transcript or restart fresh when resume fails.
- [ ] Retain the script's `plan`, `transcripts`, `launcher`, and `start` entry points as compatibility wrappers. Generated revival launchers delegate to `fleet revive`, so the lock is acquired at actual start. `plan` is read-only. `transcripts` uses Task 1's verified runtime-specific metadata and never supplies a guessed session UUID.
- [ ] Remove active call sites requiring a PATH shim and post-dispatch seed handoff. The old dispatch-launcher helper reports that dispatch now owns launch instead of generating a stale executable alias. Audit and update its current documented callers; historical plans stay historical.
- [ ] `fleet-view` and `fleet_peek` display both runtimes from shared fleet results. Keep `fleet-finished-pids.sh`'s Claude watchdog contract explicitly filtered to Claude, so adding Codex discovery cannot silently broaden watchdog actions. Leave `skills/dispatchInstants` retired.
- [ ] Run `tests.test_runtime_revival`, `tests.test_runtime_launch`, `tests.test_cli`, and each `scripts/tests/fleet-*.sh` test, including the new helper test. Commit as `feat: recover Codex fleet sessions with recorded provenance`.

## Task 10: Update skills with before/after behavioral evidence

**Files:** Modify `skills/using-fleet/SKILL.md`,
`skills/coordinating-instants/SKILL.md`,
`skills/working-as-a-dispatched-instant/SKILL.md`,
`skills/dispatching-a-wave/SKILL.md`,
`skills/harvesting-an-instant/SKILL.md`,
`skills/reviving-dead-panes/SKILL.md`, and their active umbrella callers only where
the runtime mechanism changed. Create `docs/README.fleet-runtimes.md` and
`docs/superpowers/specs/evidence/2026-09-11-fleet-runtime-evals.md`.

**Interfaces:** Skills invoke the shared runtime/send/revive CLI contracts; the
operator guide supplies the one-time CLI/plugin/hook setup and switch procedure.
Systematic debugging retains its existing evidence law and phase requirements.

- [ ] Read `skills/writing-skills/SKILL.md` before modifying skill instructions. Capture baseline behavior before the edits; use the approved implementation checkout with the original skills for comparison, not the operator's production installation.
- [ ] Prepare the separate eval checkout. The repository named in the contributor instructions was inspected at `ccb85dab7d95bd3f6cec3beaf0993b6191641426`; it currently uses Quorum/Bun rather than the older Drill commands. Its README and `docs/scenario-authoring.md` define the current scenario/run interfaces. Do not vendor it or its dependencies into fleet.

```bash
git clone https://github.com/prime-radiant-inc/superpowers-evals.git evals
git -C evals checkout ccb85dab7d95bd3f6cec3beaf0993b6191641426
```

Use an existing checkout if present instead of replacing it. Run in `evals/`:

```bash
bun install
bun run quorum check
bun run quorum run scenarios/superpowers-bootstrap --coding-agent codex
bun run quorum run scenarios/conversation-debugging --coding-agent codex
bun run quorum run scenarios/superpowers-bootstrap --coding-agent claude
bun run quorum run scenarios/conversation-debugging --coding-agent claude
```

Set `SUPERPOWERS_ROOT` to the exact implementation checkout before running. Live
evals use the external lab's configured execution environment and credentials;
read its runbook and use its isolated test environment. Report missing credentials
or unavailable test infrastructure rather than claiming an eval passed. Do not
change fleet's production sandbox policy to match an eval runner.

- [ ] Run at least three independent sessions per runtime for these fleet pressure cases: "send immediately" while input is queued; "harvest now" while a completed worker remains mid-turn; "switch to Codex now" while a crashed worker holds a lease. The expected actions are inspect/wait/refuse, preserving the lease and draft. Keep prompts, complete transcripts, commands, versions, and artifact paths for baseline and candidate.
- [ ] Replace direct tmux send recipes with `fleet send`; describe runtime-neutral pane codes and verified watcher behavior. Replace native Claude-only peer messaging advice with the runtime's exposed address transport. Point revival to the exact-session helper. Restrict terminology changes to sentences whose mechanism changed; preserve tuned tables and "human partner" wording unless an eval demonstrates a needed correction.
- [ ] The operator guide shows `fleet runtime`, `fleet runtime --set codex`, ordinary dispatch, completion/harvest, stopping the coordinator, and switching back. Explain normal-shell switching and manually starting the matching coordinator. Record only tested CLI versions, installation/hook trust steps, refusal remedies, and old-binary/new-record incompatibility.
- [ ] Repeat the same finite eval matrix against the candidate. In the report, distinguish infrastructure failures, behavioral failures, and passes. Capture the exact react-todo bootstrap transcript separately because another scenario's pass does not replace the repository's exact acceptance prompt.
- [ ] Commit as `docs: teach fleet workflows for Claude and Codex` only after the required behavior evidence supports the edits.

## Task 11: Validate the complete lifecycle and switch-back

**Files:** Create `fleet/it/run-runtime.sh` and
`docs/superpowers/specs/evidence/2026-09-11-fleet-runtime-validation.md`;
modify `fleet/it/run-all.sh` and `fleet/src/fleet/release_verify.py` only as needed
to register deterministic coverage without silently enabling paid live evals.

**Interfaces:** `run-runtime.sh --stubs` is repeatable infrastructure coverage;
`run-runtime.sh --live --runtime claude|codex` runs explicitly selected real-CLI
coverage. It uses `fleet/it/lib.sh` isolation assertions and records the tested tree
and versions. No default invocation launches a real model.

- [ ] Add the deterministic runner's red assertions for command parsing, both-runtime records, failed launch cleanup, switch refusal, and close/send locking. Use fake binaries with attributed delivery evidence, not the real CLI on PATH. Verify the runner refuses an absent/private-socket violation before any tmux command.
- [ ] Implement the runner with the same isolation contract as existing `run-R.sh` and `run-S.sh`, explicit case ownership, and results schema. Add stub execution to the default IT roster; keep live mode opt-in. An assertion against stub process identity is not a substitute for the real-session gate.
- [ ] Run all fleet unit tests:

```bash
PYTHONPATH=fleet/src:fleet python3 -m unittest discover -s fleet/tests -t fleet -v
bash fleet/it/run-runtime.sh --stubs
bash fleet/it/run-all.sh
bash tests/hooks/test-session-start.sh
bash tests/codex/test-marketplace-manifest.sh
bash tests/codex/test-package-codex-plugin.sh
bash tests/systematic-debugging/test-find-polluter.sh
```

- [ ] Execute the following real lifecycle for each runtime in its private test root: bootstrap a coordinator; create two milestones and dispatch two workers into distinct slots; verify cap refusal for excess active work; send a message and capture its reply; submit/apply attributed proposals; diagnose a seeded failing test using captured artifacts; verify completion/review guards; close and harvest each worker only after process exit.
- [ ] Test watcher behavior independently from capacity: prove a real completion wakes the worker before accepting the watcher-positive case. If Codex lacks that mechanism, prove `awaiting-ci` is refused and the slot still counts, and document that supported fallback. A sleeping shell is not a watcher-positive test.
- [ ] Kill one test worker mid-effort, retain its lease, revive its exact session, and complete it. Repeat with an invalid session ID and confirm no fresh worker or wrong transcript is silently selected. Confirm completed history is still readable.
- [ ] Close out the Claude test run, switch the same test store to Codex, perform the workflow, and switch back. Attempt an early switch with one worker unfinished and prove refusal without changing the stored runtime. Check no slot is released twice and no retired worker is reawakened by messaging.
- [ ] Write the validation report with exact commands, outcomes, tree revision, CLI/plugin versions, sanitized transcripts, and remaining limitations. Failed or unavailable live gates mean the feature is not release-ready. Commit tests and evidence as `test: verify fleet lifecycle across Claude and Codex`.

## Final review and handoff

- [ ] Run `git diff --check` and inspect the full diff. Confirm each spec requirement maps to the tasks below and no unrelated skill prose, production config, generated credentials, or eval dependency was added.
- [ ] Report implementation status and validation honestly. Do not deploy, open a PR, or claim full support solely because the settings command and unit tests pass.

| Spec requirement | Tasks |
| --- | --- |
| One saved selection, legacy default, strict errors, read/dry-run behavior | 4, 8 |
| Between-run switching and admission races | 4, 6, 8, 9, 11 |
| Runtime metadata and old-record compatibility | 4, 5, 9, 10 |
| Direct launch, configuration ownership, seed integrity | 1, 3, 6 |
| Cross-process discovery and guarded messaging | 3, 5, 7 |
| Capacity, watcher evidence, close/harvest safety | 3, 7, 8, 11 |
| Exact-session recovery and active fleet helpers | 1, 6, 9 |
| Automatic bootstrap and skill behavior, including debugging | 1, 2, 10, 11 |
| Private test isolation and switch-back acceptance | 1, 11 |
