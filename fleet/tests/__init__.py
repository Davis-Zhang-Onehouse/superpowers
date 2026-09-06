"""Shared fixture support for the hermetic suite.

One helper lives here, and it exists because the suite was measured NOT being hermetic. `cli.main` reads
`os.environ` at parse time — `require_named_instants` asks whether the caller named where instants go —
while a fixture states the same fact by handing `Ctx` an `instants_dir`. Those are two different tiers,
and nothing made them agree: 33 tests passed only because the operator's shell happened to export
`FLEET_HOME`, and the same tests failed inside `release-verify`, which runs with `env -u FLEET_HOME`.

A test that passes because of what the person running it exported is not measuring the product.
"""
import contextlib
import os
from unittest import mock

#: Every variable `cli` reads. Cleared as a SET rather than one at a time: the failure this file exists
#: to stop was one unlisted variable reaching a test, and a hand-maintained partial list is that failure
#: waiting to happen again.
FLEET_ENV = ("FLEET_HOME", "FLEET_INSTANTS", "FLEET_RELEASES", "FLEET_TMUX_SOCKET", "FLEET_ROOT")


@contextlib.contextmanager
def hermetic_environment(instants, home=None):
    """The environment a fixture-driven `cli.main` sees: this fixture's instants directory, and NOTHING
    the operator happened to export.

    It SETS `FLEET_INSTANTS` rather than merely clearing the rest, and that is the honest form: a real
    caller must name where instants are created, so a fixture that drives `dispatch` has to say it too.
    Saying it here — at the tier the guard actually reads — is what makes the fixture's `Ctx.instants_dir`
    and the parse-time check agree.

    `mock.patch.dict` restores deletions as well as assignments, so the operator's own environment is
    intact after the call.
    """
    with mock.patch.dict(os.environ, {}, clear=False):
        for name in FLEET_ENV:
            os.environ.pop(name, None)
        os.environ["FLEET_INSTANTS"] = str(instants)
        #: `$HOME` too, when the fixture has one to offer. It is not a `FLEET_` variable, but it decides
        #: the same kind of answer: `root.find` walks up to it and `root-init` refuses outside it, so a
        #: test that leaves it pointing at the operator's real home is measuring their box. The variable
        #: is only SET when a fixture names one, because most cases have no notion of a home directory and
        #: inventing one for them would be this file's own failure in the other direction.
        if home is not None:
            os.environ["HOME"] = str(home)
        yield
