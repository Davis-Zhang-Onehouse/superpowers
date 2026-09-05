"""Tests for `fleet.profiles` — typed manifests and invocation templates.

Every case names the finding it encodes, because the finding is what stops the assertion being
weakened into something that is green and useless. The headline one: a kind-aware linter that picks
the WRONG kind is worse than no linter, because it converts "unchecked" into "checked and fine".
"""
import pathlib
import unittest

from fleet.errors import BadInput
from fleet.profiles import KINDS, Profile, agrees_with_optype, lint

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "profiles"
INVALID = FIXTURES / "_invalid"


def load(name: str) -> Profile:
    return Profile.load(FIXTURES / name)


def shipped() -> list:
    """Every SHIPPABLE fixture profile, in a stable order.

    `_`-prefixed directories hold the deliberately invalid manifests, which are not part of the
    population a lint sweep would see. Order matters here: `workerMissingClause` sorts LAST, so a
    check that runs on the first profile only (M-35) cannot reach it.
    """
    return [Profile.load(p) for p in sorted(FIXTURES.iterdir())
            if p.is_dir() and not p.name.startswith("_")]


def flagged(violations, rule: str) -> list:
    return [v for v in violations if v.rule == rule and v.severity == "violation"]


class TestKind(unittest.TestCase):
    def test_kind_is_read_from_a_declared_field(self):
        p = load("compaction")
        self.assertEqual(p.kind, "compaction")
        self.assertIn(p.kind, KINDS)

    def test_an_undeclared_kind_is_an_error_not_a_default(self):
        # OBS-5 / OBS-64. Grepping kind out of prose failed in BOTH directions: too greedy (a later
        # word in the same line won) and too strict (`^Kind:` missed a mid-line declaration), and
        # 3 of 5 shipped profiles silently fell back to `worker`. The fixture prose below is built
        # so that every prose-derived answer is available and all of them are wrong — the only
        # correct behaviour is to refuse.
        for name in ("undeclaredKind", "proseOnlyKind"):
            prose = (INVALID / name / "charter.md").read_text()
            self.assertIn("worker", prose, "fixture must offer the historical wrong default")
            self.assertIn("coordinator", prose, "fixture must offer a greedy same-line winner")
            self.assertIn("compaction", prose, "fixture must offer an anchored-grep winner")
            with self.assertRaises(BadInput, msg=name) as cm:
                Profile.load(INVALID / name)
            msg = str(cm.exception)
            self.assertIn("kind", msg, name)
            self.assertIn("profile.json", msg, name)

    def test_an_unknown_kind_is_an_error(self):
        self.assertEqual("wizard", __import__("json").loads(
            (INVALID / "unknownKind" / "profile.json").read_text())["kind"])
        with self.assertRaises(BadInput) as cm:
            Profile.load(INVALID / "unknownKind")
        self.assertIn("wizard", str(cm.exception))
        for kind in KINDS:
            self.assertIn(kind, str(cm.exception))


class TestRender(unittest.TestCase):
    def test_render_fills_every_declared_placeholder(self):
        p = load("placeholders")
        self.assertEqual(set(p.placeholders), {"TITLE", "BASE", "RUN_ID"})
        out = p.render({"TITLE": "foldTheStack", "BASE": "00000000",
                        "RUN_ID": "29618938212"})
        self.assertEqual(set(out), {"charter", "seed"})
        self.assertIn("foldTheStack", out["charter"])
        self.assertIn("00000000", out["charter"])
        self.assertIn("29618938212", out["seed"])
        for artifact, text in out.items():
            self.assertNotIn("{{", text, artifact)

    def test_an_unresolved_placeholder_in_a_RENDERED_artifact_raises(self):
        # SR-C10-2: the old renderer left an unknown {{VAR}} LITERAL, with a human checklist as the
        # only defence — and the rendered charter is what the worker reads first.
        p = load("placeholders")
        with self.assertRaises(BadInput) as cm:
            p.render({"TITLE": "foldTheStack", "BASE": "00000000"})
        self.assertIn("RUN_ID", str(cm.exception))
        self.assertIn("seed", str(cm.exception))


