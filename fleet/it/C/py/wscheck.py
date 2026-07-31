"""§C9 / §C11 / §C12 / §C13 — `fleet.workspace` against real directories and a real git.

None of these three concerns has a verb. `isolate_build_cache`'s only caller is inside `_do_dispatch`,
past the point a `dt-` session is started, and `base_check` and `golden()` have no caller at all outside
`set-golden`'s own re-read. So they are called directly, with `workspace.default_git()` — the module's
real subprocess runner — and every observation printed comes from the product, not from this file.

Each subcommand prints its raw observations and then exactly one `VERDICT:` line, and exits 0/1. The
observations are the evidence; the verdict is the assertion. A summary line never contains an absolute
path, because it is quoted into a results-file note and `bin/lint-evidence-paths.sh` rejects those.
"""
import sys
from pathlib import Path

from fleet.errors import BadInput
from fleet.workspace import GOLDEN_FILE, REPO_LOCAL, Workspace, default_git

OUT = []


def obs(text):
    OUT.append(str(text))
    print(text)


def check(ok, label):
    obs(f"{'ok  ' if ok else 'BAD '} {label}")
    return bool(ok)


def c9(home, dummy):
    """`golden` unset ⇒ BadInput(2) naming a verb that EXISTS, with both controls."""
    from fleet import cli

    home, dummy = Path(home), Path(dummy)
    good = True
    workspace = Workspace(home)
    obs(f"golden file: {home / GOLDEN_FILE} exists={(home / GOLDEN_FILE).exists()}")
    try:
        value = workspace.golden()
        good = check(False, f"golden() returned {value} with nothing declared")
        message, code = "", None
    except BadInput as exc:
        message, code = str(exc), exc.exit_code
        obs(f"--- unset golden raised {type(exc).__name__} exit_code={code} ---")
        obs(message)
    good &= check(code == 2, f"the unset golden's exit code is 2 (got {code})")
    good &= check("no golden workspace is declared" in message, "the message says the golden is unset")
    good &= check("fleet set-golden --path" in message, "the message NAMES THE FIX as a command")
    good &= check("set-golden" in cli.VERBS, "the verb the message prescribes is a declared verb (FI-19a)")
    good &= check(str(home / GOLDEN_FILE) in message, "the message names the file it looked in")
    good &= check("fleet golden" not in message, "the message does not prescribe the verb that never existed")

    # POSITIVE CONTROL. Without it, "raises BadInput" would also pass for a golden() that always raises.
    workspace.set_golden(dummy)
    fresh = Workspace(home).golden()                # a FRESH consumer, not the writer's return value
    good &= check(fresh == dummy, f"after set_golden a fresh consumer reads it back (got {fresh.name})")

    # And the value, not the file's existence, is what governs.
    (home / GOLDEN_FILE).write_text("\n")
    try:
        Workspace(home).golden()
        good &= check(False, "an EMPTY golden file was accepted as a declaration")
    except BadInput as exc:
        good &= check(exc.exit_code == 2, "an empty golden file is exit 2, not a silent empty path")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} unset golden is BadInput/2 naming `fleet set-golden "
          f"--path`; a set golden reads back; an empty file is still unset")
    return 0 if good else 1


def c11(slot):
    """The config must name the POPULATED `.m2-old`, not the empty `.m2` that sorts first."""
    slot = Path(slot)
    workspace = Workspace(slot.parent)
    populated, empty = slot / ".m2-old", slot / ".m2"
    obs(f"before: .m2 exists={empty.is_dir()} jars={len(list(empty.rglob('*.jar')))} · "
        f".m2-old exists={populated.is_dir()} jars={len(list(populated.rglob('*.jar')))}")
    good = check(empty.is_dir() and not list(empty.rglob("*.jar")),
                 "the DECOY empty .m2 exists and sorts first, so `.m2*` alone cannot pick the right one")
    good &= check(populated.is_dir() and list(populated.rglob("*.jar")),
                  "the .m2-old the product must choose is populated")

    written = workspace.isolate_build_cache(slot)
    obs(f"isolate_build_cache wrote {len(written)} config(s): "
        f"{', '.join(str(p.relative_to(slot)) for p in written)}")
    want = f"{REPO_LOCAL}{populated}"
    good &= check(len(written) == 2, f"one .mvn/maven.config per pom at depth<=2 (got {len(written)})")
    for config in written:
        text = config.read_text()
        obs(f"--- {config.relative_to(slot)} ---\n{text.rstrip()}")
        good &= check(text.strip() == want,
                      f"{config.relative_to(slot)} names the populated cache and nothing else")
        good &= check(f"{REPO_LOCAL}{empty}\n" not in text,
                      f"{config.relative_to(slot)} does NOT name the empty .m2")
    good &= check(populated.is_dir(), "the target the config names EXISTS (OI-6: a cold cache is a failure)")
    caches = sorted(d.name for d in slot.glob(".m2*") if d.is_dir())
    good &= check(caches == [".m2", ".m2-old"], f"no third cache directory was invented (found {caches})")

    again = workspace.isolate_build_cache(slot)     # idempotent: never a stacked second line
    good &= check(again == [], f"a second call writes nothing (got {len(again)})")
    for config in written:
        good &= check(config.read_text().count(REPO_LOCAL) == 1,
                      f"{config.relative_to(slot)} still holds exactly one repo.local line")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} both maven.config files name the POPULATED .m2-old "
          f"(which exists) and not the empty .m2 that sorts first; re-running stacks nothing")
    return 0 if good else 1


