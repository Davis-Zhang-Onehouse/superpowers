"""`B11`. A refusal names what clears it and who clears it — enforced, not remembered.

`errors.Refused` always ACCEPTED `clears_when`/`clears_who`, and `cli._report_error` always printed them, but
both were optional, so the contract held only where somebody remembered it: every refusal on the send path
passed neither ("No matching live runtime process owns the recorded pane" named no remedy and no actor),
and the ones that did name a route went stale — for a deleted owner they prescribed `abort` and `harvest`,
both of which exit 2 on a folder that is gone, while `fleet close --id`, the door that works, was named by
neither.

So the contract is checked over the SOURCE, by enumeration, the way a new site is added: every
`Refused(...)` call in `src/fleet` must pass both keywords, and neither may be a literal `None` or empty
string. A new refusal with no route fails here with its file and line — the site, not a sample of it.

The second half is that a named route has to be one that RUNS. Statically this can only prove its shape:
every backticked `fleet <verb> --flag` anywhere in the source names a verb the parser has and flags that
verb declares. Whether the route then succeeds in the state the refusal describes is a behavioural fact,
and the cases that prove it live beside the verbs (`test_cli.TestB11RefusalsNameARouteThatRuns`).
"""
import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
import ast
import pathlib
import re
import unittest

from fleet import cli

#: The package that was IMPORTED, not the tree beside this file: run against another source (a base export on
#: `PYTHONPATH`, a release copy) the scan must read the code under test, or it certifies the wrong tree.
SRC = pathlib.Path(cli.__file__).resolve().parent
ROUTE_KEYWORDS = ("clears_when", "clears_who")


def _called_name(call: ast.Call) -> str:
    func = call.func
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")


def refusal_sites():
    """Every `Refused(...)` call in the package, raised or returned, as (path, line, keywords)."""
    for path in sorted(SRC.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Call) and _called_name(node) == "Refused":
                yield path, node.lineno, {k.arg: k.value for k in node.keywords if k.arg}


def _empty(value: ast.AST) -> bool:
    return isinstance(value, ast.Constant) and (value.value is None or value.value == "")


def _text(node: ast.AST) -> str:
    """The literal text of a string expression; each interpolation reads as `<X>`."""
    parts = []
    for item in ast.walk(node):
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            parts.append(item.value)
        elif isinstance(item, ast.FormattedValue):
            parts.append("<X>")
    return "".join(parts)


class TestEveryRefusalNamesItsRoute(unittest.TestCase):

    def test_the_enumeration_finds_the_sites_it_is_about(self):
        """Positive control: a scan that finds nothing would pass the case below vacuously."""
        sites = list(refusal_sites())
        self.assertGreater(len(sites), 40, f"the scan found only {len(sites)} Refused(...) site(s)")
        self.assertTrue(any(path.name == "messaging.py" for path, _, _ in sites),
                        "the scan does not reach messaging.py, whose refusal is one of the originals")

    def test_every_refused_passes_clears_when_and_clears_who(self):
        missing = []
        for path, line, keywords in refusal_sites():
            lacks = [k for k in ROUTE_KEYWORDS if k not in keywords or _empty(keywords[k])]
            if lacks:
                missing.append(f"{path.name}:{line} lacks {'/'.join(lacks)}")
        self.assertEqual([], missing,
                         f"{len(missing)} refusal(s) name no route (what clears it and who clears it):\n  "
                         + "\n  ".join(missing))


class TestEveryNamedRouteIsACommandTheParserTakes(unittest.TestCase):
    ROUTE = re.compile(r"`fleet ([a-z][a-z-]*)([^`]*)`")

    def routes(self):
        for path in sorted(SRC.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant)
                                                       and isinstance(node.value, str)):
                    for match in self.ROUTE.finditer(_text(node)):
                        yield path, node.lineno, match

    def test_the_scan_finds_routes(self):
        self.assertGreater(len(list(self.routes())), 50)

    def test_every_backticked_fleet_command_names_a_real_verb_and_its_own_flags(self):
        common = {flag.name for flag in cli.COMMON_FLAGS} | {cli.DRY_RUN}
        wrong = []
        for path, line, match in self.routes():
            spec = cli.VERBS.get(match.group(1))
            if spec is None:
                wrong.append(f"{path.name}:{line} names no verb: {match.group(0)[:90]}")
                continue
            declared = common | {flag.name for flag in spec.flags}
            for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", match.group(2)):
                if flag not in declared:
                    wrong.append(f"{path.name}:{line} `{spec.name}` has no {flag}: {match.group(0)[:90]}")
        self.assertEqual([], wrong, "\n  ".join(wrong))


if __name__ == "__main__":
    unittest.main()