class TestLint(unittest.TestCase):
    def test_an_unsubstituted_authoring_placeholder_is_a_lint_violation(self):
        # OBS-63: `the-tip-in-your-CHARTER` shipped in compact-ansi/seed.txt where two baseline run
        # ids belonged, disagreeing with its own sibling charter.
        p = load("authoringPlaceholder")
        self.assertIn("the-tip-in-your-CHARTER", p.seed, "fixture lost its stub")
        v = flagged(lint(p), "authoring-placeholder")
        self.assertEqual(len(v), 1, [x.detail for x in v])
        self.assertIn("the-tip-in-your-CHARTER", v[0].detail)
        self.assertIn("seed.txt", v[0].detail)
        # and a profile without one is clean on this rule
        self.assertEqual(flagged(lint(load("workerCompliant")), "authoring-placeholder"), [])

    def test_a_seed_and_charter_disagreeing_on_a_baseline_id_is_flagged(self):
        # Same OBS-63 entry: the seed and the charter of one profile named different baselines.
        p = load("baselineDisagreement")
        v = flagged(lint(p), "baseline-disagreement")
        self.assertEqual(len(v), 1, [x.detail for x in v])
        self.assertIn("29618938212", v[0].detail)
        self.assertIn("29618938999", v[0].detail)
        # An agreeing pair is not flagged — otherwise the rule is just "has a baseline".
        self.assertEqual(flagged(lint(load("staticSha")), "baseline-disagreement"), [])

    def test_a_static_sha_is_flagged_but_an_all_digit_run_id_is_NOT(self):
        # OBS-41 then OBS-42: the over-correction flagged a CI RUN ID because digits are valid hex,
        # and pinning run ids is what the brief contract REQUIRES. A sha contains a hex letter.
        p = load("staticSha")
        self.assertIn("a1b2c3d4e5f6a7", p.charter, "fixture lost its sha")
        self.assertIn("29618938212", p.charter, "fixture lost its run id")
        v = flagged(lint(p), "static-sha")
        self.assertEqual(len(v), 1, [x.detail for x in v])
        self.assertIn("a1b2c3d4e5f6a7", v[0].detail)
        self.assertNotIn("29618938212", v[0].detail)
        for x in lint(p):
            self.assertNotIn("29618938212", x.detail if x.rule == "static-sha" else "")

    def test_a_worker_facing_profile_missing_the_awaiting_ci_clause_is_flagged(self):
        # OBS-63: the clause landed in the fix profile and not the compaction profile — L-8
        # answering "where else does this shape live?" by grepping for the text it just fixed,
        # which finds copies and never counterparts. So the check is imposed on the WHOLE
        # worker-facing population, never on the profile that happens to be looked at first
        # (M-35), and it is not satisfied by the profile declaring the clause itself.
        population = shipped()
        facing = [p for p in population if p.kind in ("worker", "compaction")]
        self.assertGreaterEqual(len(facing), 2, "M-35 needs two worker-facing profiles")

        missing = load("workerMissingClause")
        compliant = load("workerCompliant")
        self.assertNotIn(missing.path.name, ("", None))
        # The non-compliant fixture DOES contain the literal token, so a lint that greps for
        # AWAITING-CI passes it. The clause is the `fleet declare` command, not the token.
        self.assertIn("AWAITING-CI", missing.charter)
        self.assertNotIn("fleet declare --instant", missing.charter)
        self.assertEqual(len(flagged(lint(missing), "awaiting-ci-clause")), 1)
        self.assertEqual(flagged(lint(compliant), "awaiting-ci-clause"), [])
        # None of the profiles declares the clause in its own `requires_clauses`, so the rule
        # cannot be passing by accident through the author-declared clause check.
        self.assertEqual([c for p in facing for c in p.requires_clauses
                          if "awaiting-ci" in c.lower()], [])
        # Swept over the population in order, exactly the non-compliant one is flagged.
        offenders = sorted(p.path.name for p in population
                           if flagged(lint(p), "awaiting-ci-clause"))
        self.assertEqual(offenders, ["workerMissingClause"])
        self.assertEqual(population[-1].path.name, "workerMissingClause",
                         "the offender must not be first, or M-35 is undetectable")

    def test_an_invocation_template_flag_whose_omission_changes_the_target_must_be_required(self):
        # FI-5 / RCF-B-8 / R5I-7, a LIVE open defect: a shared command "silently runs the base
        # branch's workflow definition unless --ref is passed", fixed in one instant's RUNBOOK and
        # still wrong in the shared profile. This is the first mechanical check for it.
        bad = load("invocationMissingRef")
        self.assertEqual(bad.invocation_templates,
                         ("gh workflow run velox-ci.yml -f build_type=release",))
        v = flagged(lint(bad), "invocation-target-flag")
        self.assertEqual(len(v), 1, [x.detail for x in v])
        self.assertIn("--ref", v[0].detail)
        self.assertIn("gh workflow run", v[0].detail)
        good = load("invocationWithRef")
        self.assertIn("--ref", good.invocation_templates[0])
        self.assertEqual(flagged(lint(good), "invocation-target-flag"), [])
        self.assertEqual(flagged(lint(load("compaction")), "invocation-target-flag"), [])

    def test_lint_reports_the_population_it_examined(self):
        # FR2-8.3 / OBS-49: a checker states what it looked at, so a scope that narrows cannot
        # read as a pass.
        out = lint(load("workerCompliant"))
        rows = [x for x in out if x.rule == "population"]
        self.assertEqual(len(rows), 1, [x.rule for x in out])
        self.assertEqual(rows[0].severity, "info")
        self.assertIn("charter.md", rows[0].detail)
        self.assertIn("seed.txt", rows[0].detail)

    def test_the_compliant_profiles_are_otherwise_clean(self):
        # Guards against a rule that fires on everything, which would make every case above
        # green for the wrong reason.
        for name in ("compaction", "workerCompliant", "invocationWithRef", "placeholders"):
            v = [x for x in lint(load(name)) if x.severity == "violation"]
            self.assertEqual(v, [], f"{name}: {[(x.rule, x.detail) for x in v]}")


