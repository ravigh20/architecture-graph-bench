#!/usr/bin/env python3
"""Generate the submission-candidate paper's tables, figures and underlying evidence.

The workflow optionally prepares a Boutique reference candidate, executes the
scientific processing, then runs tests when requested. Child output is streamed
while calculations execute so a live demonstration is not a delayed log replay.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from archgraphbench.io import write_json, inventory
from archgraphbench.execution_log import (
    add_logging_arguments, validate_logging_arguments, forwarded_arguments,
    configure, info, error, stream_child,
)

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    """Coordinate independent processes and retain their status and output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-mode', choices=['historical', 'generated'], default='historical',
                        help='historical uses the paper input; generated builds a NEW pending-review Boutique candidate')
    parser.add_argument('--no-plots', action='store_true', help='Skip figure rendering; record missing figure artifacts')
    parser.add_argument('--checks', action='store_true', help='Execute implementation tests after generating outputs')
    add_logging_arguments(parser)
    args = parser.parse_args(argv)
    validate_logging_arguments(args, parser)
    output, data = args.out.resolve(), args.data.resolve()
    if output.exists():
        parser.error('Use a new output directory')
    if not data.is_dir():
        parser.error('Data folder missing')
    if output == data or output.is_relative_to(data) or data.is_relative_to(output) or ROOT.is_relative_to(output):
        parser.error('Unsafe output directory')
    if not args.no_plots:
        try:
            import matplotlib
        except ImportError:
            parser.error('Install requirements-plots.txt first')

    before = inventory(data)
    output.mkdir(parents=True)
    logs = output / 'logs'
    logs.mkdir()
    # Only algorithm checkpoints in children pause. The orchestrator reports
    # launch/completion events but must not add another interactive prompt.
    session = configure(args, logs, name='workflow', interactive=False)
    record = {'status': 'RUNNING', 'started': datetime.now(timezone.utc).isoformat(),
              'reference_mode': args.reference_mode, 'steps': []}
    flags = forwarded_arguments(args)

    def save():
        write_json(output / 'workflow.json', record)

    def run(name, command):
        """Tee live stdout/stderr into both the terminal and the stage logs."""
        print(name, flush=True)
        info('WORKFLOW', 'LAUNCH', 'Launch the program that performs this stage.', stage_name=name, command=command)
        code, stdout_tail, stderr_tail = stream_child(
            command, logs / (name + '.stdout.txt'), logs / (name + '.stderr.txt'), echo=True)
        record['steps'].append({'name': name, 'command': command, 'returncode': code})
        save()
        if code:
            raise RuntimeError(name + ' failed: ' + stderr_tail[-2500:] + stdout_tail[-1500:])
        info('WORKFLOW', 'STAGE_COMPLETE', 'The child completed successfully.', stage_name=name, returncode=code)

    save()
    try:
        info('WORKFLOW', 'START', 'Begin the complete evidence workflow.',
             reference_mode=args.reference_mode, data=data, output=output)
        # -u makes Python's stdout/stderr unbuffered even when captured by a pipe.
        command = [sys.executable, '-u', str(ROOT / 'process.py'), '--data', str(data),
                   '--out', str(output / 'results'), *flags]
        if not args.no_plots:
            command.append('--plots')
        if args.reference_mode == 'generated':
            source = data / 'public_case/source/kubernetes-manifests.yaml'
            candidate = output / 'generated_reference'
            run('build_reference', [sys.executable, '-u', str(ROOT / 'build_reference.py'),
                                   '--input', str(source), '--out', str(candidate), *flags])
            # Verification re-derives the source rules; it is not an independent
            # human review. Preserve the candidate's pending-review status.
            run('verify_reference', [sys.executable, '-u', str(ROOT / 'build_reference.py'), 'verify',
                                    '--input', str(source), '--reference', str(candidate / 'reference.json'), *flags])
            command += ['--source', str(source), '--reference', str(candidate / 'reference.json'),
                        '--allow-unreviewed-reference']
        run('process', command)
        if args.checks:
            if not (ROOT / 'tests').is_dir():
                raise ValueError('The --checks option requires the supplied tests directory')
            # Tests run without inherited logger flags: this avoids pausing or
            # tracing thousands of intentionally failing test fixtures.
            run('implementation_tests', [sys.executable, '-u', str(ROOT / 'run_checks.py'),
                                         '--out', str(output / 'checks')])
        record.update(status='COMPLETED', finished=datetime.now(timezone.utc).isoformat(),
                      inputs_unchanged=before == inventory(data))
        if not record['inputs_unchanged']:
            raise RuntimeError('Input files changed')
        save()
        info('WORKFLOW', 'COMPLETE', 'All requested stages completed; original inputs remain unchanged.', output=output)
        session.close()
        write_json(output / 'evidence_manifest.json',
                   {key: value for key, value in inventory(output).items() if key != 'evidence_manifest.json'})
        print('Evidence generated:', output / 'results')
        print('Live execution log:', output / 'results/logs/algorithm.log')
        print('Open results/EVIDENCE_README.md.', flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        state = 'CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
        record.update(status=state, error=str(exc), finished=datetime.now(timezone.utc).isoformat())
        save()
        error('WORKFLOW', state, 'The workflow stopped; inspect the stage logs and retained partial results.', reason=str(exc))
        print('ERROR:', exc, file=sys.stderr, flush=True)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        session.close()


if __name__ == '__main__':
    raise SystemExit(main())
