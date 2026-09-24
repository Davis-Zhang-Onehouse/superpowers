"""`fleet.markdown` — the ONE enclosure-aware reader for the markdown fleet reads (B19).

Two gates used to scan `HANDOFF.md` line by line with no fence / comment state, so a path QUOTED inside a
```bash block refused `complete` (rc=4) and a `Phase: AWAITING-CI` quoted inside a ```markdown block was a
lint violation. `recipes_of` and `lint-skill.py` each carried a private fence tracker. This module is the
single copy, and these tests pin the grammar every consumer now shares.
"""
import unittest

from fleet.markdown import COMMENT, FENCE, PROSE, fenced, lines, prose


class TestFences(unittest.TestCase):

    def test_a_backtick_fence_encloses_its_content_and_carries_its_language(self):
        rows = lines("before\n```bash\necho hi\n```\nafter\n")
        self.assertEqual([r.enclosure for r in rows], [PROSE, FENCE, FENCE, FENCE, PROSE])
        self.assertEqual([r.boundary for r in rows], [False, True, False, True, False])
        self.assertEqual(rows[2].lang, "bash")
        self.assertEqual(rows[2].block, 0)
        self.assertEqual([r.number for r in rows], [1, 2, 3, 4, 5])

    def test_a_tilde_fence_is_a_fence_too(self):
        rows = lines("~~~\nx\n~~~\n")
        self.assertEqual([r.enclosure for r in rows], [FENCE, FENCE, FENCE])
        self.assertEqual(rows[1].lang, "")

    def test_the_info_string_first_word_is_the_language_lowercased(self):
        rows = lines("```Bash title=x\nls\n```\n")
        self.assertEqual(rows[1].lang, "bash")

    def test_a_shorter_backtick_run_inside_a_longer_fence_is_content(self):
        rows = lines("````md\n```\ninner\n```\n````\nout\n")
        self.assertEqual([r.enclosure for r in rows], [FENCE] * 5 + [PROSE])
        self.assertEqual([r.boundary for r in rows], [True, False, False, False, True, False])

    def test_a_closer_must_be_the_same_character(self):
        rows = lines("```\n~~~\nstill inside\n```\n")
        self.assertEqual([r.enclosure for r in rows], [FENCE] * 4)
        self.assertEqual(rows[1].boundary, False)

    def test_a_closer_carries_no_info_string(self):
        rows = lines("```\n```bash\nstill inside\n```\n")
        self.assertEqual([r.enclosure for r in rows], [FENCE] * 4)
        self.assertEqual(rows[1].boundary, False)

    def test_an_unclosed_fence_runs_to_end_of_file(self):
        rows = lines("```\none\ntwo\n")
        self.assertEqual([r.enclosure for r in rows], [FENCE] * 3)

    def test_up_to_three_leading_spaces_still_open_a_fence(self):
        self.assertEqual(lines("   ```\nx\n   ```\n")[1].enclosure, FENCE)
        self.assertEqual(lines("    ```\nx\n")[0].enclosure, PROSE)

    def test_blocks_are_numbered_in_file_order(self):
        rows = lines("```a\n1\n```\n```b\n2\n```\n")
        self.assertEqual([r.block for r in rows if not r.boundary], [0, 1])

    def test_fenced_returns_content_lines_of_the_named_languages_only(self):
        text = "```bash\nls\n```\n```markdown\nPhase: X\n```\n```\nplain\n```\n"
        self.assertEqual([r.raw for r in fenced(text)], ["ls", "Phase: X", "plain"])
        self.assertEqual([r.raw for r in fenced(text, ("bash", "sh"))], ["ls"])

    def test_fenced_accepts_a_single_language_as_a_string(self):
        text = "```bash\nls\n```\n```sh\npwd\n```\n"
        self.assertEqual([r.raw for r in fenced(text, "bash")], ["ls"])

    def test_a_backtick_opener_whose_info_string_holds_a_backtick_is_not_a_fence(self):
        rows = lines("``` `x` ```\nnext\n")
        self.assertEqual([r.enclosure for r in rows], [PROSE, PROSE])

    def test_a_tilde_fence_closes_on_a_longer_run_and_a_closer_may_carry_trailing_spaces(self):
        self.assertEqual([r.enclosure for r in lines("~~~\nx\n~~~~\nafter\n")], [FENCE, FENCE, FENCE, PROSE])
        self.assertEqual([r.enclosure for r in lines("```\nx\n```   \nafter\n")], [FENCE, FENCE, FENCE, PROSE])

    def test_a_fence_indented_four_spaces_is_prose_to_this_reader(self):
        """The stated limit: containers (a list item, a blockquote) are not modelled, so a fence inside
        one is read as CommonMark reads it outside its container — an indented code block, i.e. prose
        here. A quotation written that way is still seen by the gates (ISSUES: routed)."""
        rows = lines("1. step\n    ```bash\n    cat /abs/x\n    ```\n")
        self.assertEqual([r.enclosure for r in rows], [PROSE] * 4)

    def test_line_numbers_follow_newlines_only(self):
        """`str.splitlines` also breaks on a form feed and friends; an editor and `grep -n` do not, and
        the numbers this reader reports are the ones a reader looks up."""
        self.assertEqual([r.number for r in lines("a\x0cb\nc")], [1, 2])
        self.assertEqual([r.raw for r in lines("a\r\nb\r\n")], ["a", "b"])


