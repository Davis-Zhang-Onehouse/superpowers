"""V23-H (v2-16): a completed worker's orphaned watcher pipelines held its slot, `harvest` refused with the pid list
and nothing could reap them. The attribution rule decides which slot holders are the torn-down instant's own; only
those are ever signalled."""

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from fleet import orphans
from fleet.orphans import NAME, REAP, REFUSE, Proc
from fleet.pool import UnreadableHolder
from fleet.session import Probes, SessionLayer, default_probes

INST = "/i/00000000-09251054-inflight-append-orphanw"
#: Launch bound for the pure cases, and a start time after it: the watcher was started by the launched worker.
LAUNCHED = 1.0e9
LATER = 4.0e9
DONE = "/i/00000000-09251054-complete-append-orphanw"


def table(*procs):
    return {p.pid: p for p in procs}


def pipeline(root=500, ppid=1, path=INST):
    """The measured harness shape: zsh wrapper (argv carries `$INSTANT` unexpanded), tail (argv names the path),
    grep (argv names nothing). `evidence/01-repro/base-334fb1d5.txt`."""
    return (Proc(root, ppid, "s500", ("zsh", "-c", "tail -n0 -F $INSTANT/evidence/INDEX.md | grep DONE"),
                 sid=root, children=(root + 1, root + 2), started_at=LATER, fleet_instant=path),
            Proc(root + 1, root, "s501", ("tail", "-n0", "-F", f"{path}/evidence/INDEX.md"), sid=root, children=()),
            Proc(root + 2, root, "s502", ("grep", "--line-buffered", "DONE"), sid=root, children=()))


