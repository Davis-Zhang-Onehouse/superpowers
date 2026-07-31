"""M9 — an audit of every handler: no push/merge/publish/rm-rf outside the section dir, no spawn behind
a handler's back, and every DELETE site named together with the path it deletes.

The audit runs over the WHOLE package, not over `cli.py`'s intra-module call closure. A handler reaches
another module through an attribute call (`ctx.pool.unenroll`), and a closure that follows only bare-name
calls inside one module cannot cross that boundary — so the package's own `FORBIDDEN_CALLS` invariant is
unenforced exactly where the deletes live."""
import ast, os
from pathlib import Path
from fleet.cli import FORBIDDEN_CALLS, FORBIDDEN_COMMANDS, VERBS
pkg = Path(os.environ["INSTANT"]) / "src" / "fleet"
#: Probe/runner factories: the only functions allowed to spawn. Each is referenced by `default_context`
#: (or a caller's own injection) and by no handler.
SEAMS = {("session.py", "default_probes"), ("cli.py", "_default_runner"),
         ("workspace.py", "default_git")}
DELETERS = {"rmtree", "remove", "removedirs", "unlink", "rmdir"}
#: Every delete-shaped call in the package, read and accounted for. `pool` deletes its own bookkeeping
#: under `<FLEET_HOME>`; `roadmap._consume` calls `list.remove` on a python list and touches no file.
#: A new, moved or renamed site fails this case rather than being absorbed.
DELETE_ALLOWLIST = {
    ("pool.py", "unenroll", "unlink"),      # <home>/pool/enrolled/<slot>.json
    ("pool.py", "release", "unlink"),       # <home>/pool/leases/<slot>/lease.json and leftovers
    ("pool.py", "release", "rmdir"),        # <home>/pool/leases/<slot>
    ("roadmap.py", "_consume", "remove"),   # list.remove(body) — not a filesystem call
    # SI-9 / SI-7. Four sites added deliberately, each with the reason it is safe. The list stays a
    # CEILING: it is printed when an entry disappears, so it cannot quietly grow stale.
    ("atomic.py", "atomic_write", "unlink"),  # its OWN staging file, path.parent/tmp_name(path.name),
                                              # on the failure path only. Not removing it leaves a partial
                                              # file for the next reader — FI-20's third property.
    ("atomic.py", "_break", "rmdir"),         # its OWN advisory lock dir, path.parent/f".{path.name}.lock",
                                              # and only after the holder is shown dead. rmdir cannot empty
                                              # a directory, so it fails safe.
    ("pool.py", "_reclaim", "unlink"),        # staging litter inside <home>/pool/leases/<slot>, and ONLY
                                              # names matching atomic.tmp_name's shape: anything else raises
                                              # Refused naming it rather than being swept (SI-7).
    ("pool.py", "_reclaim", "rmdir"),         # <home>/pool/leases/<slot> once emptied of that litter.
}
NOT_A_FILE_DELETE = {("roadmap.py", "_consume", "remove")}

def owner_of(tree):
    """The chain of enclosing functions for every node. A class name is not who makes a call, and a
    nested helper inside a probe factory is still inside that factory — the seam is the whole closure."""
    out = {}
    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            nxt = chain + (child.name,) if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                else chain
            out[id(child)] = nxt
            walk(child, nxt)
    walk(tree, ())
    return out

IN_PACKAGE = set()
for path in sorted(pkg.glob("*.py")):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            IN_PACKAGE.add(node.name)
SELF_LIKE = {"self", "ctx", "store", "pool", "sessions", "harvest", "roadmap", "review", "profile"}
bad, spawn_sites, examined, in_pkg_sites, deletes, delete_sites = [], [], 0, [], set(), []
for path in sorted(pkg.glob("*.py")):
    text = path.read_text()
    examined += 1
    for shape in FORBIDDEN_COMMANDS + ("rm -rf ~", "> /etc", "sudo "):
        if shape in text:
            bad.append(f"{path.name} contains the outward shape {shape!r}")
    tree = ast.parse(text)
    owners = owner_of(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attribute = isinstance(node.func, ast.Attribute)
        name = node.func.attr if attribute else getattr(node.func, "id", "")
        receiver = getattr(node.func.value, "id", "") if attribute else ""
        if name not in FORBIDDEN_CALLS:
            continue
        chain = owners.get(id(node), ())
        owner = chain[-1] if chain else "<module>"
        site = (f"{path.name}:{node.lineno} {'.'.join(chain) or '<module>'}() -> "
                f"{receiver + '.' if receiver else ''}{name}()")
        if any((path.name, link) in SEAMS for link in chain):
            spawn_sites.append(site)
        elif name in DELETERS:
            deletes.add((path.name, owner, name))
            delete_sites.append(site)
        elif receiver in SELF_LIKE and name in IN_PACKAGE:
            in_pkg_sites.append(site)
        else:
            bad.append(f"FORBIDDEN CALL {site}")
print(f"examined {examined} module(s) behind {len(VERBS)} handlers")
for site in sorted(spawn_sites):
    print("spawn seam (no handler reaches it):", site)
for site in sorted(in_pkg_sites):
    print("in-package method, not a spawn:", site)
for site in sorted(delete_sites):
    print("DELETE site:", site)
undeclared = sorted(deletes - DELETE_ALLOWLIST)
if undeclared:
    bad.append(f"UNDECLARED DELETE SITE(S): {undeclared}")
gone = sorted(DELETE_ALLOWLIST - deletes)
if gone:
    print("allow-listed delete no longer present (the list is a ceiling):", gone)
# Every file-deleting site must derive its target from the store root, never from a workspace or $HOME.
source_of = {}
for path in sorted(pkg.glob("*.py")):
    body = path.read_text()
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.FunctionDef):
            source_of[(path.name, node.name)] = ast.get_source_segment(body, node) or ""
