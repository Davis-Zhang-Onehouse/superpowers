"""Process races at the public command boundary, synchronized without timing guesses."""
import multiprocessing as mp
from pathlib import Path
import shutil
import unittest

from fleet.runtime_config import read_runtime, write_runtime
from tests.test_cli import Fleet


def run_cli(fleet, args, output):
    output.send(fleet.run(args))


class RuntimeConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)
        self.processes = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for process in self.processes:
            if process.is_alive():
                process.kill()
            process.join(5)

    def start(self, args):
        receive, output = mp.Pipe(False)
        # `fork`, explicitly: the fixture carries lambdas, and Linux's default start method changes in 3.14.
        process = mp.get_context('fork').Process(target=run_cli, args=(self.f, args, output))
        self.processes.append(process)
        process.start()
        self.addCleanup(receive.close)
        self.addCleanup(output.close)
        return receive

    def answer(self, pipe):
        self.assertTrue(pipe.poll(10), 'operation did not finish')
        return pipe.recv()

    def test_switch_waits_for_dispatch_and_then_refuses_its_open_record(self):
        entered, release = mp.Event(), mp.Event()
        original = self.f.context
        def factory():
            build = original()
            def context(parsed, out, err):
                ctx = build(parsed, out, err)
                resolve = ctx.launch_settings
                def paused(runtime, slot):
                    entered.set()
                    if not release.wait(8):
                        raise RuntimeError('test barrier timed out')
                    return resolve(runtime, slot)
                ctx.launch_settings = paused
                return ctx
            return context
        self.f.context = factory
        dispatch = self.start(['dispatch', '--profile', str(self.f.profile()), '--title', 'racing'])
        self.assertTrue(entered.wait(5))
        switch = self.start(['runtime', '--set', 'codex'])
        self.assertFalse(switch.poll(.15), 'switch bypassed an admitted dispatch')
        release.set()
        self.assertEqual(self.answer(dispatch)[0], 0)
        self.assertEqual(self.answer(switch)[0], 4)
        self.assertEqual(read_runtime(self.f.home)[0], 'claude')
        self.assertEqual(self.f.store.all()[0].runtime, 'claude')

    def test_dispatch_reads_the_selection_saved_by_another_process(self):
        switch = self.start(['runtime', '--set', 'codex'])
        self.assertEqual(self.answer(switch)[0], 0)
        dispatch = self.start(['dispatch', '--profile', str(self.f.profile()), '--title', 'selected'])
        self.assertEqual(self.answer(dispatch)[0], 0)
        self.assertEqual(self.f.store.all()[0].runtime, 'codex')

    def test_send_serializes_other_senders_and_close_until_submission(self):
        self.f.worker('target', slot='ws1', pane='❯ \n? for shortcuts')
        manager = mp.Manager()
        self.addCleanup(manager.shutdown)
        state = manager.dict(frame='❯ \n? for shortcuts', inserts=0, submits=0)
        entered, release = mp.Event(), mp.Event()
        def insert(name, text):
            state['inserts'] += 1
            state['frame'] = '❯ ' + text + '\n? for shortcuts'
            entered.set()
            if not release.wait(8):
                raise RuntimeError('test barrier timed out')
        def submit(name):
            state['submits'] += 1
            state['frame'] = 'esc to interrupt'
        self.f.sessions.probes.capture_pane = lambda name: state['frame']
        self.f.sessions.probes.send_literal = insert
        self.f.sessions.probes.submit = submit
        path = self.f.tmp / 'message.txt'
        path.write_text('hello')
        args = ['send', '--id', self.f.ids['target'], '--message-file', str(path)]
        first = self.start(args)
        self.assertTrue(entered.wait(5))
        second = self.start(args)
        close = self.start(['close', '--id', self.f.ids['target']])
        self.assertFalse(second.poll(.15), 'second sender bypassed the pane lock')
        self.assertFalse(close.poll(.15), 'close bypassed the pane lock')
        release.set()
        self.assertEqual(self.answer(first)[0], 0)
        self.assertEqual(self.answer(second)[0], 0)
        self.assertEqual(self.answer(close)[0], 4)
        self.assertEqual((state['inserts'], state['submits']), (2, 2))
        self.assertIsNone(self.f.store.read(self.f.ids['target']).closed_at)
