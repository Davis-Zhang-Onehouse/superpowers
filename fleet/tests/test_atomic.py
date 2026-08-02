"""The ONE atomic write, and the one thing a hermetic suite normally cannot test.

`NFR2-3` makes every probe in this package injectable so a suite can describe a whole fleet without owning
one — which is exactly why 612 hermetic tests could not see `FI-20`. A race is a property of concurrent
processes, and injected probes have none. So the cases here spawn **real processes** and race them, the same
licence `test_pool.TestClaimIsAtomicUnderConcurrency` already takes for `mkdir`-as-the-lock.

What is being killed here is a mutation that no single-threaded case can distinguish: restoring the staging
path that eight sites derived from their target (`path.with_suffix(".json.tmp")`) passes every sequential
assertion about atomic write, byte for byte. It fails only when two writers meet.
"""
import json
import multiprocessing as mp
import os
import pathlib
import shutil
import tempfile
import threading
import unittest

from fleet.atomic import TMP_SUFFIX, atomic_update, atomic_write, tmp_name

#: Big enough that a partial write is not one page and therefore not accidentally atomic. A 40-byte
#: document lands in a single write(2) whatever the code does, so a torn read is unobservable and the case
#: would pass against the defect — the shape of assertion this build has filed three times (`OBS-50`).
_PAYLOAD_BYTES = 400_000