class AttributionRule(unittest.TestCase):

    def spell(self):
        return orphans.instant_spellings(DONE)

    def test_spellings_cover_every_state_of_the_instant(self):
        spelled = self.spell()
        self.assertIn(INST, spelled)
        self.assertIn(DONE, spelled)
        self.assertIn("/i/00000000-09251054-abort-append-orphanw", spelled)

    def test_an_orphaned_pipeline_naming_the_instant_is_reaped_whole(self):
        facts = table(*pipeline())
        att = orphans.attribute([500, 501, 502], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(sorted(att.pids(REAP)), [500, 501, 502])
        self.assertIn("501", att.of(REAP)[0].why)

    def test_a_prefix_sharing_sibling_is_not_this_instant(self):
        facts = table(*pipeline(path=INST + "2"))
        att = orphans.attribute([500, 501, 502], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(sorted(att.pids(REFUSE)), [500, 501, 502])

    def test_boundaries(self):
        s = (INST,)
        self.assertTrue(orphans.names_instant(("x", f"--instant={INST}"), s))
        self.assertTrue(orphans.names_instant((f"'{INST}/evidence'",), s))
        self.assertTrue(orphans.names_instant((INST,), s))
        self.assertFalse(orphans.names_instant((INST + "2/evidence",), s))
        self.assertFalse(orphans.names_instant(("/prefix" + INST,), s))
        self.assertFalse(orphans.names_instant((INST + ".bak",), s))

    def test_named_but_parented_by_a_live_process_is_named_never_reaped(self):
        facts = table(*pipeline(ppid=4242))          # an operator's shell, NOT a slot holder, is its parent
        att = orphans.attribute([500, 501, 502], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(sorted(att.pids(NAME)), [500, 501, 502])
        command = att.of(NAME)[0].kill_command()
        self.assertTrue(command.startswith("kill -TERM 500 501 502"), command)
        self.assertIn("4242", command)

    def test_an_orphan_that_names_nothing_is_refused(self):
        facts = table(Proc(700, 1, "s", ("sleep", "900"), sid=700, children=()))
        att = orphans.attribute([700], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REFUSE), [700])

    def test_an_unreadable_holder_is_refused_even_when_named(self):
        facts = table(Proc(800, 1, "s", ("tail", "-F", f"{INST}/x"), sid=800, children=()))
        att = orphans.attribute([UnreadableHolder(800)], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REFUSE), [800])

    def test_a_holder_whose_facts_cannot_be_read_is_refused(self):
        att = orphans.attribute([900], {}.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REFUSE), [900])

    def test_the_callers_own_lineage_is_never_a_target(self):
        facts = table(*pipeline())
        att = orphans.attribute([500, 501, 502], facts.get, self.spell(), exclude={502}, not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(sorted(att.pids(REFUSE)), [500, 501, 502])

    def test_the_sessions_own_process_that_survived_the_kill_is_reaped_unnamed(self):
        facts = table(Proc(600, 1, "s600", ("node", "worker.js"), sid=600, children=()))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"}, not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [600])
        self.assertIn("session", att.of(REAP)[0].why)

    def test_a_recycled_pid_is_not_the_sessions_process(self):
        facts = table(Proc(600, 1, "s-new", ("node", "worker.js"), sid=600, children=()))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"}, not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])

    def test_a_slot_started_tmux_server_is_never_reaped_with_its_panes(self):
        """Task-1 review, Critical: a server started from inside the slot is ppid 1 and holds the slot; one pane naming
        the instant must not take down the server and every other pane."""
        facts = table(
            Proc(300, 1, "t", ("tmux", "-L", "priv", "new-session", "-d"), sid=300, children=(310, 320)),
            Proc(310, 300, "p1", ("bash",), sid=310, tty=34817, children=(311,)),
            Proc(311, 310, "l", ("less", f"{INST}/evidence/INDEX.md"), sid=310, tty=34817, children=()),
            Proc(320, 300, "p2", ("bash",), sid=320, tty=34818, children=(321,)),
            Proc(321, 320, "v", ("vim", "notes"), sid=320, tty=34818, children=()))
        att = orphans.attribute(list(facts), facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])
        self.assertNotIn(300, att.pids(NAME) + att.pids(REAP))
        self.assertIn(300, att.pids(REFUSE))
        self.assertEqual(sorted(att.pids(NAME)), [310, 311])

    def test_a_named_server_with_children_outside_is_named_not_reaped(self):
        facts = table(
            Proc(300, 1, "t", ("tmux", "new-session", "-c", INST), sid=300, children=(310,)),
            Proc(310, 300, "p1", ("bash",), sid=310, tty=34817, children=()))
        att = orphans.attribute(list(facts), facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])
        self.assertIn(300, att.pids(NAME))

    def test_a_member_in_another_session_is_its_own_unit(self):
        facts = table(*pipeline())
        facts[503] = Proc(503, 501, "s503", ("sleep", "9"), sid=503, children=())
        facts[501] = Proc(501, 500, "s501", ("tail", "-F", f"{INST}/x"), sid=500, children=(503,))
        att = orphans.attribute(list(facts), facts.get, self.spell(), not_before=LAUNCHED)
        self.assertIn(503, att.pids(REFUSE))
        self.assertNotIn(501, att.pids(REAP), "a unit with a child outside it was reaped")

    def test_an_orphan_that_is_not_a_session_leader_is_named(self):
        facts = table(Proc(700, 1, "s", ("tail", "-F", f"{INST}/x"), sid=650, children=(), started_at=LATER,
                           fleet_instant=INST))
        att = orphans.attribute([700], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(NAME), [700])

    def test_an_orphan_with_a_terminal_is_named(self):
        facts = table(Proc(700, 1, "s", ("tail", "-F", f"{INST}/x"), sid=700, tty=34817, children=(),
                           started_at=LATER, fleet_instant=INST))
        att = orphans.attribute([700], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(NAME), [700])

    def test_unobserved_children_fail_closed(self):
        facts = table(Proc(700, 1, "s", ("tail", "-F", f"{INST}/x"), sid=700, children=None))
        att = orphans.attribute([700], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(att.pids(NAME), [700])

    def test_a_sessions_own_survivor_with_an_outside_child_is_named(self):
        facts = table(Proc(600, 1, "s600", ("node",), sid=600, children=(999,)))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"}, not_before=LAUNCHED)
        self.assertEqual(att.pids(NAME), [600])

    def test_a_childless_server_that_predates_the_launch_is_named_not_reaped(self):
        """Task-2 re-review, Critical: fleet's own tmux servers carry the first dispatch's command line (it names that
        instant), have ppid 1, lead their session and have no tty; with no live pane they have no children either."""
        facts = table(Proc(300, 1, "t", ("tmux", "-L", "fleet", "new-session", "bash", f"{INST}/.fleet/resume.sh"),
                           sid=300, children=(), started_at=LAUNCHED - 5))
        att = orphans.attribute([300], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(att.pids(NAME), [300])

    def test_a_server_started_after_launch_without_the_workers_provenance_is_named(self):
        """Task-3 review, Critical: a childless tmux/screen server started from the slot AFTER the launch, naming the
        instant (an operator's `tmux new "less <instant>/…"` with its panes gone) — detached, closed, late. Its
        environment carries another instant or none, so it is not the worker's."""
        for env in (None, "/i/00000000-09250000-inflight-append-coordinator"):
            for argv in (("tmux", "new", "-s", "peek", "less", f"{INST}/evidence/INDEX.md"),
                         ("SCREEN", "-dmS", "x", "tail", "-F", f"{INST}/x")):
                facts = table(Proc(300, 1, "t", argv, sid=300, children=(), started_at=LATER, fleet_instant=env))
                att = orphans.attribute([300], facts.get, self.spell(), not_before=LAUNCHED)
                self.assertEqual(att.pids(REAP), [], (env, argv))
                self.assertEqual(att.pids(NAME), [300], (env, argv))

    def test_provenance_of_a_prefix_sharing_sibling_is_not_this_instant(self):
        facts = table(*pipeline())
        facts[500] = Proc(500, 1, "s500", facts[500].argv, sid=500, children=(501, 502), started_at=LATER,
                          fleet_instant=INST + "2")
        att = orphans.attribute([500, 501, 502], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])

    def test_no_recorded_launch_reaps_nothing_by_name(self):
        facts = table(*pipeline())
        att = orphans.attribute([500, 501, 502], facts.get, self.spell(), not_before=None)
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(sorted(att.pids(NAME)), [500, 501, 502])

    def test_an_unread_start_time_reaps_nothing_by_name(self):
        facts = table(Proc(700, 1, "s", ("tail", "-F", f"{INST}/x"), sid=700, children=(), started_at=None))
        att = orphans.attribute([700], facts.get, self.spell(), not_before=LAUNCHED)
        self.assertEqual(att.pids(REAP), [])

    def test_a_recycled_pid_with_outside_children_is_refused_not_named(self):
        """Task-2 re-review, Important: a snapshot entry whose start does not match is not the session's process."""
        facts = table(Proc(600, 1, "s-new", ("node",), sid=600, children=(999,)))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"}, not_before=LAUNCHED)
        self.assertEqual(att.pids(REFUSE), [600])

    def test_naming_holders_lists_only_naming_pids_outside_the_lineage(self):
        facts = table(*pipeline(ppid=77))
        found = orphans.naming_holders([500, 501, 502], facts.get, self.spell(), exclude={77})
        self.assertEqual([p.pid for p in found], [501])


class Reap(unittest.TestCase):
    """TERM, a bounded wait, then KILL — each signal re-checks the start time so a recycled pid is never hit."""

    def setUp(self):
        self.live = table(*pipeline())
        self.sent = []
        self.slept = []

    def signal_pid(self, pid, sig):
        self.sent.append((pid, sig))
        return True

    def units(self):
        return orphans.attribute(list(self.live), self.live.get, orphans.instant_spellings(INST), not_before=LAUNCHED)

    def test_term_ends_them_and_nothing_is_killed(self):
        att = self.units()
        def signal_pid(pid, sig):
            self.sent.append((pid, sig))
            self.live.pop(pid, None)
            return True
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, signal_pid, self.slept.append)
        self.assertEqual(sorted((pid, how) for pid, how, _ in done), [(500, "TERM"), (501, "TERM"), (502, "TERM")])
        self.assertEqual({sig for _, sig in self.sent}, {signal.SIGTERM})

    def test_a_term_ignorer_is_killed_after_the_bound(self):
        att = self.units()
        def signal_pid(pid, sig):
            self.sent.append((pid, sig))
            if sig == signal.SIGKILL:
                self.live.pop(pid, None)
            return True
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, signal_pid, self.slept.append, wait_s=0.3)
        self.assertEqual({how for _, how, _ in done}, {"KILL"})
        self.assertAlmostEqual(sum(self.slept[:3]), 0.3, places=5)

    def test_a_recycled_pid_is_never_signalled(self):
        att = self.units()
        self.live[501] = Proc(501, 1, "someone-else", ("vim",), sid=501, children=())
        def signal_pid(pid, sig):
            self.sent.append((pid, sig))
            self.live.pop(pid, None)
            return True
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, signal_pid, self.slept.append)
        self.assertNotIn(501, [pid for pid, _ in self.sent])
        self.assertIn((501, "gone"), [(pid, how) for pid, how, _ in done])

    def test_an_undelivered_signal_is_reported_unsignalled_not_gone(self):
        att = self.units()
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, lambda pid, sig: False, self.slept.append,
                            wait_s=0.2)
        self.assertEqual({how for _, how, _ in done}, {"unsignalled"})

    def test_a_process_that_survives_kill_is_reported_survived(self):
        att = self.units()
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, self.signal_pid, self.slept.append, wait_s=0.2)
        self.assertEqual({how for _, how, _ in done}, {"survived"})


