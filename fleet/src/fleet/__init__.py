"""fleet — agent-fleet infrastructure.

Built because the predecessor carried five machine-consumed control signals in markdown prose and matched
them with regexes; each was patched at the instance and recurred at a different instance of the same class
within days to weeks (RCF-9, OBS-53, OBS-64, RCF-10, RCF-11). Two recurrences cost more than the original.
Structured state is the source of truth here; markdown is generated.
"""
__version__ = "0.4.0"

EXIT_OK = 0
EXIT_ATTENTION = 1
EXIT_BAD_INPUT = 2
EXIT_NO_CAPACITY = 3
EXIT_REFUSED = 4

# The ONE registry. A verb returning a code absent from here fails the suite (NFR2-8): a tick that
# branches on an exit code must be told when a new one appears.
EXIT_CODES = {
    EXIT_OK: "ok",
    EXIT_ATTENTION: "needs attention / check failed",
    EXIT_BAD_INPUT: "bad input",
    EXIT_NO_CAPACITY: "no capacity",
    EXIT_REFUSED: "refused by an admission rule",
}