class TestComments(unittest.TestCase):

    def test_an_inline_comment_is_removed_from_prose_text(self):
        (row,) = lines("see evidence/INDEX.md <!-- and /abs/instant/x -->\n")
        self.assertEqual(row.enclosure, PROSE)
        self.assertEqual(row.text, "see evidence/INDEX.md ")
        self.assertIn("/abs/instant/x", row.raw)

    def test_a_whole_line_comment_is_a_comment_line(self):
        (row,) = lines("<!-- archival: /abs/instant/ -->\n")
        self.assertEqual(row.enclosure, COMMENT)
        self.assertEqual(row.text, "")

    def test_a_multi_line_comment_encloses_every_line_until_it_closes(self):
        rows = lines("a\n<!-- one\ntwo\nthree --> tail\nb\n")
        self.assertEqual([r.enclosure for r in rows], [PROSE, COMMENT, COMMENT, PROSE, PROSE])
        self.assertEqual(rows[3].text, " tail")

    def test_two_comments_on_one_line_are_both_removed(self):
        (row,) = lines("x <!-- a --> y <!-- b --> z\n")
        self.assertEqual(row.text, "x  y  z")

    def test_a_comment_opener_inside_a_fence_is_literal(self):
        rows = lines("```\n<!-- not a comment\n```\nprose\n")
        self.assertEqual([r.enclosure for r in rows], [FENCE, FENCE, FENCE, PROSE])

    def test_a_fence_opener_inside_a_comment_is_literal(self):
        rows = lines("<!--\n```\n-->\nprose\n")
        self.assertEqual([r.enclosure for r in rows], [COMMENT, COMMENT, COMMENT, PROSE])

    def test_an_unclosed_comment_runs_to_end_of_file(self):
        rows = lines("<!-- open\nstill\n")
        self.assertEqual([r.enclosure for r in rows], [COMMENT, COMMENT])

    def test_an_unclosed_inline_opener_is_literal_text(self):
        """RV (Task 1): a mid-line `<!--` with no `-->` on its line used to turn the REST OF THE FILE into
        COMMENT, so every later pointer vanished from the gate and every later near-miss from the lint.
        CommonMark: an inline comment must close on its line; only a comment that starts a line spans."""
        rows = lines("Wrap it in <!-- like this.\nRead /abs/instant/evidence/INDEX.md\n")
        self.assertEqual([r.enclosure for r in rows], [PROSE, PROSE])
        self.assertIn("<!--", rows[0].text)
        self.assertIn("/abs/instant/evidence/INDEX.md", rows[1].text)

    def test_a_comment_opener_inside_a_code_span_is_literal(self):
        rows = lines("Wrap it in `<!--` like this.\n\nRead /abs/instant/x\nPhase: X\n")
        self.assertEqual([r.enclosure for r in rows], [PROSE, PROSE, PROSE, PROSE])
        self.assertEqual(rows[0].text, "Wrap it in `<!--` like this.")

    def test_a_double_backtick_span_holding_a_single_backtick_and_an_opener_is_literal(self):
        (row,) = lines("use `` ` <!-- `` here <!-- gone -->!\n")
        self.assertEqual(row.text, "use `` ` <!-- `` here !")

    def test_an_inline_comment_may_contain_backticks(self):
        (row,) = lines("a <!-- `x` --> b\n")
        self.assertEqual(row.text, "a  b")

    def test_the_empty_comment_forms_close_on_their_own_dashes(self):
        rows = lines("x <!--> y\nz\n<!--->\nw\n")
        self.assertEqual([r.enclosure for r in rows], [PROSE, PROSE, COMMENT, PROSE])
        self.assertEqual(rows[0].text, "x  y")

    def test_a_block_comment_closes_on_the_first_line_containing_the_closer(self):
        rows = lines("<!-- a\n b --> tail <!-- c --> more\nnext\n")
        self.assertEqual([r.enclosure for r in rows], [COMMENT, PROSE, PROSE])
        self.assertEqual(rows[1].text, " tail  more")

    def test_a_fence_may_open_right_after_a_block_comment_closes(self):
        rows = lines("<!-- a\n-->\n```\nx\n```\n")
        self.assertEqual([r.enclosure for r in rows], [COMMENT, COMMENT, FENCE, FENCE, FENCE])


class TestProse(unittest.TestCase):

    def test_prose_returns_prose_lines_with_their_original_numbers(self):
        rows = prose("one\n```\nfenced\n```\n<!-- c -->\nfive\n")
        self.assertEqual([(r.number, r.text) for r in rows], [(1, "one"), (6, "five")])

    def test_a_blank_line_is_prose(self):
        self.assertEqual(lines("\n")[0].enclosure, PROSE)

    def test_inline_code_is_not_an_enclosure(self):
        """A code span is how a live pointer is written (`Read \\`…/INDEX.md\\``), and IT G3/G4 pin the
        backticked near-miss rendering as a finding. Inline code stays prose (DECISIONS D-2)."""
        (row,) = prose("Read `/abs/instant/evidence/INDEX.md` first.\n")
        self.assertIn("/abs/instant/evidence/INDEX.md", row.text)


if __name__ == "__main__":
    unittest.main()
