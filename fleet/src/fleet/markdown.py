"""The ONE enclosure-aware reader for the markdown fleet reads.

`B19`. Two gates scanned `HANDOFF.md` line by line with no fence / comment state: `complete`'s pointer gate
refused an instant whose only absolute self-reference was a QUOTATION inside a ```bash block (rc=4), and
`lint`'s near-miss rule flagged a `Phase: AWAITING-CI` quoted inside a ```markdown block introduced by
"what NOT to do" (rc=1). Meanwhile `recipes_of` and `skills/using-fleet/tools/lint-skill.py` each carried
a private fence tracker. Four consumers, two techniques, two of them missing: this module is the single
copy, and every consumer reads through it.

Grammar (CommonMark, the subset that matters here):
  * a fence opens on a line of 3+ backticks or 3+ tildes after at most 3 spaces; the rest of the line is
    the info string, whose first word is the language. A backtick fence's info string may not contain a
    backtick (so ``` `x` ``` inline code on its own line is not an opener).
  * it closes on a line of the SAME character, at least as long, with nothing after it. Anything else —
    a shorter run, the other character, a run with an info string — is content. An unclosed fence runs
    to the end of the file.
  * `<!--` … `-->` is a comment, possibly spanning lines. Inside a fence it is literal; inside a comment a
    fence opener is literal.
  * inline code (`…`) is NOT an enclosure. A code span is how a live pointer is usually written, and the
    near-miss rule deliberately matches through backticks (IT G3/G4). Consumers see it as prose.

A PROSE line's `text` has its comment portions removed; its `raw` is untouched, so a consumer that wants
to read a token INSIDE a comment (a retraction, an exemption marker) still can.
"""
import re
from dataclasses import dataclass

PROSE = "prose"
FENCE = "fence"
COMMENT = "comment"

_FENCE_LINE = re.compile(r"^ {0,3}(?P<run>`{3,}|~{3,})(?P<info>.*)$")
_COMMENT_OPEN = "<!--"
_COMMENT_CLOSE = "-->"


@dataclass(frozen=True)
class Line:
    number: int
    raw: str
    text: str
    enclosure: str
    lang: str = ""
    block: int = -1
    boundary: bool = False


def _strip_comments(raw: str, open_already: bool):
    """`(text, still_open)`: the line with every comment portion removed, and whether a comment is open
    at the end of it. `open_already` says the line starts inside a comment."""
    text, rest, open_now = "", raw, open_already
    while rest:
        if open_now:
            end = rest.find(_COMMENT_CLOSE)
            if end < 0:
                return text, True
            rest, open_now = rest[end + len(_COMMENT_CLOSE):], False
            continue
        start = rest.find(_COMMENT_OPEN)
        if start < 0:
            return text + rest, False
        text, rest, open_now = text + rest[:start], rest[start + len(_COMMENT_OPEN):], True
    return text, open_now


def lines(text: str) -> list:
    """Every line of `text`, in order, classified."""
    out = []
    fence_char, fence_len, lang, block = "", 0, "", -1
    in_comment = False
    for number, raw in enumerate(str(text).splitlines(), start=1):
        if fence_char:
            match = _FENCE_LINE.match(raw)
            closes = (match is not None and match.group("run")[0] == fence_char
                      and len(match.group("run")) >= fence_len and not match.group("info").strip())
            out.append(Line(number, raw, raw, FENCE, lang, block, boundary=closes))
            if closes:
                fence_char = ""
            continue
        if in_comment:
            stripped, in_comment = _strip_comments(raw, True)
            enclosure = PROSE if stripped.strip() else COMMENT
            out.append(Line(number, raw, stripped if enclosure == PROSE else "", enclosure))
            continue
        match = _FENCE_LINE.match(raw)
        if match is not None and not (match.group("run")[0] == "`" and "`" in match.group("info")):
            fence_char, fence_len = match.group("run")[0], len(match.group("run"))
            lang = (match.group("info").split() or [""])[0].lower()
            block += 1
            out.append(Line(number, raw, raw, FENCE, lang, block, boundary=True))
            continue
        stripped, in_comment = _strip_comments(raw, False)
        if stripped != raw and not stripped.strip():
            out.append(Line(number, raw, "", COMMENT))
        else:
            out.append(Line(number, raw, stripped, PROSE))
    return out


def prose(text: str) -> list:
    """The PROSE lines only — what a gate that looks for a live pointer or a declaration reads."""
    return [line for line in lines(text) if line.enclosure == PROSE]


def fenced(text: str, langs=None) -> list:
    """Fenced CONTENT lines (never an opener or closer), optionally only those in `langs`."""
    wanted = None if langs is None else {str(lang).lower() for lang in langs}
    return [line for line in lines(text)
            if line.enclosure == FENCE and not line.boundary and (wanted is None or line.lang in wanted)]