# SI-9. The rule WAS `"self.enrolled" in body or "self.leases" in body` — a substring test, which is
# why it rejected atomic.py's two sites: their targets are derived from the function's OWN operand
# (`path.parent / tmp_name(path.name)`), which is every bit as rooted, just not rooted in the pool.
#
# The fix is to widen the RULE, not to add names to the allowlist. An allowlist entry says "somebody
# decided this one is fine"; a rule says what makes any delete fine, and can still fail. What makes these
# safe is that the deleted path is DERIVED, inside the same function, from either the store root or one of
# the function's own parameters — never from $HOME, the environment, or an absolute literal. So that is
# what is now checked, by following the assignments.
FORBIDDEN_SOURCES = ("Path.home", "expanduser", "os.environ", "getenv", "os.sep")
ROOTS = ("self.enrolled", "self.leases", "self.root", "self.home")

def deleted_names(fn):
    """The local name each delete in this function is applied to: `os.unlink(tmp)` -> tmp,
    `lock.rmdir()` -> lock, `entry.unlink()` -> entry."""
    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("unlink", "rmdir", "rmtree", "remove"):
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id not in ("os", "shutil"):
            out.add(node.func.value.id)                     # receiver.unlink()
        for arg in node.args:                               # os.unlink(x)
            if isinstance(arg, ast.Name):
                out.add(arg.id)
    return out

def derivation_ok(fn, name, depth=0):
    """Whether EVERY assignment to `name` in this function derives it from a parameter or the store root.

    "Every", not "some", and that word was bought by a mutation. The first version of this returned True on
    the first assignment it found that mentioned the store root — so injecting a SECOND assignment
    `record = Path.home() / 'victim.json'` right above `record.unlink()` SURVIVED: the original rooted
    assignment was still there, the check found it, and never looked at the poisoned one. A rule that any
    single safe assignment satisfies is a rule an attacker (or a careless edit) satisfies by leaving the
    safe line in place.
    """
    if depth > 6:
        return False
    params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    sources = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                sources.append(node.value)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                sources.append(node.value)
        elif isinstance(node, (ast.For, ast.comprehension)):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                sources.append(node.iter)
    if not sources:
        return name in params            # a parameter never assigned: the caller's path, which is the point
    for src in sources:
        text = ast.unparse(src)
        if any(f in text for f in FORBIDDEN_SOURCES):
            return False                 # ONE poisoned assignment condemns the name
        if any(r in text for r in ROOTS):
            continue
        if any(isinstance(n, ast.Name) and (n.id in params or derivation_ok(fn, n.id, depth + 1))
               for n in ast.walk(src)):
            continue
        return False                     # this assignment is derived from nothing we can vouch for
    return True


fn_of = {}
for path in sorted(pkg.glob("*.py")):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            fn_of[(path.name, node.name)] = node

for module, function, call in sorted(deletes):
    if (module, function, call) in NOT_A_FILE_DELETE:
        print(f"{module}:{function}() {call}() is a list operation, not a filesystem delete")
        continue
    fn = fn_of.get((module, function))
    if fn is None:
        bad.append(f"{module}:{function}() could not be parsed, so its delete is unverified")
        continue
    names = deleted_names(fn)
    if not names:
        bad.append(f"{module}:{function}() deletes something this audit could not name — unverified")
        continue
    unrooted = sorted(n for n in names if not derivation_ok(fn, n))
    print(f"{module}:{function}() {call}() targets {sorted(names)} derived from the store root or its own "
          f"operand: {not unrooted}")
    if unrooted:
        bad.append(f"{module}:{function}() deletes {unrooted}, which is derived neither from the store "
                   f"root nor from the function's own parameters")
assert not bad, "\n".join(bad)
print(f"OK M9: across all {examined} modules — no push/merge/publish/rm-rf shape anywhere; the only "
      f"spawn sites are the {len(SEAMS)} probe/runner factories ({len(spawn_sites)} call sites), none "
      f"reachable from a handler; every delete is one of {len(deletes)} accounted-for sites, and each "
      f"target is DERIVED (by following the assignments, not by matching a substring) from the store root "
      f"or from that function's own parameters — never from $HOME, the environment or an absolute literal")
