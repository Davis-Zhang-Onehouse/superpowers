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
  * `<!--` … `-->` is a comment. One that STARTS a line (after at most 3 spaces) is an HTML block and
    spans lines until the first line containing `-->` (so an archival note can run on). One that starts
    mid-line must close on that line, or it is literal text. That is STRICTER than CommonMark, which lets
    an inline comment run on within its paragraph; the strict reading errs towards the gates SEEING a
    line, and it is what keeps a worker's "wrap it in `<!--`" from turning the rest of the document into
    a comment (RV, Task 1).
    A `<!--` inside a code span is literal. `<!-->` and `<!--->` are complete, empty comments. Inside a
    fence a comment opener is literal; inside a comment a fence opener is literal.
  * containers are not modelled: a fence indented 4+ spaces (inside a list item) or behind `> ` is prose
    to this reader, as CommonMark reads it outside its container. Pinned by a test so the limit is stated.
  * inline code (`…`) is NOT an enclosure. A code span is how a live pointer is usually written, and the
    near-miss rule deliberately matches through backticks (IT G3/G4). Consumers see it as prose.

A PROSE line's `text` has its comment portions removed; its `raw` is untouched, so a consumer that wants
to read a token INSIDE a comment (a retraction, an exemption marker) still can. Lines are split on `\n`
only (a stray form feed is not a line break to an editor or to grep), so `number` is the number a reader
sees.
"""
import re
from dataclasses import dataclass

PROSE = "prose"
FENCE = "fence"
COMMENT = "comment"

_FENCE_LINE = re.compile(r"^ {0,3}(?P<run>`{3,}|~{3,})(?P<info>.*)$")
_BLOCK_COMMENT = re.compile(r"^ {0,3}<!--")
_BACKTICK_RUN = re.compile(r"`+")
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


def _split(text: str) -> list:
    """Lines the way an editor or `grep -n` counts them: on `\n` only, a trailing `\r` dropped."""
    parts = [part[:-1] if part.endswith("\r") else part for part in str(text).split("\n")]
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _comment_close(s: str, opener: int) -> int:
    """Index of the `-->` that closes the comment opened at `opener`, or -1. Searched from two characters
    past the opener so `<!-->` and `<!--->` — complete, empty comments — close on their own dashes."""
    return s.find(_COMMENT_CLOSE, opener + 2)


def _code_span_end(s: str, tick: int) -> int:
    """End index of the code span whose opening backtick run starts at `tick`, or -1 when no run of exactly
    the same length follows (then the run is literal backticks)."""
    n = len(_BACKTICK_RUN.match(s, tick).group(0))
    for match in _BACKTICK_RUN.finditer(s, tick + n):
        if len(match.group(0)) == n:
            return match.end()
    return -1


def _strip_inline_comments(s: str) -> str:
    """`s` with every complete inline comment removed. A `<!--` inside a code span is literal, an opener
    with no `-->` on the line is literal, and a code span's contents are kept whole."""
    out, i = [], 0
    while i < len(s):
        tick, opener = s.find("`", i), s.find(_COMMENT_OPEN, i)
        if opener < 0:
            out.append(s[i:])
            break
        if 0 <= tick < opener:
            end = _code_span_end(s, tick)
            if end < 0:
                run_end = _BACKTICK_RUN.match(s, tick).end()
                out.append(s[i:run_end])
                i = run_end
            else:
                out.append(s[i:end])
                i = end
            continue
        close = _comment_close(s, opener)
        if close < 0:
            out.append(s[i:])
            break
        out.append(s[i:opener])
        i = close + len(_COMMENT_CLOSE)
    return "".join(out)


def _after_block_close(number: int, raw: str, rest: str) -> Line:
    """The line on which a block comment closes: whatever follows `-->` is prose, or nothing is."""
    stripped = _strip_inline_comments(rest)
    if stripped.strip():
        return Line(number, raw, stripped, PROSE)
    return Line(number, raw, "", COMMENT)


def lines(text: str) -> list:
    """Every line of `text`, in order, classified."""
    out = []
    fence_char, fence_len, lang, block = "", 0, "", -1
    in_block_comment = False
    for number, raw in enumerate(_split(text), start=1):
        if fence_char:
            match = _FENCE_LINE.match(raw)
            closes = (match is not None and match.group("run")[0] == fence_char
                      and len(match.group("run")) >= fence_len and not match.group("info").strip())
            out.append(Line(number, raw, raw, FENCE, lang, block, boundary=closes))
            if closes:
                fence_char = ""
            continue
        if in_block_comment:
            end = raw.find(_COMMENT_CLOSE)
            if end < 0:
                out.append(Line(number, raw, "", COMMENT))
                continue
            in_block_comment = False
            out.append(_after_block_close(number, raw, raw[end + len(_COMMENT_CLOSE):]))
            continue
        match = _FENCE_LINE.match(raw)
        if match is not None and not (match.group("run")[0] == "`" and "`" in match.group("info")):
            fence_char, fence_len = match.group("run")[0], len(match.group("run"))
            lang = (match.group("info").split() or [""])[0].lower()
            block += 1
            out.append(Line(number, raw, raw, FENCE, lang, block, boundary=True))
            continue
        if _BLOCK_COMMENT.match(raw):
            close = _comment_close(raw, raw.index(_COMMENT_OPEN))
            if close < 0:
                in_block_comment = True
                out.append(Line(number, raw, "", COMMENT))
                continue
            out.append(_after_block_close(number, raw, raw[close + len(_COMMENT_CLOSE):]))
            continue
        out.append(Line(number, raw, _strip_inline_comments(raw), PROSE))
    return out


def prose(text: str) -> list:
    """The PROSE lines only — what a gate that looks for a live pointer or a declaration reads."""
    return [line for line in lines(text) if line.enclosure == PROSE]


def fenced(text: str, langs=None) -> list:
    """Fenced CONTENT lines (never an opener or closer), optionally only those in `langs`."""
    if isinstance(langs, str):
        langs = (langs,)
    wanted = None if langs is None else {str(lang).lower() for lang in langs}
    return [line for line in lines(text)
            if line.enclosure == FENCE and not line.boundary and (wanted is None or line.lang in wanted)]
