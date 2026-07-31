"""A4c — real verbs, run under `-S` (no site-packages on sys.path) with a meta_path hook that REFUSES
any non-stdlib import requested BY A FLEET MODULE.

Attribution is by calling frame, deliberately. A name-only deny-list reports the stdlib's own optional
probes as fleet violations: CPython's `copy.py` does `from org.python.core import PyStringMap` inside a
try/except for Jython, so `org` is attempted on every run and is nobody's defect. A check that cannot
say whose import it caught is a check that gets switched off — which is worse than not having it.
"""
import os, sys, importlib
FLEET_DIR = os.path.realpath(os.environ["A4_SRC_SECOND"])
STD = set(sys.stdlib_module_names)
REFUSED, ALLOWED_ELSEWHERE = [], []


def _requester():
    """The frame that ACTUALLY asked for this module, skipping only importlib's own machinery.

    The first version of this walked the whole stack for the nearest fleet frame, which is wrong and
    said so loudly: `cli.py` imports `dataclasses`, `dataclasses` imports `copy`, and `copy` probes
    `org.python.core` — so the nearest fleet frame up the stack is `cli.py` and a stdlib probe three
    levels down got attributed to the product. Only the IMMEDIATE requester can answer "whose import
    is this", so the walk stops at the first frame that is not import machinery.
    """
    frame = sys._getframe(1)
    while frame:
        name = os.path.realpath(frame.f_code.co_filename)
        base = os.path.basename(name)
        if base.startswith("<") or "importlib" in name or base in ("a4c.py",):
            frame = frame.f_back
            continue
        return name if name.startswith(FLEET_DIR) else None
    return None


class DenyNonStdlibFromFleet:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in STD or root == "fleet":
            return None
        who = _requester()
        if who is None:
            ALLOWED_ELSEWHERE.append(name)
            return None
        REFUSED.append(f"{name} <- {who}")
        raise ImportError(f"A4c: refused non-stdlib import {name!r} requested by {who}")


sys.meta_path.insert(0, DenyNonStdlibFromFleet())

# Import every module in the package with the hook armed, so a module-level third-party import is caught
# before any verb runs.
mods = sorted(p[:-3] for p in os.listdir(os.path.join(FLEET_DIR))
              if p.endswith(".py") and p != "__init__.py")
for mod in ["fleet"] + [f"fleet.{m}" for m in mods]:
    importlib.import_module(mod)
print("site_packages_on_path:", [p for p in sys.path if "site-packages" in p or "dist-packages" in p])
print("modules_imported:", len(mods) + 1)

from fleet.cli import main, registered_codes            # noqa: E402

INST, SLOT = os.environ["A4_INST"], os.environ["A4_SLOT"]
# Real handlers, chosen to cover the runtime-heavy paths: subprocess (`verify`), /proc (`reconcile`),
# git (`set-golden`), json state (`enroll`/`harvest`/`reap`), the layout matrix (`init`/`lint`).
matrix = [("leases", []), ("board", []), ("lint", ["--instant", INST]), ("roadmap", ["--instant", INST]),
          ("reconcile", []), ("compaction-status", []), ("verify", ["--instant", INST]),
          ("init", ["--name", "a4cprobe"]), ("enroll", ["--slot", SLOT]),
          ("set-golden", ["--path", os.environ["A4_GOLDEN"]]), ("harvest", []), ("reap", []),
          ("declare", ["--instant", INST, "--phase", "awaiting-ci"]),
          ("park", ["--instant", INST, "--question", "a4c"]), ("unpark", ["--instant", INST]),
          ("pane-guard", ["--pane", "itfleet-A-absent-zzz"])]
codes = {}
for verb, args in matrix:
    rc = main([verb] + args)
    codes[verb] = rc
    assert rc in registered_codes(verb), f"{verb} returned unregistered {rc}"
print("verbs_run:", len(matrix), "codes:", codes)
print("REFUSED_FROM_FLEET:", REFUSED)
print("attempted_elsewhere_and_allowed:", sorted(set(ALLOWED_ELSEWHERE)))
assert not REFUSED, REFUSED
print("OK A4c")
