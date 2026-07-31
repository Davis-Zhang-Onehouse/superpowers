"""The exception hierarchy. Each maps to exactly one registered exit code, so a caller can tell a refusal
(4) from bad input (2) from a full pool (3) — the distinction OI-3 showed a test cannot make when two
mechanisms produce one non-zero class."""
from fleet import EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_NO_CAPACITY, EXIT_REFUSED


class FleetError(Exception):
    exit_code = EXIT_ATTENTION


class BadInput(FleetError):
    exit_code = EXIT_BAD_INPUT


class NoCapacity(FleetError):
    exit_code = EXIT_NO_CAPACITY


class Refused(FleetError):
    """An admission rule said no. Carries the clearing condition and the clearing ACTOR, because
    'not yours to clear' is a state and not a failure (RI-31)."""

    exit_code = EXIT_REFUSED

    def __init__(self, message, *, clears_when=None, clears_who=None):
        super().__init__(message)
        self.clears_when = clears_when
        self.clears_who = clears_who


class AmbiguousId(BadInput):
    """Refused rather than resolved. Every time this toolkit picked a winner from an ambiguous key it
    eventually picked a sibling's record (OBS-14)."""


class InstantNameError(BadInput):
    pass