def _doc(tag: str) -> str:
    return json.dumps({"writer": tag, "filler": tag * (_PAYLOAD_BYTES // max(1, len(tag)))})


def _write_many(args):
    """One writer process: publish the same target N times, then report."""
    target, tag, rounds = args
    for _ in range(rounds):
        atomic_write(pathlib.Path(target), _doc(tag))
    return tag


def _read_many(args):
    """One reader process: read the target repeatedly and report every document it could NOT parse."""
    target, rounds = args
    path = pathlib.Path(target)
    bad = []
    for _ in range(rounds):
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            bad.append("missing")
            continue
        except ValueError as exc:
            bad.append(f"torn: {type(exc).__name__}: {exc}")
            continue
        if data.get("writer") not in ("A", "B", "C", "D"):
            bad.append(f"mixed: writer={data.get('writer')!r}")
    return bad


def _add_entry(args):
    """One updater process: add its own entry to a shared registry, read-modify-write."""
    target, tag = args

    def mutate(current):
        data = json.loads(current) if current else {"entries": []}
        data["entries"].append(tag)
        return json.dumps(data), tag

    return atomic_update(pathlib.Path(target), mutate)


class TestAtomicWriteIsUniquePerWriter(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-atomic-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_staging_name_is_not_a_function_of_the_target(self):
        """The whole defect in one assertion: eight sites derived the tmp name from the target, so two
        writers of one file shared one staging path."""
        names = {tmp_name("x.json") for _ in range(200)}
        self.assertEqual(len(names), 200, "two staging names collided for one target")
        for name in names:
            self.assertTrue(name.endswith(".tmp"), name)
            self.assertNotEqual(name, "x.json.tmp",
                                "the staging name is derived from the target — FI-20 restored")

    def test_a_write_leaves_no_staging_file_behind(self):
        target = self.tmp / "sub" / "rec.json"
        atomic_write(target, '{"ok": true}')
        self.assertEqual(json.loads(target.read_text()), {"ok": True})
        self.assertEqual([p.name for p in target.parent.iterdir()], ["rec.json"])

    def test_a_failed_write_publishes_nothing_and_leaves_no_litter(self):
        target = self.tmp / "rec.json"
        atomic_write(target, '{"first": true}')

        # A lone surrogate cannot be encoded, so the failure happens INSIDE the staged write — after the
        # staging file exists and before anything is published, which is the window that matters.
        with self.assertRaises(UnicodeEncodeError):
            atomic_write(target, "\ud800")
        self.assertEqual(json.loads(target.read_text()), {"first": True},
                         "a failed write published something")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["rec.json"],
                         "a failed write left a staging file for the next reader to trip over")

    def test_concurrent_writers_never_publish_a_torn_or_mixed_document(self):
        """Real processes, because this is unobservable without them (`FI-20`).

        Restoring the shared staging path makes this fail three ways at once — a reader parsing half a
        document, a reader finding the file missing between somebody's write and somebody's replace, and a
        writer raising `FileNotFoundError` out of `replace` because another writer's `replace` consumed the
        staging file it was about to publish.
        """
        target = self.tmp / "contended.json"
        atomic_write(target, _doc("A"))
        ctx = mp.get_context("fork")
        with ctx.Pool(6) as procs:
            jobs = [(str(target), tag, 12) for tag in ("A", "B", "C", "D")]
            reads = [(str(target), 60), (str(target), 60)]
            writers = procs.map_async(_write_many, jobs)
            readers = procs.map_async(_read_many, reads)
            writers.get(120)
            problems = [p for batch in readers.get(120) for p in batch]
        self.assertEqual(problems, [], f"a reader saw a document no writer ever published: {problems[:5]}")

    def test_concurrent_read_modify_writes_lose_nothing(self):
        """`atomic_write` is not enough on its own, and this is the difference.

        E7 measured it: two dispatches for different bases, each reading an empty registry, each appending
        its own base, each publishing — 20 of 20 iterations ended with ONE base watched. No torn byte
        anywhere; the other effort was simply unwatched, which is `OBS-68`'s exact structure.
        """
        target = self.tmp / "registry.json"
        tags = [f"base{i:02d}" for i in range(8)]
        ctx = mp.get_context("fork")
        with ctx.Pool(8) as procs:
            got = procs.map(_add_entry, [(str(target), tag) for tag in tags])
        self.assertEqual(sorted(got), sorted(tags), "an updater did not report its own entry")
        entries = json.loads(target.read_text())["entries"]
        self.assertEqual(sorted(entries), sorted(tags),
                         f"a concurrent read-modify-write lost an entry: {sorted(entries)}")

    def test_a_lock_left_by_a_dead_updater_is_broken_rather_than_waited_on_forever(self):
        target = self.tmp / "wedged.json"
        atomic_write(target, '{"entries": []}')
        (self.tmp / f".{target.name}.lock").mkdir()          # a holder that will never come back
        result = atomic_update(target, lambda cur: ('{"entries": ["after"]}', "done"), timeout_s=0.05)
        self.assertEqual(result, "done")
        self.assertEqual(json.loads(target.read_text())["entries"], ["after"],
                         "a lock nobody may break turns one dead writer into a permanently wedged file")


class AtomicSymlinkCase(unittest.TestCase):
    """`atomic_symlink` — the publish for a pointer rather than for text.

    The property is not "the link ends up right", which unlink-then-symlink also satisfies. It is that the
    link is NEVER ABSENT, and that is only observable from another thread while a flip is in progress: by
    the time the call returns, the broken implementation has already put the link back. A single-threaded
    sampler passes against the defect — measured, not assumed.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.a = self.tmp / "a"
        self.b = self.tmp / "b"
        self.a.mkdir()
        self.b.mkdir()
        self.link = self.tmp / "current"

    def test_it_publishes_the_target(self):
        from fleet.atomic import atomic_symlink
        atomic_symlink(self.a, self.link)
        self.assertEqual(pathlib.Path(os.readlink(self.link)), self.a)

    def test_it_replaces_an_existing_link(self):
        from fleet.atomic import atomic_symlink
        atomic_symlink(self.a, self.link)
        atomic_symlink(self.b, self.link)
        self.assertEqual(pathlib.Path(os.readlink(self.link)), self.b)

    def test_the_link_is_never_absent_while_flipping(self):
        from fleet.atomic import atomic_symlink
        atomic_symlink(self.a, self.link)
        # A COUNTER, not a list. Against the defect this fires ~240k times, and asserting on the list
        # rendered a 1.4 MB unittest diff that buried the one number a reader needs.
        misses = [0]
        stop = threading.Event()

        def observe():
            while not stop.is_set():
                if not self.link.is_symlink():
                    misses[0] += 1

        watcher = threading.Thread(target=observe, daemon=True)
        watcher.start()
        try:
            for _ in range(300):
                atomic_symlink(self.b, self.link)
                atomic_symlink(self.a, self.link)
        finally:
            stop.set()
            watcher.join(timeout=5)
        self.assertEqual(misses[0], 0, f"the link was absent {misses[0]} time(s) during a flip")

    def test_concurrent_flippers_do_not_share_a_staging_name(self):
        """Two threads flipping at once must both succeed. A pid-derived staging name — the obvious
        choice — is shared by every writer inside one process, so one publishes the other's target and the
        other raises FileNotFoundError. That is `FI-20` with a different receiver."""
        from fleet.atomic import atomic_symlink
        errors = []

        def flip(target):
            for _ in range(200):
                try:
                    atomic_symlink(target, self.link)
                except Exception as exc:                       # noqa: BLE001 - recording, not handling
                    errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=flip, args=(t,)) for t in (self.a, self.b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [], f"concurrent flips raised: {errors[:3]}")
        self.assertTrue(self.link.is_symlink())

    def test_no_staging_link_is_left_behind(self):
        from fleet.atomic import atomic_symlink
        atomic_symlink(self.a, self.link)
        litter = [p.name for p in self.tmp.iterdir() if p.name.endswith(TMP_SUFFIX)]
        self.assertEqual(litter, [], "a staging symlink survived the publish")
