#!/usr/bin/env python3
"""Execute the submission-candidate ArchGraphBench algorithms on experimental inputs.

This entry point validates immutable inputs, runs the selected studies, and
writes calculated outputs. Reconstruction, support reasoning and scoring live
in archgraphbench/. Logging observes those functions without supplying answers.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import platform
import sys
import traceback

from archgraphbench import __version__
from archgraphbench.io import read_json, write_json, write_csv, sha256, inventory, check_data_manifest
from archgraphbench.execution_log import (
    add_logging_arguments, validate_logging_arguments, configure,
    checkpoint, info, warning, error, context,
)

ROOT = Path(__file__).resolve().parent


def now():
    """Return an execution timestamp; it is metadata, not an experimental input."""
    return datetime.now(timezone.utc).isoformat()


def dependency_version(name):
    """Record an installed dependency version without adding an installation step."""
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def print_results(summary: dict, output: Path) -> None:
    """Display the already calculated results; never manufacture a target score."""
    print('\nCALCULATED RESULTS')
    if 'diagnostics' in summary:
        result = summary['diagnostics']
        print('Diagnostic configurations:', result['support_configurations'],
              'policies:', result['policy_count'], 'weights:', result['weight_settings'],
              'rankings:', result['weight_ranks'])
    if 'boutique' in summary:
        print('Boutique: condition / method | edges | F1 | Ds | De | accepted | UCR')
        for row in summary['boutique']['cases']:
            print(f"  {row['condition']}/{row['method']}: {row['edges']} | "
                  f"{row['edge_f1']:.6f} | {row['Ds']:.3f} | {row['De']:.3f} | "
                  f"{row['accepted']}/{row['query_count']} | "
                  f"{row['UCR_q'] if row['UCR_q'] is not None else 'N/A'}")
    if 'bookinfo' in summary:
        for row in summary['bookinfo']['methods']:
            print('Bookinfo', row['method'], 'F1=', row['edge_f1'],
                  'wrong=', row['wrong_answers'], '/', row['queries'])
        result = summary['bookinfo']['confidence']
        print('Confidence: fit=', result['training_pairs'], 'test=', result['test_pairs'],
              'Brier=', result['brier'], 'hard-name Brier=', result['hard_name_brier'])
        for threshold in result['thresholds']:
            print('  threshold', threshold['threshold'], 'accepted', threshold['accepted'],
                  'errors', threshold['errors'], 'withheld true edges', threshold['withheld_true_edges'])
    if 'membership' in summary:
        print('Membership pairs:', summary['membership']['pairs'], 'query population:', summary['membership']['cardinality_queries'])
        print('Membership pooled Brier:', summary['membership']['baselines']['fitted']['pair_weighted_brier'])
    if 'replay' in summary:
        r=summary['replay']['annotated']
        print('Annotated replay records:', r['records'], 'queries:', r['ordered_pair_evaluations'], 'ranking reversals:', r['ranking_reversals'])
    if 'calibration' in summary:
        r=summary['calibration']['annotated']
        print('Edge-proposal calibration:', r['proposals'], 'proposals;', r['correct_proposals'], 'correct; Brier=',r['brier'])
        for row in r['thresholds']:
            if row['method']=='fitted': print('  threshold',row['threshold'],'accepted',row['accepted'],'correct',row['correct'])
    print('Outputs:', output, flush=True)


def main(argv=None):
    """Run selected studies while recording source integrity and failure status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data')
    parser.add_argument('--study', choices=['all', 'diagnostics', 'boutique', 'membership', 'replay', 'calibration', 'bookinfo', 'contract'], default='all')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--plots', action='store_true', help='Final Figures 1-6 for --study all')
    parser.add_argument('--source', type=Path, help='Optional Boutique source, requires matching --reference')
    parser.add_argument('--reference', type=Path, help='Generated Boutique reference; other references unchanged')
    parser.add_argument('--allow-unreviewed-reference', action='store_true')
    parser.add_argument('--allow-modified-inputs', action='store_true', help='Explicit new experiment, records manifest differences')
    parser.add_argument('--case', type=Path, help='Structured example for --study contract')
    add_logging_arguments(parser)
    args = parser.parse_args(argv)
    validate_logging_arguments(args, parser)
    data, output = args.data.resolve(), args.out.resolve()

    # Never overwrite a prior run or place generated evidence within source data.
    # These checks occur before opening log files, which are outputs too.
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('Output exists and is not empty; use a new --out')
    if output == data or output.is_relative_to(data) or data.is_relative_to(output) or ROOT.is_relative_to(output):
        parser.error('Unsafe output directory')
    if args.plots and args.study != 'all':
        parser.error('--plots produces the full figure set; use --study all')
    if args.source and not args.reference:
        parser.error('--source requires --reference matching its source')
    if args.reference and args.study not in ('all', 'boutique'):
        parser.error('--reference applies to Boutique only')
    if args.allow_unreviewed_reference and not args.reference:
        parser.error('--allow-unreviewed-reference needs --reference')
    for path in (args.source, args.reference, args.case):
        if path and path.resolve().is_relative_to(output):
            parser.error('Output must not contain an input override')
    if args.plots:
        try:
            import matplotlib
        except ImportError:
            parser.error('Install requirements-plots.txt')

    output.mkdir(parents=True, exist_ok=True)
    session = configure(args, output / 'logs')
    record = {
        'producer': 'archgraphbench.submission_candidate', 'version': __version__,
        'status': 'RUNNING', 'started': now(), 'python': platform.python_version(),
        'platform': platform.platform(), 'pyyaml': dependency_version('PyYAML'),
        'study': args.study, 'plots': args.plots, 'steps': [],
        'code_sha256': {path.relative_to(ROOT).as_posix(): sha256(path)
                       for path in [Path(__file__), *sorted((ROOT / 'archgraphbench').glob('*.py'))]},
        'execution_logging': {'text': 'logs/algorithm.log', 'jsonl': 'logs/algorithm.jsonl',
                              'trace': args.trace, 'trace_limit': args.trace_limit,
                              'demo': session.demo, 'pause': args.pause},
    }
    write_json(output / 'run.json', record)
    before = None
    try:
        info('RUN', 'START', 'Begin a new processing run.', study=args.study, output=output)
        overrides = {str(path.resolve()): sha256(path) for path in (args.source, args.reference, args.case) if path}
        summary = {}
        if args.study == 'contract':
            if not args.case:
                raise ValueError('--case is required for structured contract evaluation')
            from archgraphbench.core import evaluate_contract
            result = evaluate_contract(read_json(args.case))
            summary['contract'] = result
            write_json(output / 'contract/results.json', result)
            write_csv(output / 'contract/queries.csv', result['queries'])
        else:
            checkpoint('INPUT', 'Verify the frozen test-data inventory before calculating results.', directory=data)
            before = inventory(data)
            checked = check_data_manifest(data)
            write_json(output / 'audit/input_verification.json', checked)
            if not checked['matches'] and not args.allow_modified_inputs:
                raise ValueError('Input checksum mismatch: ' + ', '.join(checked['mismatches']))
            if not checked['matches']:
                warning('INPUT', 'MODIFIED', 'Explicitly running a new experiment with modified inputs.',
                        mismatches=checked['mismatches'])
            info('INPUT', 'VERIFIED', 'Record the input snapshot and load experiment settings.',
                 files=len(before), manifest_matches=checked['matches'])
            record['input_snapshot'] = before
            record['original_input_manifest_matches'] = checked['matches']
            record['new_experiment_modified_inputs'] = not checked['matches']
            config = read_json(data / 'experiment_config.json')
            from archgraphbench import diagnostics, boutique, bookinfo, membership, replay, calibration

            # Each module processes its own inputs. The reference is passed to
            # Boutique's evaluator, never into its extract() prediction function.
            for name in ['diagnostics', 'boutique', 'membership', 'replay', 'calibration', 'bookinfo']:
                if name == 'bookinfo' and args.study != 'bookinfo':
                    continue
                if args.study not in ('all', name) and not (args.study == 'calibration' and name == 'replay'):
                    continue
                print('Processing:', name, flush=True)
                step = {'name': name, 'started': now(), 'status': 'RUNNING'}
                record['steps'].append(step)
                write_json(output / 'run.json', record)
                with context(study=name):
                    if name == 'diagnostics':
                        result = diagnostics.run(output, config)
                    elif name == 'boutique':
                        result = boutique.run(data, output, config, source_path=args.source,
                                              reference_path=args.reference,
                                              allow_unreviewed_reference=args.allow_unreviewed_reference)
                    else:
                        module = {'membership': membership, 'replay': replay, 'calibration': calibration, 'bookinfo': bookinfo}[name]
                        result = module.run(data, output, config)
                summary[name] = result
                step.update(status='COMPLETED', finished=now())
                write_json(output / 'logs' / (name + '.json'), step)
                info('RUN', 'STUDY_COMPLETE', 'Study finished and its evidence files were written.', study=name)
            if args.study == 'all':
                from archgraphbench.evidence import all_evidence
                record['evidence'] = all_evidence(data, output, args.plots)

        checkpoint('OUTPUT', 'Check that inputs are unchanged and finalize the run records.')
        record.update(status='COMPLETED', finished=now(),
                      inputs_unchanged=before == inventory(data) if before is not None else True,
                      override_inputs_unchanged=all(sha256(Path(path)) == digest for path, digest in overrides.items()))
        if not record['inputs_unchanged'] or not record['override_inputs_unchanged']:
            raise RuntimeError('An input changed during execution')
        write_json(output / 'summary.json', summary)
        write_json(output / 'run.json', record)
        info('RUN', 'COMPLETE', 'Processing completed; all original and override inputs are unchanged.', output=output)

        # Log files are evidence artifacts. Flush and close them before computing
        # their checksums; otherwise a final log message invalidates the manifest.
        session.close()
        write_json(output / 'output_manifest.json',
                   {key: value for key, value in inventory(output).items() if key != 'output_manifest.json'})
        print_results(summary, output)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        state = 'CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
        record.update(status=state, finished=now(), error=f'{type(exc).__name__}: {exc}')
        write_json(output / 'run.json', record)
        (output / 'logs').mkdir(exist_ok=True)
        trace = traceback.format_exc()
        (output / 'logs/error.txt').write_text(trace, encoding='utf-8')
        error('RUN', state, 'Execution stopped; retain the failure and partial evidence.',
              exception_type=type(exc).__name__, reason=str(exc), traceback=trace)
        print('ERROR:', exc, file=sys.stderr, flush=True)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        session.close()


if __name__ == '__main__':
    raise SystemExit(main())
