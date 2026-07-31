"""M3 — every declared long flag appears in that verb's usage (usage is DERIVED from VERBS)."""
from fleet.cli import VERBS, usage
bad = []
for name, spec in sorted(VERBS.items()):
    text = usage(name)
    for flag in spec.flags:
        if flag.name not in text:
            bad.append(f"{name}: {flag.name} missing from usage")
        if flag.takes_value and f"{flag.name} <value>" not in text:
            bad.append(f"{name}: {flag.name} documented without its value")
        if flag.required and "(required)" not in text:
            bad.append(f"{name}: {flag.name} is required and usage says nothing")
    print(f"{name}: {len(spec.flags)} flag(s) all present")
assert not bad, "\n".join(bad)
print(f"OK M3: every declared flag of all {len(VERBS)} verbs appears in its own usage, "
      "with its value form and required marker")
