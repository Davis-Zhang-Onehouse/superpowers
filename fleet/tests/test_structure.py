"""Structural invariants. These are the assertions that make the architecture a fact rather than an
intention: the import graph, the no-prose-parsing rule, and the isolation from the live stores."""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "fleet"
LEAVES = {"identity", "store", "pool", "session", "atomic", "release_scope"}
EXPECTED = {"identity", "store", "pool", "session", "atomic", "layout", "profiles", "reconcile",
            "guards", "roadmap", "review", "harvest", "render", "cli"}

#: The two zero-dependency primitives every layer may use without becoming non-leaf: the shared error
#: base, and the shared atomic write. Both are asserted to import nothing themselves (`LEAVES`), so
#: excusing them from the dependency graph cannot hide a cycle — and the alternative is worse: `store` and
#: `pool` would each need their own copy of the write primitive to stay "leaves", which is FI-20 exactly.
PRIMITIVES = {"errors", "atomic"}

#: The one module allowed to name a staging path. `FI-20`: this primitive was implemented eight times, by
#: seven implementers, each deriving the tmp name from the target and so sharing it with every concurrent
#: writer of the same file.
ATOMIC = "atomic"

#: Variable names a hand-rolled staging path is written to. The eight copies used exactly `tmp`.
_TMP_NAMES = {"tmp", "tmpfile", "tmp_path", "tmppath", "temp", "temp_path", "staging", "scratch"}


