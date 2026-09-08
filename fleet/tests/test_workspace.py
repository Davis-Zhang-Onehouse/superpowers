# tests/test_workspace.py
import pathlib, tempfile, unittest
from fleet.workspace import BaseCheck, Workspace
from fleet.errors import BadInput

class FakeGit:
    """Injected git.

    TWO separate facts, deliberately — an earlier version of this double answered both
    `merge-base --is-ancestor` and `cat-file -t` from one `contains` map keyed on the expected sha, which
    conflated "is an ancestor of HEAD" with "exists as an object". The three-way verdict needs them apart:
    the `present` state IS "the object exists and is NOT an ancestor", so a single map makes that state
    unreachable and the `present` case unsatisfiable. Task 6's implementer proved it by enumerating all 21
    query shapes and finding zero responses that differ between the two fixtures. Filed as FI-14.

      heads[repo]      -> HEAD sha
      ancestors[repo]  -> shas that ARE ancestors of HEAD
      objects[repo]    -> shas that exist as objects at all
    """

    def __init__(self, heads, ancestors=None, objects=None):
        self.heads = heads
        self.ancestors = ancestors or {}
        self.objects = objects or {}
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append((tuple(args), str(cwd)))
        repo = pathlib.Path(cwd).name
        if args[:1] == ["rev-parse"]:
            head = self.heads.get(repo)
            return (0, head + "\n") if head else (128, "")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return (0, "") if args[2] in self.ancestors.get(repo, ()) else (1, "")
        if args[:1] == ["cat-file"]:
            return (0, "commit\n") if args[2] in self.objects.get(repo, ()) else (128, "")
        return (1, "")


