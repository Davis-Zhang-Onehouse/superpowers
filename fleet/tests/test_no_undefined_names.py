"""Every global name a module references must actually exist.

`SI-40`. `cli.py` used `COORDINATOR` at FOUR sites and never imported it. All four were `NameError`s
waiting to happen, and the suite was 864 tests green, because each one sits on a branch reached only in a
specific condition — the one in `brief` fires only when a milestone HAS a blocker, which is precisely when a
dispatched worker most needs `brief` to work. A real worker hit it mid-effort.

A test per branch would not have prevented this: the whole point is that nobody knew those branches were
unexercised. So this checks the property directly, over every module, and needs no maintenance as code is
added.

Why `symtable` rather than a regex or an AST walk: it is the compiler's own scope analysis. It already
knows that a name assigned in a function is local, that a parameter is not a global reference, that a
comprehension has its own scope, and that `global`/`nonlocal` change binding. Reimplementing any of that by
hand produces false positives, and a check that cries wolf gets deleted.

This is a dev-time check written in stdlib. No linter is installed on this box, and the package's
no-third-party-imports rule is about what `fleet` needs at RUNTIME — but writing it in stdlib means it runs
anywhere the suite runs, which is the only way it actually gets run.
"""
import builtins
import pathlib
import symtable
import unittest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "fleet"
BUILTINS = set(dir(builtins))

#: Provided by the import machinery at module load, so they exist at runtime while appearing nowhere in the
#: source. Not builtins, so they must be named explicitly or every module reports a false positive — and a
#: check that cries wolf gets deleted, which costs more than the check was worth.
MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__spec__", "__loader__", "__package__",
                  "__builtins__", "__path__", "__debug__"}


def _module_globals(top: symtable.SymbolTable) -> set:
    """Names bound at module level: assignments, imports, `def`, `class`."""
    names = set()
    for sym in top.get_symbols():
        if sym.is_assigned() or sym.is_imported() or sym.is_namespace():
            names.add(sym.get_name())
    return names


def _undefined_in(table: symtable.SymbolTable, defined: set, path: list) -> list:
    """Every global-scoped reference in this scope and its children that nothing defines."""
    bad = []
    for sym in table.get_symbols():
        name = sym.get_name()
        # `is_global()` is the compiler's verdict that this name resolves to module scope — so a local,
        # a parameter, a closure variable and a comprehension target are all already excluded.
        if (sym.is_global() and sym.is_referenced()
                and name not in defined and name not in BUILTINS and name not in MODULE_DUNDERS):
            bad.append((".".join(path) or "<module>", name))
    for child in table.get_children():
        bad.extend(_undefined_in(child, defined, path + [child.get_name()]))
    return bad


class TestNoUndefinedNames(unittest.TestCase):
    def test_every_module_reference_resolves(self):
        modules = sorted(SRC.glob("*.py"))
        self.assertTrue(modules, f"no modules found under {SRC}; the check would pass vacuously")
        problems = []
        for path in modules:
            top = symtable.symtable(path.read_text(), str(path), "exec")
            defined = _module_globals(top)
            for scope, name in _undefined_in(top, defined, []):
                problems.append(f"{path.name}: {scope!r} references {name!r}, which the module never "
                                f"defines or imports")
        self.assertEqual(problems, [], "\n  " + "\n  ".join(problems) if problems else "")

    def test_the_check_would_have_caught_SI_40(self):
        """The guard must fail on the actual bug, or it is decoration.

        A check that has never been seen to fail is indistinguishable from one that cannot.
        """
        source = (
            "from fleet.roadmap import TERMINAL\n"
            "def handler():\n"
            "    return COORDINATOR\n"          # imported nowhere — exactly the shipped defect
        )
        top = symtable.symtable(source, "fake.py", "exec")
        found = _undefined_in(top, _module_globals(top), [])
        self.assertIn(("handler", "COORDINATOR"), found)

    def test_a_legitimate_local_is_not_reported(self):
        """No false positives on the shapes that look similar."""
        source = (
            "import os\n"
            "TOP = 1\n"
            "def f(param):\n"
            "    local = param + TOP\n"
            "    return [x for x in range(local)] + [os.sep]\n"
            "def g():\n"
            "    global LATE\n"
            "    LATE = 2\n"
        )
        top = symtable.symtable(source, "fake.py", "exec")
        self.assertEqual(_undefined_in(top, _module_globals(top), []), [])


if __name__ == "__main__":
    unittest.main()
