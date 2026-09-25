import unittest
from fleet.reconcile import reconcile, UNREACHABLE, DEAD
from fleet.session import LiveSession, Probes, SessionLayer
from tests.test_reconcile import SyntheticFleet, _record

class ForeignHolder(unittest.TestCase):
    def test_foreign_socket_record_whose_slot_is_held(self):
        fleet = SyntheticFleet()
        (fleet.slots_dir / "ws9").mkdir(exist_ok=True)
        rec = _record(todo_id="t1", child_instant="00000000-07310348-inflight-append-w",
                      slot="ws9", tmux="dt-w", tmux_socket="other")
        fleet.store.write(rec)
        fleet.pool.claim(todo_id=rec.todo_id, tmux=rec.tmux, base_instant=rec.base_instant,
                         child_instant=rec.child_instant, slot="ws9")
        fleet.procs.append(LiveSession(pid=99, cwd=fleet.slots_dir / "ws9", name=None))
        # Same pane name on the queried server belongs to a different worker.
        fleet.procs.append(LiveSession(pid=100, cwd=fleet.slots_dir / "ws9", name="dt-w", nested=True))
        procs = fleet.procs
        other = SessionLayer(Probes(list_processes=lambda: [p for p in procs if p.name != "dt-w"], capture_pane=lambda n: None,
                                    has_session=lambda n: False, start_session=lambda *a: None,
                                    kill_session=lambda n: None, send_literal=lambda *a: None,
                                    submit=lambda n: None, socket="other"))
        subs = reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants, layer_for=lambda s: other)
        w = [s for s in subs if s.identity == "t1"][0]
        print("\nSTATE", w.state, "PID", w.evidence.get("pid"), "NOTE", w.note[:120])
        self.assertEqual(w.state, UNREACHABLE)
        self.assertEqual(w.evidence.get("pid"), "99")
        self.assertEqual(w.evidence.get("nested"), "")

if __name__ == "__main__":
    unittest.main()