class RealProcessFacts(unittest.TestCase):
    """The real `/proc` reader and signal seam `default_probes` hands the attribution rule."""

    def probes(self):
        return default_probes(tmux_socket="itfleet-v23h-unused")

    def test_facts_of_a_real_process(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (child.kill(), child.wait()))
        fact = self.probes().proc_facts(child.pid)
        self.assertEqual((fact.pid, fact.ppid, fact.argv), (child.pid, os.getpid(), ("sleep", "30")))
        self.assertTrue(fact.start.isdigit())
        self.assertEqual(fact.children, ())
        own = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
        self.assertEqual((fact.sid, fact.tty), (int(own[3]), int(own[4])), "a child inherits session and terminal")

    def test_a_zombie_child_is_dropped_and_a_live_one_kept(self):
        code = ("import os, subprocess, sys, time\n"
                "if os.fork() == 0:\n    os._exit(0)\n"                  # never waited for: stays a zombie
                "p = subprocess.Popen(['sleep', '30'])\n"
                "print(p.pid, flush=True)\n"
                "time.sleep(30)\n")
        parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        sleeper = int(parent.stdout.readline())
        self.addCleanup(lambda: (os.kill(sleeper, signal.SIGKILL), parent.kill(), parent.wait(),
                                 parent.stdout.close()))
        time.sleep(0.2)
        states = {int(c): Path(f"/proc/{c}/stat").read_text().rsplit(")", 1)[1].split()[0]
                  for t in Path(f"/proc/{parent.pid}/task").iterdir()
                  for c in (t / "children").read_text().split()}
        self.assertIn("Z", states.values(), f"control: the fixture made no zombie ({states})")
        self.assertEqual(self.probes().proc_facts(parent.pid).children, (sleeper,))

    def test_a_gone_pid_has_no_facts(self):
        child = subprocess.Popen(["true"])
        child.wait()
        self.assertIsNone(self.probes().proc_facts(child.pid))

    def test_signal_pid_ends_the_process_it_was_given(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (child.poll() is None and child.kill(), child.wait()))
        self.assertTrue(self.probes().signal_pid(child.pid, signal.SIGTERM))
        self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)

    def test_a_child_whose_stat_cannot_be_read_still_counts_as_live(self):
        """Task-2 re-review, Important: an unreadable child (hidepid, another uid) must keep its parent's unit from
        reading closed. Modelled with a fake proc root whose child `stat` is unreadable (a directory)."""
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="fleet-v23h-proc-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "stat").write_text("cpu 0\nbtime 1000\n")
        me = root / "40" / "task" / "40"
        me.mkdir(parents=True)
        (root / "40" / "stat").write_text("40 (sh) S 1 40 40 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 500 0 0\n")
        (root / "40" / "cmdline").write_bytes(b"sh\0-c\0x\0")
        (me / "children").write_text("41 42")
        (root / "41" / "stat").mkdir(parents=True)                        # exists, unreadable as a file
        (root / "42").mkdir()                                              # exists, no stat at all: gone or hidden
        fact = default_probes(tmux_socket="itfleet-v23h-unused", proc_root=root).proc_facts(40)
        self.assertEqual(fact.children, (41, 42))
        (me / "children").write_text("41 43")                              # 43: no /proc entry (hidepid=2), listed
        fact = default_probes(tmux_socket="itfleet-v23h-unused", proc_root=root).proc_facts(40)
        self.assertEqual(fact.children, (41, 43), "a listed child hidden from /proc must count as live")
        (root / "40" / "environ").write_bytes(b"A=1\0FLEET_INSTANT=/i/x\0")
        self.assertEqual(default_probes(tmux_socket="itfleet-v23h-unused", proc_root=root).proc_facts(40).fleet_instant,
                         "/i/x")
        self.assertAlmostEqual(fact.started_at, 1000 + 500 / os.sysconf("SC_CLK_TCK"))

    def test_an_absent_probe_is_not_observable(self):
        layer = SessionLayer(Probes(list_processes=list, capture_pane=lambda n: "", has_session=lambda n: False,
                                    start_session=lambda *a: None, kill_session=lambda n: None))
        self.assertFalse(layer.facts_observable())
        self.assertIsNone(layer.proc_facts(1))
        self.assertFalse(layer.signal_pid(1, 0))


