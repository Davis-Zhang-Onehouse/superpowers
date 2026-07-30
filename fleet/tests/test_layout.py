import pathlib, tempfile, unittest
from fleet.identity import InstantName
from fleet.layout import (DUE_LATER, FORBIDDEN, OPTIONAL, REQUIRED, SPEC_VERSION,
                          bootstrap, requirement, validate)

CANONICAL = ("HANDOFF.md", "CHARTER.md", "RUNBOOK.md", "DECISIONS.md", "ISSUES.md", "ASSUMPTIONS.md")

class TestMatrix(unittest.TestCase):
    def test_the_six_canonical_files_are_required_in_every_cell(self):
        for state in ("inflight", "complete", "abort"):
            for optype in ("append", "compact"):
                for f in CANONICAL:
                    self.assertEqual(requirement(state, optype, f), REQUIRED, f"{state}/{optype}/{f}")

    def test_state_md_is_forbidden_in_every_cell(self):
        # FD-7 / operator Q12. Four consumers disagreed about this file: the bootstrap seeded it, the
        # format checklist forbade it, the skill folded it, and the review skill auto-fixed it away — so a
        # worker that followed the template it was given failed the gate it was held to (RCF-11).
        for state in ("inflight", "complete", "abort"):
            for optype in ("append", "compact"):
                self.assertEqual(requirement(state, optype, "STATE.md"), FORBIDDEN, f"{state}/{optype}")

    def test_compacted_md_is_state_scoped_and_abort_is_in_the_matrix(self):
        # W2-21: demanding it of any -compact- instant makes a correctly-running compaction lint RED for
        # its entire life. W2-21's own fix reached inflight/complete and never abort, and abort is legal.
        self.assertEqual(requirement("complete", "compact", "COMPACTED.md"), REQUIRED)
        self.assertEqual(requirement("inflight", "compact", "COMPACTED.md"), DUE_LATER)
        self.assertEqual(requirement("abort", "compact", "COMPACTED.md"), OPTIONAL)
        self.assertEqual(requirement("complete", "append", "COMPACTED.md"), FORBIDDEN)

    def test_an_earlier_spec_version_downgrades_a_requirement_to_info(self):
        # FR2-2.7 / OBS-9 generalised: greenfield removes today's legacy, not the NEXT spec change.
        self.assertEqual(requirement("complete", "compact", "COMPACTED.md", spec_version=0), OPTIONAL)

class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.name = InstantName.parse("00000000-07300312-inflight-append-someWork")
        self.instant = self.tmp / self.name.format()

    def test_bootstrap_creates_exactly_what_the_matrix_requires_and_validates_clean(self):
        made = bootstrap(self.instant, self.name)
        self.assertTrue(made)
        self.assertEqual([v for v in validate(self.instant) if v.severity == "violation"], [])

    def test_bootstrap_never_creates_state_md(self):
        bootstrap(self.instant, self.name)
        self.assertFalse((self.instant / "STATE.md").exists())

    def test_bootstrap_is_idempotent_and_does_not_clobber(self):
        bootstrap(self.instant, self.name)
        (self.instant / "CHARTER.md").write_text("MINE\n")
        bootstrap(self.instant, self.name)
        self.assertEqual((self.instant / "CHARTER.md").read_text(), "MINE\n")

class TestValidate(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def make(self, nm):
        name = InstantName.parse(nm)
        inst = self.tmp / nm
        bootstrap(inst, name)
        return inst

    def test_a_missing_canonical_file_is_a_violation_naming_the_file(self):
        inst = self.make("00000000-07300312-inflight-append-someWork")
        (inst / "RUNBOOK.md").unlink()
        v = [x for x in validate(inst) if x.severity == "violation"]
        self.assertEqual(len(v), 1)
        self.assertIn("RUNBOOK.md", v[0].detail)

    def test_a_present_state_md_is_a_violation(self):
        inst = self.make("00000000-07300312-inflight-append-someWork")
        (inst / "STATE.md").write_text("x")
        self.assertTrue(any("STATE.md" in x.detail and x.severity == "violation" for x in validate(inst)))

    def test_an_inflight_compaction_reports_info_not_a_violation(self):
        # The alarm that cannot be cleared, prevented: COMPACTED.md is written in the compaction's LAST
        # phase, so a running compaction must not be RED for its entire life.
        inst = self.make("00000000-07300312-inflight-compact-foldTheStack")
        out = validate(inst)
        self.assertEqual([x for x in out if x.severity == "violation"], [])
        self.assertTrue(any("COMPACTED.md" in x.detail and x.severity == "info" for x in out))

    def test_a_complete_compaction_without_its_defining_document_is_a_violation(self):
        inst = self.make("00000000-07300312-inflight-compact-foldTheStack")
        done = inst.parent / InstantName.parse(inst.name).with_state("complete").format()
        inst.rename(done)
        self.assertTrue(any("COMPACTED.md" in x.detail and x.severity == "violation" for x in validate(done)))

    def test_a_non_conforming_folder_name_is_refused_not_judged(self):
        # FD-1/FD-2: no legacy tolerance. A folder that is not an instant is not silently treated as one.
        from fleet.errors import InstantNameError
        bad = self.tmp / "main-07300312-inflight-append-legacy"
        bad.mkdir()
        with self.assertRaises(InstantNameError):
            validate(bad)

    def test_validate_reports_the_population_it_examined(self):
        # FR2-8.3 / OBS-49: a checker states what it looked at, so a scope that narrows cannot read as a pass.
        inst = self.make("00000000-07300312-inflight-append-someWork")
        self.assertTrue(any(x.rule == "population" for x in validate(inst)))
