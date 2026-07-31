"""A8 — the audit of the harness itself. Classified by lexing the shell, not by grepping the text.

Three greps were tried first and all three failed the same way: they judged PROSE. `grep -nE 'git
+(push|merge)'` matched this runner's own comment describing the pattern and its own pass-note saying
"no git push"; the rm-target grep, run against a quote-stripped line, reported `;;` as the target of
`rm -rf "$A_EVDIR"`. Whether a line PUSHES is a question about code, and the only way to ask it is to
know which characters the shell would run as words and which it would pass as data.

So one scan produces two renderings of every line:

  `code`   — what the shell RUNS. Quoted spans collapse to a token (`<V>` if the span began with `$`,
             else `<L>`), and a `$( ... )` substitution is code again even inside double quotes, which
             is exactly where the false positives lived.
  `masked` — the same, but each token carries its content, so a write TARGET (almost always quoted) is
             still readable.

Heredoc bodies are DATA and are skipped, counted rather than silently dropped: every runner here embeds
python that way, including this audit, whose regexes contain the very strings it searches for. The one
thing this cannot see is a heredoc written out as a script and then executed; no runner does that.
"""
import json, os, re, sys

FORBIDDEN = [
    (re.compile(r"\bgit\s+(push|merge)\b"), "git push/merge"),
    (re.compile(r"\bgh\s+pr\s+merge\b"), "gh pr merge"),
    (re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+(\$HOME|~(/|\s|$)|/home/[a-z]+\s*$)"), "rm -rf home"),
]
KILL = re.compile(r"tmux[^;&|]*kill-(server|session)")
RM_CMD = re.compile(r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*r[a-zA-Z]*\b")
RM_TGT = re.compile(r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*r[a-zA-Z]*\s+(?P<target>\S+)")
WRITE_OUT = re.compile(r"(>>?|tee)\s*<\$?(IT_ROOT|LIVE_TMUX_SNAPSHOT|RESULTS|LIVE_SNAPSHOT)\b"
                       r"|(>>?|tee)\s*<\$(IT_ROOT|LIVE_TMUX_SNAPSHOT|RESULTS|LIVE_SNAPSHOT)")
TMPDIR = re.compile(r"\bmktemp\b|\$TMPDIR|(^|[\s<(=])/tmp/")
HEREDOC = re.compile(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")


def lex(line):
    """-> (code, masked, comment_stripped_raw). A tiny context stack, not a full shell parser."""
    code, masked, plain = [], [], []
    stack = ["CODE"]          # CODE | DQ | SQ | CS(=command substitution, code again)
    span = []
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        top = stack[-1]
        if top == "CODE" or top == "CS":
            if ch == "#" and top == "CODE":
                break                                   # a top-level comment; the rest is prose
            if line.startswith("$(", i):
                stack.append("CS"); code.append("$("); masked.append("$("); plain.append("$(")
                i += 2; continue
            if ch == ")" and top == "CS":
                stack.pop(); code.append(")"); masked.append(")"); plain.append(")")
                i += 1; continue
            if ch in "\"'":
                stack.append("DQ" if ch == '"' else "SQ"); span = []
                plain.append(ch); i += 1; continue
            code.append(ch); masked.append(ch); plain.append(ch); i += 1; continue
        # inside a quoted span
        if top == "DQ" and line.startswith("$(", i):
            # a substitution inside a string: flush what we have as a token, then lex code again
            token = "".join(span)
            code.append("<V>" if token.startswith("$") else "<L>")
            masked.append("<" + token + ">")
            span = []
            stack.append("CS"); code.append("$("); masked.append("$("); plain.append("$(")
            i += 2; continue
        if (top == "DQ" and ch == '"') or (top == "SQ" and ch == "'"):
            stack.pop()
            token = "".join(span)
            code.append("<V>" if token.startswith("$") else "<L>")
            masked.append("<" + token + ">")
            plain.append(ch); span = []
            i += 1; continue
        span.append(ch); plain.append(ch); i += 1
    return "".join(code), "".join(masked), "".join(plain)


report = {"forbidden": [], "kill_unsafe": [], "kill_all": [], "rm_all": [], "rm_unrooted": [],
          "writes_outside": [], "writes_tmpdir": [], "files": 0, "heredoc_data_lines": 0}
for path in sys.argv[1:]:
    report["files"] += 1
    name = os.path.basename(path)
    pending = None
    for lineno, raw in enumerate(open(path, encoding="utf-8", errors="replace"), start=1):
        raw = raw.rstrip("\n")
        if pending is not None:
            report["heredoc_data_lines"] += 1
            if raw.strip() == pending:
                pending = None
            continue
        code, masked, plain = lex(raw)
        where = f"{name}:{lineno}"
        for pattern, label in FORBIDDEN:
            if pattern.search(code):
                report["forbidden"].append(f"{where} [{label}] {code.strip()[:120]}")
        if KILL.search(code):
            report["kill_all"].append(f"{where} {masked.strip()[:130]}")
            # Safe iff it names a private server: `-L <socket>`, or `it_tmux` — lib.sh's wrapper, which
            # refuses outright when no section has been entered and so cannot reach the default server.
            if not re.search(r"tmux\s+-L\b", code) and not re.search(r"\bit_tmux\b", code):
                report["kill_unsafe"].append(f"{where} {masked.strip()[:130]}")
        if RM_CMD.search(code):
            m = RM_TGT.search(masked)
            target = m.group("target") if m else "(none)"
            report["rm_all"].append(f"{where} target={target}")
            rooted = target.startswith("<$") or target.startswith("$")
            # `find <$DIR> ... -exec rm -rf {} +`: the target is find's own substitution and the bound is
            # find's START PATH, so the question moves one argument left rather than disappearing.
            if not rooted and target.startswith("{}") and re.search(r"\bfind\s+<\$", masked):
                rooted = True
            if not rooted:
                report["rm_unrooted"].append(f"{where} target={target} :: {masked.strip()[:110]}")
        if WRITE_OUT.search(masked):
            report["writes_outside"].append(f"{where} {masked.strip()[:130]}")
        if TMPDIR.search(masked):
            report["writes_tmpdir"].append(f"{where} {masked.strip()[:130]}")
        # On `plain` (comment stripped, quotes KEPT) and never on `code`: in `code` two adjacent quoted
        # spans render as `<V><L>`, whose `<<` opened a phantom heredoc with tag `L` that swallowed 2500
        # lines of three runners — an audit that silently stops reading is the OBS-49 shape, so the
        # skipped-line count is printed and was what made this visible.
        m_here = HEREDOC.search(plain)
        if m_here:
            pending = m_here.group(1)

print(f"=== heredoc data lines skipped: {report['heredoc_data_lines']}")
for key in ("forbidden", "kill_all", "kill_unsafe", "rm_all", "rm_unrooted",
            "writes_outside", "writes_tmpdir"):
    print(f"=== {key} ({len(report[key])})")
    for row in report[key]:
        print("   ", row)
print("COUNTS " + json.dumps({k: (v if isinstance(v, int) else len(v)) for k, v in report.items()}))