class TestGolden(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.ws = Workspace(self.tmp / "home", git=FakeGit({}))

    def test_an_unset_golden_is_bad_input_that_NAMES_THE_FIX(self):
        # FR2-13.2 / MI-7: there is no golden file on the real box, so the old tool survived only by
        # inheriting one from the last dispatch record — a fallback doing load-bearing work.
        with self.assertRaises(BadInput) as cm:
            self.ws.golden()
        self.assertIn("set_golden", str(cm.exception))

    def test_the_named_fix_is_a_verb_THAT_EXISTS(self):
        # FI-19a: the diagnostic prescribed `fleet golden --set <path>`, and there is no `golden` verb —
        # the verb is `set-golden --path`. A message naming a non-existent remedy is W2-20's family: the
        # tool and its own usage disagree, and the operator's next command fails for a second reason.
        with self.assertRaises(BadInput) as cm:
            self.ws.golden()
        text = str(cm.exception)
        self.assertIn("fleet set-golden --path", text, "the remedy does not name the real verb")
        self.assertNotIn("golden --set", text, "the remedy still names a verb that does not exist")

    def test_set_then_get_round_trips(self):
        g = self.tmp / "ws0"; g.mkdir()
        self.ws.set_golden(g)
        self.assertEqual(self.ws.golden(), g)

    def test_a_golden_that_does_not_exist_is_refused_at_set_time(self):
        with self.assertRaises(BadInput):
            self.ws.set_golden(self.tmp / "nope")

class TestBuildCache(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.ws = Workspace(self.tmp / "home", git=FakeGit({}))
        self.slot = self.tmp / "ws1"
        (self.slot / "proj").mkdir(parents=True)
        (self.slot / "proj" / "pom.xml").write_text("<project/>")

    def test_isolation_is_applied_at_dispatch_not_requested_of_the_worker(self):
        written = self.ws.isolate_build_cache(self.slot)
        cfg = self.slot / "proj" / ".mvn" / "maven.config"
        self.assertIn(cfg, written)
        self.assertIn("-Dmaven.repo.local=", cfg.read_text())

    def test_an_ALREADY_POPULATED_cache_under_any_name_is_reused(self):
        # OI-6: pointing at a bare `.m2` that does not exist is isolated with a COLD cache, which is its
        # own failure. R5I-4 is the live instance: a stale `.m2-compact1` left in place and overridden on
        # every invocation instead.
        populated = self.slot / ".m2-compact1" / "org" / "x"
        populated.mkdir(parents=True)
        (populated / "a.jar").write_text("x")
        self.ws.isolate_build_cache(self.slot)
        self.assertIn(".m2-compact1", (self.slot / "proj" / ".mvn" / "maven.config").read_text())

    def test_it_never_points_at_a_directory_that_does_not_exist(self):
        self.ws.isolate_build_cache(self.slot)
        line = (self.slot / "proj" / ".mvn" / "maven.config").read_text().strip()
        target = pathlib.Path(line.split("=", 1)[1])
        self.assertTrue(target.is_dir(), f"{target} does not exist")

    def test_it_is_idempotent(self):
        self.ws.isolate_build_cache(self.slot)
        first = (self.slot / "proj" / ".mvn" / "maven.config").read_text()
        self.ws.isolate_build_cache(self.slot)
        self.assertEqual((self.slot / "proj" / ".mvn" / "maven.config").read_text(), first)

class TestBaseCheck(unittest.TestCase):
    """OBS-12: the first version of this check false-alarmed on BOTH states a healthy worker occupies.
    'I encoded the state I HAPPENED to see first as the only correct one.'"""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.slot = self.tmp / "ws1"
        for r in ("alpha", "beta"):
            (self.slot / r).mkdir(parents=True)

    def ws(self, heads, ancestors=None, objects=None):
        return Workspace(self.tmp / "home", git=FakeGit(heads, ancestors, objects))

    def test_at_base_is_ok(self):
        w = self.ws({"alpha": "aaa"})
        checks = w.base_check(self.slot, {"alpha": "aaa"})
        self.assertEqual([c.verdict for c in checks], ["at-base"])
        self.assertEqual(w.verdict(checks), "ok")

    def test_a_descendant_is_ok_because_that_is_the_intended_end_state(self):
        w = self.ws({"alpha": "bbb"}, ancestors={"alpha": ("aaa",)}, objects={"alpha": ("aaa",)})
        checks = w.base_check(self.slot, {"alpha": "aaa"})
        self.assertEqual([c.verdict for c in checks], ["descendant"])
        self.assertEqual(w.verdict(checks), "ok")

    def test_present_but_not_checked_out_is_ADVISORY_not_a_failure(self):
        # An analysis milestone deliberately parked on the golden, reading the base via git show, is the
        # BETTER choice there — it keeps the prebuilt native artifacts valid.
        # The expected sha EXISTS as an object but is NOT an ancestor of HEAD — the whole point of this
        # state, and the state a single-map double cannot express.
        w = self.ws({"alpha": "zzz"}, ancestors={"alpha": ()}, objects={"alpha": ("aaa",)})
        checks = w.base_check(self.slot, {"alpha": "aaa"})
        self.assertEqual([c.verdict for c in checks], ["present"])
        self.assertEqual(w.verdict(checks), "advisory")

    def test_absent_is_the_only_hard_failure(self):
        w = self.ws({"alpha": "zzz"}, ancestors={"alpha": ()}, objects={"alpha": ()})
        checks = w.base_check(self.slot, {"alpha": "aaa"})
        self.assertEqual([c.verdict for c in checks], ["absent"])
        self.assertEqual(w.verdict(checks), "failed")

    def test_the_worst_verdict_across_repos_governs(self):
        w = self.ws({"alpha": "aaa", "beta": "zzz"},
                    ancestors={"alpha": ("aaa",), "beta": ()}, objects={"alpha": ("aaa",), "beta": ()})
        self.assertEqual(w.verdict(w.base_check(self.slot, {"alpha": "aaa", "beta": "aaa"})), "failed")

class FakeGitHeads:
    """Injected git for heads() tests. Returns (rc, stdout) based on repo name."""
    def __init__(self, answers):
        self.answers = answers

    def __call__(self, args, cwd):
        return self.answers.get(pathlib.Path(cwd).name, (1, ""))

class TestHeads(unittest.TestCase):
    """Repo HEAD snapshots. A repo that cannot answer is omitted, never recorded as empty:
    an empty string would read as a measured answer downstream (FI-417)."""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_heads_maps_each_repo_to_its_sha(self):
        ws = Workspace(self.tmp, git=FakeGitHeads({"gluten-internal": (0, "a" * 40 + "\n"),
                                                    "velox-internal": (0, "b" * 40 + "\n")}))
        self.assertEqual(ws.heads(self.tmp, ["velox-internal", "gluten-internal"]),
                         {"gluten-internal": "a" * 40, "velox-internal": "b" * 40})

    def test_a_repo_that_cannot_answer_is_omitted_not_empty(self):
        ws = Workspace(self.tmp, git=FakeGitHeads({"gluten-internal": (0, "a" * 40 + "\n"), "velox-internal": (128, "")}))
        self.assertEqual(ws.heads(self.tmp, ["gluten-internal", "velox-internal"]),
                         {"gluten-internal": "a" * 40})
