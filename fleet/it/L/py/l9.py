"""L9 — the same advice in TWO documents ⇒ repetitions flags it at 2, with a citation per instance."""
import os
from pathlib import Path
from fleet.harvest import Harvest, Repetition
from fleet.errors import BadInput
EV = Path(os.environ["EV"])
h = Harvest(EV / "home-l9")
advice = "always re-derive the state from the join instead of trusting the board"
doc_a = (EV / "reg" / "l9-A.md"); doc_a.parent.mkdir(parents=True, exist_ok=True)
doc_b = (EV / "reg" / "l9-B.md")
doc_a.write_text(f"# DECISIONS\n\n## RI-5 {advice}\nsomething else entirely on this line\n")
doc_b.write_text(f"# HANDOFF\n\n- OI-9 {advice}\na different sentence that repeats nowhere\n")
corpus = {str(doc_a): doc_a.read_text(), str(doc_b): doc_b.read_text()}
reps = h.repetitions(corpus)
for r in reps:
    print("repetition:", r.count, "|", r.subject, "|", r.where)
hits = [r for r in reps if r.subject == advice]
assert len(hits) == 1, f"the repeated advice was not flagged once: {[r.subject for r in reps]}"
rep = hits[0]
assert rep.count == 2, f"count={rep.count}, expected 2 — the threshold IS two"
assert len(rep.where) == 2, f"citations={rep.where}"
assert {c.rsplit(':', 1)[0] for c in rep.where} == set(corpus), f"one citation per document: {rep.where}"
for citation in rep.where:
    path, _, line = citation.rpartition(":")
    text = Path(path).read_text().splitlines()[int(line) - 1]
    print("cited", citation, "->", text)
    assert advice in text, f"citation {citation} does not point at the advice"
try:
    Repetition(subject="x", count=2, where=[])
except BadInput as exc:
    print("uncited repetition refused:", str(exc)[:80])
else:
    raise AssertionError("a repetition with no citation was constructible")
try:
    h.repetitions(corpus, min_count=1)
except BadInput as exc:
    print("min_count=1 refused:", str(exc)[:80])
else:
    raise AssertionError("min_count=1 was accepted; a 'repetition' of one is an observation")
print("OK L9: the shared advice is flagged at count 2 with one verifiable citation per instance "
      "(the id prefix RI-5 vs OI-9 and the bullet/heading markers are normalised away)")