class TestOptypeAgreement(unittest.TestCase):
    def test_agrees_with_optype_refuses_the_contradictions(self):
        # W2-13 / OBS-58: both flags that make a compaction a compaction defaulted wrong, on a path
        # taken ONCE, at a cap of 1, unrepairable by rename. So the contradictions must be refused,
        # and the agreements must still be accepted — a check that always says no is also useless.
        compaction = load("compaction")
        worker = load("workerCompliant")
        self.assertEqual(compaction.kind, "compaction")
        self.assertEqual(worker.kind, "worker")
        self.assertFalse(agrees_with_optype(compaction, "append"))
        self.assertFalse(agrees_with_optype(worker, "compact"))
        self.assertTrue(agrees_with_optype(compaction, "compact"))
        self.assertTrue(agrees_with_optype(worker, "append"))


if __name__ == "__main__":
    unittest.main()


class TestTheSHIPPEDProfilesSatisfyOurOwnRules(unittest.TestCase):
    """`FI-13` — `lint` is run against a user's profile and never against the ones fleet ships.

    `profiles.lint` mandates, unconditionally, that every worker-facing profile instruct the worker to run
    `fleet declare --instant <instant> --phase awaiting-ci` — and the rule's own comment says why it is unconditional: *"a
    profile that forgot the clause is exactly the profile that also forgot to require it."* Both profiles
    fleet SHIPS forgot it. Measured: 0 occurrences across `charter.md` and `seed.txt` for both `worker`
    and `compaction`.

    A rule a package states about itself and never checks against itself is a rule that has already
    drifted; the only question is when somebody notices. This is the check that makes it impossible to
    drift again, and it runs the SHIPPED `lint` rather than re-testing the condition, so a change to the
    rule reaches this case automatically.
    """

    SHIPPED = pathlib.Path(__file__).resolve().parents[2] / "skills" / "using-fleet" / "profiles"

    def test_every_shipped_profile_passes_fleet_s_own_lint(self):
        self.assertTrue(self.SHIPPED.is_dir(), f"the shipped profiles moved from {self.SHIPPED}")
        checked = 0
        for path in sorted(self.SHIPPED.iterdir()):
            if not path.is_dir():
                continue
            with self.subTest(profile=path.name):
                #: Severity `violation` only. `lint` also emits a `population` row, which is INFO and
                #: is the report saying what it examined — treating that as a failure would make this
                #: case red forever and it would be switched off, which is the always-red alarm
                #: `OBS-21` avoided.
                bad = [(v.rule, v.detail) for v in lint(Profile.load(path))
                       if getattr(v, "severity", "violation") == "violation"]
                self.assertEqual(bad, [], f"the SHIPPED {path.name} profile fails fleet's own lint")
                checked += 1
        self.assertGreaterEqual(checked, 3, "the shipped profile set shrank; this case now proves less")

    def test_the_shipped_set_still_contains_a_worker_facing_profile(self):
        """Non-vacuity. If every shipped profile stopped being worker-facing, the case above would pass
        while asserting nothing about the rule it exists for."""
        from fleet.profiles import WORKER_FACING
        kinds = {Profile.load(p).kind for p in sorted(self.SHIPPED.iterdir()) if p.is_dir()}
        self.assertTrue(kinds & set(WORKER_FACING),
                        f"no shipped profile is worker-facing any more; kinds are {sorted(kinds)}")
