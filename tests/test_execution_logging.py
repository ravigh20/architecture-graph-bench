"""Demonstration controls must remain observers, not change scientific outputs."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from archgraphbench.execution_log import (
    ExecutionLog, configure, context, info, debug, checkpoint,
    add_logging_arguments, forwarded_arguments, stream_child,
)
from archgraphbench.io import read_json, inventory, sha256

ROOT = Path(__file__).resolve().parents[1]


def options(**updates):
    values = dict(verbose=False, trace=False, demo=False, pause=False, step_delay=0.0, trace_limit=50)
    values.update(updates)
    return argparse.Namespace(**values)


class LoggingUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.terminal = io.StringIO()
        self.session = None

    def tearDown(self):
        if self.session:
            self.session.close()
        self.temp.cleanup()

    def start(self, **updates):
        self.session = configure(options(**updates), self.path, stream=self.terminal)
        return self.session

    def events(self):
        return [json.loads(line) for line in (self.path / 'algorithm.jsonl').read_text().splitlines()]

    def test_01_default_records_info_without_console(self):
        self.start()
        info('TEST', 'VALUE', 'Calculated value', value=3)
        self.assertEqual(self.terminal.getvalue(), '')
        self.assertEqual(self.events()[0]['fields']['value'], 3)

    def test_02_verbose_streams_info(self):
        self.start(verbose=True)
        info('TEST', 'VALUE', 'Live calculation', value=3)
        self.assertIn('Live calculation', self.terminal.getvalue())

    def test_03_debug_requires_trace(self):
        self.start(verbose=True)
        debug('TEST', 'DETAIL', 'Not enabled')
        self.assertEqual(self.events(), [])

    def test_04_trace_records_debug(self):
        self.start(trace=True)
        debug('TEST', 'DETAIL', 'Source join', pair=['a', 'b'])
        self.assertEqual(self.events()[0]['level'], 'DEBUG')
        self.assertIn('Source join', self.terminal.getvalue())

    def test_05_limit_discloses_omissions(self):
        self.start(trace=True, trace_limit=2)
        for i in range(5):
            debug('TEST', 'PAIR', 'Pair decision', index=i)
        self.session.close()
        events = self.events()
        self.assertEqual(sum(e['action'] == 'PAIR' for e in events), 2)
        self.assertTrue(any(e['action'] == 'TRACE_LIMIT' for e in events))
        self.assertEqual(next(e for e in events if e['action'] == 'TRACE_SUMMARY')['fields']['omitted'], 3)

    def test_06_zero_limit_records_every_event(self):
        self.start(trace=True, trace_limit=0)
        for i in range(80):
            debug('TEST', 'PAIR', 'Pair decision', index=i)
        self.assertEqual(len(self.events()), 80)

    def test_07_context_restored_on_failure(self):
        self.start()
        with self.assertRaises(ValueError):
            with context(method='M2'):
                info('TEST', 'VALUE', 'In context')
                raise ValueError('expected')
        info('TEST', 'VALUE', 'After context')
        self.assertEqual(self.events()[0]['context']['method'], 'M2')
        self.assertEqual(self.events()[1]['context'], {})

    def test_08_nested_context_keeps_parent(self):
        self.start()
        with context(study='boutique'):
            with context(method='M1'):
                info('TEST', 'VALUE', 'Nested')
        self.assertEqual(self.events()[0]['context'], {'study': 'boutique', 'method': 'M1'})

    def test_09_console_shortening_does_not_truncate_json(self):
        self.start(verbose=True)
        long_value = 'x' * 600
        info('TEST', 'VALUE', 'Long field', detail=long_value)
        self.assertEqual(self.events()[0]['fields']['detail'], long_value)
        self.assertNotIn(long_value, self.terminal.getvalue())

    def test_10_sequence_and_elapsed(self):
        self.start()
        info('TEST', 'A', 'First')
        info('TEST', 'B', 'Second')
        a, b = self.events()
        self.assertEqual([a['sequence'], b['sequence']], [1, 2])
        self.assertLessEqual(a['elapsed_seconds'], b['elapsed_seconds'])

    def test_11_builder_buffer_flushes_without_duplicate_console(self):
        self.session = configure(options(verbose=True), None, name='reference_builder', stream=self.terminal)
        info('REFERENCE', 'EDGE', 'Propose an edge')
        self.session.attach_files(self.path)
        info('REFERENCE', 'COMPLETE', 'Done')
        events = (self.path / 'reference_builder.jsonl').read_text().splitlines()
        self.assertEqual(len(events), 2)
        self.assertEqual(self.terminal.getvalue().count('Propose an edge'), 1)

    def test_12_no_log_writes_after_close(self):
        self.start()
        info('TEST', 'A', 'First')
        self.session.close()
        before = sha256(self.path / 'algorithm.log')
        info('TEST', 'B', 'Too late')
        self.assertEqual(before, sha256(self.path / 'algorithm.log'))

    def test_13_delay_only_at_checkpoints(self):
        self.start(demo=True, step_delay=0.2)
        with patch('archgraphbench.execution_log.time.sleep') as sleep:
            info('TEST', 'A', 'Ordinary event')
            checkpoint('TEST', 'Execute a stage')
        sleep.assert_called_once_with(0.2)

    def test_14_orchestrator_does_not_pause(self):
        self.session = configure(options(demo=True, pause=True, step_delay=1), self.path,
                                 stream=self.terminal, interactive=False)
        with patch('archgraphbench.execution_log.time.sleep') as sleep:
            checkpoint('TEST', 'Orchestration stage')
        sleep.assert_not_called()

    def test_15_flags_are_forwarded(self):
        flags = forwarded_arguments(options(trace=True, demo=True, pause=True, step_delay=.1, trace_limit=0))
        self.assertIn('--trace', flags)
        self.assertIn('--demo', flags)
        self.assertIn('--pause', flags)
        self.assertIn('0', flags)

    def test_16_invalid_delays_rejected(self):
        parser = argparse.ArgumentParser()
        add_logging_arguments(parser)
        for value in ['-1', 'nan', 'inf']:
            with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(['--step-delay', value])

    def test_17_negative_trace_limit_rejected(self):
        parser = argparse.ArgumentParser()
        add_logging_arguments(parser)
        with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(['--trace-limit', '-1'])

    def test_18_live_child_stream_not_end_replay(self):
        # Record when the terminal actually receives each line. Replaying both
        # lines after subprocess completion would produce almost no separation.
        class Recorder(io.StringIO):
            def __init__(self):
                super().__init__()
                self.arrivals = []
            def write(self, text):
                self.arrivals.append((text, time.monotonic()))
                return super().write(text)
        terminal = Recorder()
        command = [sys.executable, '-u', '-c',
                   'import time; print("FIRST", flush=True); time.sleep(.3); print("SECOND", flush=True)']
        with patch('sys.stdout', terminal):
            code, _, _ = stream_child(command, self.path / 'stdout.txt', self.path / 'stderr.txt', echo=True)
        first = next(t for s, t in terminal.arrivals if 'FIRST' in s)
        second = next(t for s, t in terminal.arrivals if 'SECOND' in s)
        self.assertEqual(code, 0)
        self.assertGreater(second - first, .15)

    def test_19_stderr_and_return_code_retained(self):
        command = [sys.executable, '-u', '-c', 'import sys; print("problem", file=sys.stderr); sys.exit(7)']
        code, _, stderr = stream_child(command, self.path / 'out.txt', self.path / 'err.txt', echo=False)
        self.assertEqual(code, 7)
        self.assertIn('problem', stderr)

    def test_20_json_safe_paths_sets(self):
        self.start()
        info('TEST', 'TYPES', 'Safe field conversion', path=self.path, members={'b', 'a'})
        event = self.events()[0]
        self.assertEqual(event['fields']['members'], ['a', 'b'])
        self.assertEqual(event['fields']['path'], str(self.path))


class LoggingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.data = ROOT / 'data'
        cls.before = inventory(cls.data)
        cls.runs = {}
        for mode, flags in [('normal', []), ('demo', ['--demo']), ('trace', ['--trace', '--trace-limit', '0'])]:
            out = cls.base / mode
            result = subprocess.run([sys.executable, str(ROOT / 'process.py'), '--data', str(cls.data),
                                     '--study', 'boutique', '--out', str(out), *flags], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            cls.runs[mode] = (out, result)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_21_numerical_csvs_identical_with_all_modes(self):
        normal = self.runs['normal'][0]
        for mode in ('demo', 'trace'):
            for path in normal.rglob('*.csv'):
                self.assertEqual(path.read_bytes(), (self.runs[mode][0] / path.relative_to(normal)).read_bytes())

    def test_22_graph_and_query_records_unchanged(self):
        for relative in ['boutique/graphs.json', 'boutique/queries.json', 'boutique/metrics.json', 'boutique/mask.json']:
            expected = read_json(self.runs['normal'][0] / relative)
            for mode in ('demo', 'trace'):
                self.assertEqual(expected, read_json(self.runs[mode][0] / relative))

    def test_23_inputs_unchanged(self):
        self.assertEqual(self.before, inventory(self.data))

    def test_24_log_hashes_valid_after_completion(self):
        for path, _ in self.runs.values():
            manifest = read_json(path / 'output_manifest.json')
            for relative, digest in manifest.items():
                self.assertEqual(digest, sha256(path / relative), relative)
            self.assertIn('logs/algorithm.jsonl', manifest)

    def test_25_masked_unknown_and_unsupported_log_events(self):
        events = [json.loads(line) for line in (self.runs['demo'][0] / 'logs/algorithm.jsonl').read_text().splitlines()]
        query = [e['fields'] for e in events if e['stage'] == 'BOUTIQUE' and e['action'] == 'QUERY'
                 and e['fields']['condition'] == 'masked' and e['fields']['query'] == 'Q2']
        by_method = {row['method']: row for row in query}
        self.assertEqual(by_method['M2']['evidence'], 'U')
        self.assertEqual(by_method['M2-CW']['evidence'], 'F')
        self.assertTrue(by_method['M2-CW']['unsupported'])

    def test_26_trace_includes_actual_name_selector_and_edge_operations(self):
        events = [json.loads(line) for line in (self.runs['trace'][0] / 'logs/algorithm.jsonl').read_text().splitlines()]
        actions = {e['action'] for e in events}
        self.assertTrue({'NAME_JOIN', 'SELECTOR_JOIN', 'PORT_JOIN', 'EDGE_ADDED', 'BFS_FOUND'} <= actions)
        added = [e for e in events if e['action'] == 'EDGE_ADDED']
        self.assertTrue(any(e['fields']['source'] == 'entry:frontend-external' for e in added))

    def test_27_demo_default_never_waits_for_stdin(self):
        result = self.runs['demo'][1]
        self.assertIn('STEP 01', result.stdout)
        self.assertNotIn('Press Enter', result.stdout)

    def test_28_pause_requires_interactive_terminal(self):
        out = self.base / 'not_created'
        result = subprocess.run([sys.executable, str(ROOT / 'process.py'), '--out', str(out), '--pause'],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(out.exists())

    def test_29_failure_record_and_error_log(self):
        case = self.base / 'broken.json'
        case.write_text('{}', encoding='utf-8')
        out = self.base / 'failure'
        result = subprocess.run([sys.executable, str(ROOT / 'process.py'), '--study', 'contract', '--case', str(case),
                                 '--out', str(out), '--verbose'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(read_json(out / 'run.json')['status'], 'FAILED')
        events = [json.loads(line) for line in (out / 'logs/algorithm.jsonl').read_text().splitlines()]
        self.assertTrue(any(event['level'] == 'ERROR' for event in events))
        self.assertTrue((out / 'logs/error.txt').exists())


if __name__ == '__main__':
    unittest.main()