# --- through the verbs ---------------------------------------------------------------------------------------------

from fleet import EXIT_OK, EXIT_REFUSED  # noqa: E402
from tests.test_cli import IDLE_PANE, CliCase, snapshot  # noqa: E402


class FactsFixture:
    """Injects `proc_facts`/`signal_pid` into a Fleet fixture: a table of `Proc`; a signal ends the pid (removes it from
    the table, from every slot's holders and from its parent's children) unless it is in `stubborn`."""

    def __init__(self, fleet):
        self.fleet, self.table, self.sent, self.stubborn, self.immortal = fleet, {}, [], set(), set()
        fleet.sessions.probes.proc_facts = lambda pid: self.table.get(pid)
        fleet.sessions.probes.signal_pid = self.signal

    def signal(self, pid, sig):
        self.sent.append((pid, sig))
        if pid in self.immortal or (pid in self.stubborn and sig == signal.SIGTERM):
            return True
        self.table.pop(pid, None)
        for held in self.fleet.holders.values():
            if pid in held:
                held.remove(pid)
        return True

    def hold(self, slot, *procs):
        for proc in procs:
            self.table[proc.pid] = proc
            self.fleet.hold_slot_cwd(slot, proc.pid)


class HarvestReapsAttributed(CliCase):
    """RED on 334fb1d5: harvest refused rc=4 on the orphaned pipeline with no path to end it."""

    def harvestable(self, fleet, name="doneWorker", slot="ws1", live=False):
        path = fleet.worker(name, state="complete", slot=slot, pane=IDLE_PANE, live=live)
        fleet.reviewed(path)
        return path

    def pipeline_for(self, path, root=500, ppid=1):
        return pipeline(root=root, ppid=ppid, path=str(path).replace("-complete-", "-inflight-"))

    def test_the_orphaned_watchers_of_a_closed_worker_are_reaped_and_the_slot_released(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet)
        facts.hold("ws1", *self.pipeline_for(path))
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertIsNone(fleet.pool.lease("ws1"), "the slot is still leased")
        self.assertEqual(sorted(pid for pid, _ in facts.sent), [500, 501, 502])
        self.assertEqual({sig for _, sig in facts.sent}, {signal.SIGTERM})
        for pid in ("500", "501", "502"):
            self.assertIn(pid, out)
        self.assertIn("reaped", out)
        self.assertTrue(fleet.store.read(fleet.ids["doneWorker"]).harvested_at)

    def test_a_watcher_that_survives_kill_is_named_in_the_release_refusal(self):
        """Final review I1: the gate let the unit through on the promise of the reap; when a member survives even KILL,
        the release refuses — and the refusal must say what was signalled and what is left."""
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet)
        facts.hold("ws1", *self.pipeline_for(path))
        facts.immortal.add(501)
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertIn("Signalled first", err)
        self.assertIn("501 survived", err)
        self.assertIn("500 TERM", err)
        self.assertIsNotNone(fleet.pool.lease("ws1"))
        self.assertTrue(fleet.store.read(fleet.ids["doneWorker"]).harvested_at, "SI-31: stamped before the release")

    def test_a_refusing_harvest_signals_nothing(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet)
        facts.hold("ws1", *self.pipeline_for(path), Proc(700, 1, "s", ("sleep", "900"), sid=700, children=()))
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertIn("700", err)
        self.assertEqual(facts.sent, [], "a refusing harvest signalled a process")
        self.assertIsNotNone(fleet.pool.lease("ws1"))
        self.assertIsNone(fleet.store.read(fleet.ids["doneWorker"]).harvested_at)

    def test_an_operator_shaped_holder_is_named_with_a_kill_command_and_never_signalled(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet)
        facts.hold("ws1", *self.pipeline_for(path, ppid=4242))
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertIn("kill -TERM 500 501 502", err)
        self.assertEqual(facts.sent, [])

    def test_a_process_in_another_slot_naming_the_instant_is_untouched(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet)
        facts.hold("ws2", *self.pipeline_for(path, root=900))
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertEqual(facts.sent, [])
        self.assertIn(900, fleet.holders[str(fleet.pool.slot_path("ws2"))])

    def test_dry_run_names_what_it_would_reap_and_signals_nothing(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet)
        facts.hold("ws1", *self.pipeline_for(path))
        before = (snapshot(fleet.tmp), fleet.pool_state(), fleet.record_state())
        code, out, err = fleet.run(["harvest", "--dry-run", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertIn("would-reap", out)
        self.assertEqual(facts.sent, [])
        self.assertEqual((snapshot(fleet.tmp), fleet.pool_state(), fleet.record_state()), before)

    def test_without_the_facts_probe_harvest_refuses_exactly_as_before(self):
        fleet = self.fleet()
        self.harvestable(fleet)
        fleet.hold_slot_cwd("ws1", 500)
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_REFUSED, out + err)

    def test_a_live_sessions_detached_watcher_is_reaped_after_the_kill(self):
        """The session is still alive at harvest: its watcher is one of its own processes before the kill, survives
        the kill (own session, no tty) and is reaped after it, so the release that follows succeeds."""
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet, live=True)
        pane = 7000
        facts.hold("ws1", Proc(pane, 6999, "sp", ("claude",), sid=pane, tty=34817, children=(501,)),
                   Proc(501, pane, "s501", ("zsh", "-c", "watch"), sid=501, children=()))
        fleet.sessions.probes.pane_pids = lambda name: [pane] if name in fleet.tmux_live else None
        fleet.sessions.probes.parent_of = lambda pid: facts.table[pid].ppid if pid in facts.table else 0
        kill = fleet.sessions.probes.kill_session

        def kill_orphans_the_watcher(name):
            kill(name)
            facts.table.pop(pane, None)
            fleet.holders[str(fleet.pool.slot_path("ws1"))].remove(pane)
            facts.table[501] = Proc(501, 1, "s501", ("zsh", "-c", "watch"), sid=501, children=())
        fleet.sessions.probes.kill_session = kill_orphans_the_watcher
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["doneWorker"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertEqual([pid for pid, _ in facts.sent], [501])
        self.assertIsNone(fleet.pool.lease("ws1"))

    def test_a_slot_re_leased_to_another_worker_is_never_reaped_from(self):
        """FB-89's shape: the record's slot now belongs to a successor, whose own process may well tail its
        predecessor's evidence from that slot. Neither close nor harvest may attribute anything there."""
        from tests.test_cli import FOREIGN_BASE
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.harvestable(fleet)
        fleet.pool.release("ws1", force=True)
        fleet.pool.claim(todo_id="successor-0001", tmux="dt-successor", base_instant=FOREIGN_BASE,
                         child_instant="/elsewhere", slot="ws1")
        facts.hold("ws1", *self.pipeline_for(path))
        for argv in (["close", "--id", fleet.ids["doneWorker"]], ["harvest", "--id", fleet.ids["doneWorker"]]):
            fleet.run(argv)
            self.assertEqual(facts.sent, [], f"{argv[0]} signalled a process in a slot leased to someone else")
        self.assertEqual(fleet.pool.lease("ws1").todo_id, "successor-0001")

    def test_abort_is_unchanged(self):
        """D-4: abort keeps today's refusal for an orphan it could attribute."""
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = fleet.worker("abortMe", slot="ws1", pane=IDLE_PANE, live=False)
        facts.hold("ws1", *pipeline(path=str(path)))
        code, out, err = fleet.run(["abort", "--instant", str(path), "--reason", "x"])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertEqual(facts.sent, [])


class CloseReapsAttributed(CliCase):

    def live_worker(self, fleet, facts, name="liveOne"):
        fleet.worker(name, state="complete", slot="ws1", pane=IDLE_PANE)
        pane = 7000
        facts.hold("ws1", Proc(pane, 6999, "sp", ("claude",), sid=pane, tty=34817, children=(501,)),
                   Proc(501, pane, "s501", ("zsh", "-c", "watch"), sid=501, children=()))
        fleet.sessions.probes.pane_pids = lambda n: [pane] if n in fleet.tmux_live else None
        fleet.sessions.probes.parent_of = lambda pid: facts.table[pid].ppid if pid in facts.table else 0
        kill = fleet.sessions.probes.kill_session

        def kill_orphans_the_watcher(n):
            kill(n)
            facts.table.pop(pane, None)
            fleet.holders[str(fleet.pool.slot_path("ws1"))].remove(pane)
            facts.table[501] = Proc(501, 1, "s501", ("zsh", "-c", "watch"), sid=501, children=())
        fleet.sessions.probes.kill_session = kill_orphans_the_watcher

    def test_close_reaps_a_sessions_process_that_survives_the_kill(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        self.live_worker(fleet, facts)
        code, out, err = fleet.run(["close", "--id", fleet.ids["liveOne"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertEqual([pid for pid, _ in facts.sent], [501])
        self.assertIn("reaped", out)
        self.assertIsNotNone(fleet.pool.lease("ws1"), "close must not release the lease")

    def test_close_dry_run_signals_nothing(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        self.live_worker(fleet, facts)
        code, out, err = fleet.run(["close", "--dry-run", "--id", fleet.ids["liveOne"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertEqual(facts.sent, [])
        self.assertIn("would-reap", out)

    def test_close_leaves_an_unattributed_holder_alone_and_names_it(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        fleet.worker("liveTwo", state="complete", slot="ws1", pane=IDLE_PANE, live=False)
        facts.hold("ws1", Proc(700, 1, "s", ("sleep", "900"), sid=700, children=()))
        code, out, err = fleet.run(["close", "--id", fleet.ids["liveTwo"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertEqual(facts.sent, [])
        self.assertIn("700", out)

    def test_v23j_complete_but_working_refusal_still_comes_first(self):
        """v23-j refuses to close a COMPLETE-BUT-WORKING worker before anything; its watcher is never signalled."""
        from unittest import mock
        from fleet.store import ATTESTED_PREFIX, Declarations
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        self.live_worker(fleet, facts)
        declarations = Declarations(fleet.paths["liveOne"])
        declarations.set_phase("awaiting-ci")
        declarations.set_watchers(ATTESTED_PREFIX + "gate pid:999", pid={"pid": 999, "start": "1"})
        with mock.patch("fleet.reconcile.pid_start", return_value=("pid-running", "1")):
            code, out, err = fleet.run(["close", "--id", fleet.ids["liveOne"]])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertIn("COMPLETE-BUT-WORKING", err)
        self.assertEqual(facts.sent, [], "close signalled a COMPLETE-BUT-WORKING worker's watcher")
        self.assertEqual(fleet.killed, [])


def _stat(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


def _session_members(sid):
    """Live (non-zombie) pids whose session id is `sid`."""
    out = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            fields = _stat(entry.name)
            if fields and fields[0] not in ("Z", "X") and int(fields[3]) == sid:
                out.append(int(entry.name))
    return sorted(out)


def _spawn_orphan(cwd, command, instant=None):
    """A real `setsid sh -c '<command>'` whose launcher exits at once, so it is reparented to init with no terminal —
    the shape `close` leaves behind. Returns the orphan's pid, which is also its session id."""
    done = subprocess.run(["bash", "-c", f"setsid sh -c {shlex.quote(command)} </dev/null >/dev/null 2>&1 & echo $!"],
                          cwd=str(cwd), capture_output=True, text=True, check=True, start_new_session=True,
                          env=dict(os.environ, **({"FLEET_INSTANT": instant} if instant else {})))
    root = int(done.stdout.strip())
    for _ in range(100):
        fields = _stat(root)
        if fields and fields[1] == "1" and len(_session_members(root)) >= 3:
            break
        time.sleep(0.05)
    return root


@unittest.skipUnless(shutil.which("setsid") and shutil.which("tail") and shutil.which("grep"),
                     "needs setsid, tail and grep on PATH")
class RealOrphanPipeline(CliCase):
    """The real product path: `_cwd_holders`, `/proc` facts and `os.kill`, against a real orphaned watcher. RED on
    334fb1d5 (harvest refused rc=4); GREEN after. A same-uid watcher naming the instant from ANOTHER directory, and a
    non-naming orphan in the slot, are never signalled."""

    def setUp(self):
        super().setUp()
        self.roots = []

        def cleanup():
            for root in self.roots:
                for pid in _session_members(root):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.addCleanup(cleanup)

    def real_fleet(self):
        from fleet import cli
        fleet = self.fleet()
        real = default_probes(tmux_socket="itfleet-v23h-unused")
        fleet.sessions.probes.proc_facts = real.proc_facts
        fleet.sessions.probes.signal_pid = real.signal_pid
        fleet.pool._cwd_probe = cli._cwd_holders
        path = fleet.worker("realDone", state="complete", slot="ws1", pane=IDLE_PANE, live=False)
        fleet.reviewed(path)
        inflight = str(path).replace("-complete-", "-inflight-")
        self.inflight = inflight
        return fleet, f"tail -n0 -F {inflight}/evidence/INDEX.md | grep --line-buffered DONE"

    def test_harvest_reaps_the_real_orphan_and_nothing_outside_the_slot(self):
        fleet, watcher = self.real_fleet()
        ours = _spawn_orphan(fleet.pool.slot_path("ws1"), watcher, instant=self.inflight)
        self.roots.append(ours)
        elsewhere = fleet.tmp / "elsewhere"
        elsewhere.mkdir()
        theirs = _spawn_orphan(elsewhere, watcher, instant=self.inflight)
        self.roots.append(theirs)
        members = _session_members(ours)
        self.assertGreaterEqual(len(members), 3, "control: the fixture pipeline did not start")
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["realDone"]])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertIsNone(fleet.pool.lease("ws1"))
        for pid in members:
            self.assertIn(str(pid), out)
        self.assertEqual(_session_members(ours), [], "the orphaned watcher is still alive")
        self.assertGreaterEqual(len(_session_members(theirs)), 3, "a process outside the slot was signalled")

    def test_a_naming_orphan_without_the_workers_environment_refuses_and_is_named(self):
        """D-10 with real processes: same shape, but started from an environment that is not the worker's."""
        fleet, watcher = self.real_fleet()
        stranger = _spawn_orphan(fleet.pool.slot_path("ws1"), watcher)
        self.roots.append(stranger)
        before = _session_members(stranger)
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["realDone"]])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertIn(f"kill -TERM {stranger}", err)
        self.assertEqual(_session_members(stranger), before, "a process without the worker's provenance was signalled")

    def test_a_non_naming_orphan_in_the_slot_refuses_and_nothing_is_signalled(self):
        fleet, watcher = self.real_fleet()
        ours = _spawn_orphan(fleet.pool.slot_path("ws1"), watcher, instant=self.inflight)
        self.roots.append(ours)
        stranger = _spawn_orphan(fleet.pool.slot_path("ws1"), "sleep 60 | cat", instant=self.inflight)
        self.roots.append(stranger)
        before = (_session_members(ours), _session_members(stranger))
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["realDone"]])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertEqual((_session_members(ours), _session_members(stranger)), before,
                         "a refusing harvest signalled a real process")
        self.assertIsNotNone(fleet.pool.lease("ws1"))


class CompleteWarns(CliCase):
    """`complete` lists the worker's live watchers — slot holders naming its own instant — and still completes. It never
    signals, never counts the caller's own lineage, and v23-j's refusals still come first."""

    def worker_in_slot(self, fleet):
        path = fleet.worker("finishing", slot="ws1", pane=IDLE_PANE)
        fleet.reviewed(path)
        return path

    def test_complete_lists_live_watchers_and_still_completes(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.worker_in_slot(fleet)
        facts.hold("ws1", *pipeline(ppid=7000, path=str(path)))
        code, out, err = fleet.run(["complete", "--instant", str(path)])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertIn("watchers", out)
        self.assertIn("501", out)
        self.assertIn("stop your watchers", out)
        self.assertEqual(facts.sent, [], "complete must never signal")
        self.assertFalse(path.exists(), "complete did not rename")

    def test_the_dry_run_warns_too(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.worker_in_slot(fleet)
        facts.hold("ws1", *pipeline(ppid=7000, path=str(path)))
        code, out, err = fleet.run(["complete", "--dry-run", "--instant", str(path)])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertIn("watchers", out)
        self.assertTrue(path.exists())

    def test_a_failure_to_read_the_slot_never_blocks_complete(self):
        from unittest import mock
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.worker_in_slot(fleet)
        facts.hold("ws1", *pipeline(ppid=7000, path=str(path)))
        with mock.patch("fleet.orphans.naming_holders", side_effect=OSError("/proc went away")):
            code, out, err = fleet.run(["complete", "--instant", str(path)])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertFalse(path.exists())

    def test_no_watchers_no_row(self):
        fleet = self.fleet()
        FactsFixture(fleet)
        path = self.worker_in_slot(fleet)
        code, out, err = fleet.run(["complete", "--instant", str(path)])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertNotIn("watchers", out)

    def test_the_callers_own_process_is_not_a_watcher(self):
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.worker_in_slot(fleet)
        facts.hold("ws1", Proc(os.getpid(), 1, "me", ("fleet", "complete", "--instant", str(path)),
                               sid=os.getpid(), children=()))
        code, out, err = fleet.run(["complete", "--instant", str(path)])
        self.assertEqual(code, EXIT_OK, out + err)
        self.assertNotIn("watchers", out)

    def test_v23j_awaiting_ci_refusal_still_comes_first(self):
        from fleet.store import Declarations
        fleet = self.fleet()
        facts = FactsFixture(fleet)
        path = self.worker_in_slot(fleet)
        facts.hold("ws1", *pipeline(ppid=7000, path=str(path)))
        Declarations(path).set_phase("awaiting-ci")
        code, out, err = fleet.run(["complete", "--instant", str(path)])
        self.assertEqual(code, EXIT_REFUSED, out + err)
        self.assertIn("awaiting-ci", err)
        self.assertNotIn("stop your watchers", out + err)
        self.assertTrue(path.exists())