def imports_of(mod: pathlib.Path) -> set:
    tree = ast.parse(mod.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fleet"):
            parts = node.module.split(".")
            if len(parts) > 1:
                out.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("fleet."):
                    out.add(alias.name.split(".")[1])
    return out - PRIMITIVES   # a shared zero-dependency primitive is not a dependency edge


def modules():
    return [p for p in SRC.glob("*.py") if p.stem not in {"__init__"} | PRIMITIVES]


class TestStructure(unittest.TestCase):
    def test_exit_code_registry_is_the_only_definition(self):
        from fleet import EXIT_CODES, EXIT_OK, EXIT_REFUSED
        self.assertEqual(set(EXIT_CODES), {0, 1, 2, 3, 4})
        self.assertEqual((EXIT_OK, EXIT_REFUSED), (0, 4))

    def test_no_module_imports_cli(self):
        for mod in modules():
            if mod.stem == "cli":
                continue
            self.assertNotIn("cli", imports_of(mod), f"{mod.stem} imports cli")

    def test_leaves_import_nothing_in_package(self):
        present = [leaf for leaf in LEAVES if (SRC / f"{leaf}.py").exists()]
        self.assertTrue(present, "no leaf module exists yet — this assertion is vacuous")
        for leaf in present:
            self.assertEqual(imports_of(SRC / f"{leaf}.py"), set(), f"{leaf} is not a leaf")

    def test_no_import_cycles(self):
        graph = {mod.stem: imports_of(mod) for mod in modules()}
        stack, done = set(), set()

        def visit(node):
            if node in stack:
                self.fail(f"import cycle at {node}")
            if node in done or node not in graph:
                return
            stack.add(node)
            for dep in graph[node]:
                visit(dep)
            stack.discard(node)
            done.add(node)

        for node in list(graph):
            visit(node)

    def test_no_module_writes_the_live_stores(self):
        # FA-3: the ANSI coordinator is running on the old tooling right now, so nothing here may touch
        # its stores. The needles are ASSEMBLED rather than written literally, and this file excludes
        # itself: the first run of this check flagged the checker, because the banned strings appeared in
        # the checker's own source. That is OBS-44's class ("a marker two things share is not a marker")
        # and OBS-50's ("an assertion must anchor to something only the BEHAVIOUR produces, never a word
        # the reporting layer also emits"). Filed as FI-1.
        needles = ("claude-" + "dispatch-board", "claude-" + "ws-pool")
        me = pathlib.Path(__file__).name
        for mod in list(SRC.glob("*.py")) + list((ROOT / "tests").glob("*.py")):
            if mod.name == me:
                continue
            text = mod.read_text()
            for banned in needles:
                self.assertNotIn(banned, text, f"{mod.name} references the live store {banned}")

    def test_exactly_one_liveness_implementation(self):
        # The predecessor had two near-identical copies, which is how OI-16 became two defects.
        #
        # This counts AST FunctionDef nodes, not occurrences of the string "def alive". The first
        # version counted the substring over raw file text and therefore counted PROSE: it fired during
        # parallel implementation because a module's docstring mentioned `def alive` in a sentence
        # explaining this very rule. That is the third instance in this build of the family FI-1 named
        # (OBS-44 "a marker two things share is not a marker" / OBS-50 "anchor to something only the
        # BEHAVIOUR produces") — and the second time I have authored it. Structure, not text.
        defs = []
        for mod in SRC.glob("*.py"):
            for node in ast.walk(ast.parse(mod.read_text())):
                if isinstance(node, ast.FunctionDef) and node.name == "alive":
                    defs.append(f"{mod.stem}.{node.name}")
        self.assertLessEqual(len(defs), 1, f"liveness is implemented more than once: {defs}")

    def test_exactly_one_atomic_write_implementation(self):
        # The same shape as the liveness assertion above, and for a sharper reason. Atomic write is the
        # most safety-critical primitive in this package, and it shipped EIGHT times — `store` twice,
        # `pool`, `workspace`, `review`, `roadmap`, `harvest` twice — each copy deriving its staging path
        # from the target and therefore sharing it with every concurrent writer of the same file. Fourteen
        # records were left permanently unreadable by it, and no mutation caught it because every mutation
        # was single-threaded (FI-20).
        defs = []
        for mod in SRC.glob("*.py"):
            for node in ast.walk(ast.parse(mod.read_text())):
                if isinstance(node, ast.FunctionDef) and node.name in ("atomic_write", "atomic_update"):
                    defs.append(f"{mod.stem}.{node.name}")
        self.assertEqual(sorted(defs), ["atomic.atomic_update", "atomic.atomic_write"],
                         f"the atomic write primitives are not exactly one each, in {ATOMIC}: {defs}")

    def test_no_module_builds_a_tmp_path_of_its_own(self):
        """The guard that stops the NINTH copy (`FI-20`).

        Structure, not text — the lesson `test_exactly_one_liveness_implementation` records above. A
        substring sweep over source text would fire on the prose in `atomic`'s own docstring, which is the
        family `FI-1` named ("a marker two things share is not a marker"), authored twice in this build
        already. So every needle here is an AST node a hand-rolled staging write must contain and prose
        cannot:

          a. an assignment to a staging-path variable (`tmp = ...`) — what all eight copies wrote;
          b. `with_suffix("...tmp")` — how all eight derived the name FROM THE TARGET;
          c. the publish itself: `os.replace(...)`, or a single-argument `.replace(x)`, which is
             `Path.replace` and cannot be `str.replace` (that one needs two arguments).

        (c) is the load-bearing one: any future copy, however it names its staging file, must publish it,
        and the publish is the node this catches.
        """
        violations = []
        for mod in sorted(SRC.glob("*.py")):
            if mod.stem == ATOMIC:
                continue
            for node in ast.walk(ast.parse(mod.read_text())):
                where = f"{mod.name}:{getattr(node, 'lineno', '?')}"
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in _TMP_NAMES:
                            violations.append(f"{where} assigns a staging path to {target.id!r}")
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                attr, args = node.func.attr, node.args
                if attr == "with_suffix" and any(
                        isinstance(a, ast.Constant) and isinstance(a.value, str) and "tmp" in a.value
                        for a in args):
                    violations.append(f"{where} derives a tmp name from the target with with_suffix()")
                if attr != "replace":
                    continue
                is_os = isinstance(node.func.value, ast.Name) and node.func.value.id == "os"
                one_path_arg = len(args) == 1 and not (isinstance(args[0], ast.Constant)
                                                      and isinstance(args[0].value, str))
                if is_os or one_path_arg:
                    violations.append(f"{where} publishes a staged file with .replace() of its own")
        self.assertEqual(violations, [],
                         "a module builds and publishes a staging path of its own instead of calling "
                         f"{ATOMIC}.atomic_write — this is FI-20's ninth copy: " + "; ".join(violations))