def _report(checks):
    for item in checks:
        obs(f"  {item.repo:<8} expected={item.expected[:12]} actual="
            f"{(item.actual or '(none)')[:12]} -> {item.verdict}")


def c12(slot, at_base, ahead, absent):
    """Four repos, four positions, in ONE call — so a check that answers the same for everything fails."""
    slot = Path(slot)
    workspace = Workspace(slot.parent, git=default_git())
    expected = {"atbase": at_base, "desc": at_base, "present": ahead, "absent": absent}
    checks = workspace.base_check(slot, expected)
    _report(checks)
    by = {item.repo: item for item in checks}
    want_position = {"atbase": "at-base", "desc": "descendant", "present": "present", "absent": "absent"}
    want_verdict = {"atbase": "ok", "desc": "ok", "present": "advisory", "absent": "failed"}
    good = check(len(checks) == 4, f"four repos examined (got {len(checks)})")
    for repo in sorted(want_position):
        item = by.get(repo)
        if item is None:
            good = check(False, f"{repo} is missing from the report")
            continue
        good &= check(item.verdict == want_position[repo],
                      f"{repo}: position {item.verdict} == {want_position[repo]}")
        got = workspace.verdict([item])
        good &= check(got == want_verdict[repo], f"{repo}: verdict {got} == {want_verdict[repo]}")
    # THE DISCRIMINATING CONTROL. All four inputs are real repos with a readable HEAD, so `absent` here
    # is the object-missing branch and not "there is no git here" — the two share one label.
    good &= check(all(item.actual for item in checks),
                  "every repo has a readable HEAD, so `absent` is a MISSING OBJECT and not a missing repo")
    good &= check(len({item.verdict for item in checks}) == 4,
                  "the four inputs produced FOUR DISTINCT positions, so the check discriminates")
    good &= check(by["atbase"].actual == at_base, "at-base repo's HEAD really is the expected sha")
    good &= check(by["desc"].actual == ahead, "descendant repo's HEAD really is the 1-ahead sha")
    good &= check(by["present"].actual == at_base and by["present"].expected == ahead,
                  "present repo's HEAD is elsewhere and the expected sha is an object it holds")
    good &= check(workspace.verdict(checks) == "failed", "over all four together the WORST governs")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} at-base/descendant/present/absent -> "
          f"ok/ok/advisory/failed, four distinct positions from one call, every HEAD readable")
    return 0 if good else 1


def c13(slot, alpha_sha, beta_absent_sha, beta_head):
    """`alpha` ok, `beta` absent ⇒ overall failed — with the control that says the verdict can move."""
    slot = Path(slot)
    workspace = Workspace(slot.parent, git=default_git())
    checks = workspace.base_check(slot, {"alpha": alpha_sha, "beta": beta_absent_sha})
    _report(checks)
    by = {item.repo: item for item in checks}
    good = check(by["alpha"].verdict == "at-base", f"alpha is at-base (got {by['alpha'].verdict})")
    good &= check(by["beta"].verdict == "absent", f"beta is absent (got {by['beta'].verdict})")
    good &= check(bool(by["beta"].actual),
                  "beta HAS a readable HEAD, so `absent` means the expected object is missing from it")
    good &= check(workspace.verdict([by["alpha"]]) == "ok", "alpha ALONE is ok")
    good &= check(workspace.verdict([by["beta"]]) == "failed", "beta ALONE is failed")
    good &= check(workspace.verdict(checks) == "failed", "together the overall verdict is failed")
    # THE DISCRIMINATING CONTROL (OBS-49's inverse): a verdict that answered `failed` for every
    # multi-repo input would satisfy the assertion above. So the same two repos, both at base.
    both_ok = workspace.base_check(slot, {"alpha": alpha_sha, "beta": beta_head})
    _report(both_ok)
    good &= check(workspace.verdict(both_ok) == "ok",
                  "the SAME two repos with both expectations met are `ok`, so `failed` is not a constant")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} alpha ok + beta absent -> failed (worst governs); "
          f"the same pair with both bases met -> ok, so the aggregate is not constant")
    return 0 if good else 1


if __name__ == "__main__":
    WHICH = {"c9": c9, "c11": c11, "c12": c12, "c13": c13}
    sys.exit(WHICH[sys.argv[1]](*sys.argv[2:]))
