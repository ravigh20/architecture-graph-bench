#!/usr/bin/env python3
"""Build, mechanically verify, compare, or record review of a YAML-derived reference."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import yaml
from archgraphbench.execution_log import (add_logging_arguments, validate_logging_arguments, configure, info, error)
from archgraphbench.reference_builder import (write_candidate, verify_reference,
                                              compare_references, finalize)

BASE = Path(__file__).resolve().parent


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    commands = {'build','verify','compare','finalize'}
    # Backward-friendly short command: python build_reference.py --input ... --out ...
    if not args or (args[0] not in commands and args[0] not in ('-h','--help')):
        args.insert(0,'build')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    p = sub.add_parser('build',help='Derive an unreviewed candidate from source fields and answer-free questions')
    p.add_argument('--input',type=Path,required=True,help='Original/full Kubernetes YAML, not a reference JSON')
    p.add_argument('--profile',type=Path,default=BASE/'profiles/online_boutique.json',help='Answer-free questions, scope and mask; default is Online Boutique')
    p.add_argument('--out',type=Path,required=True,help='New directory outside input data; never replace the historical reference')
    p = sub.add_parser('verify',help='Verify source binding, locations and rule consistency; not independent validation')
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p = sub.add_parser('compare',help='Compare already-built candidate against the historical reference')
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p = sub.add_parser('finalize',help='Record a completed human review, without fabricating approval')
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--input',type=Path,required=True,help='Source YAML to verify before recording the review')
    p.add_argument('--review',type=Path,required=True,help='Completed review.csv; APPROVE/name/notes on every row')
    p.add_argument('--reviewer',required=True)
    p.add_argument('--note',required=True)
    p.add_argument('--attest-independent',action='store_true',help='Records your attestation, not a software verification of independence')
    p.add_argument('--out',type=Path,required=True)
    # Give every subcommand the same console controls. Verification without
    # --out writes to stdout; the outer workflow retains those lines in logs.
    for command_parser in sub.choices.values():
        add_logging_arguments(command_parser)
    ns = parser.parse_args(args)
    validate_logging_arguments(ns, parser)
    session = configure(ns, None, name='reference_builder')
    try:
        info('REFERENCE', 'START', 'Begin reference preparation or mechanical verification.', operation=ns.command)
        if ns.command=='build': result = write_candidate(ns.input,ns.profile,ns.out)
        elif ns.command=='verify': result = verify_reference(ns.input,ns.reference,allow_unreviewed=True)
        elif ns.command=='compare': result = compare_references(ns.candidate,ns.reference,ns.out)
        else:
            verify_reference(ns.input,ns.candidate,allow_unreviewed=True)
            result = finalize(ns.candidate,ns.review,ns.out,ns.reviewer,ns.note,ns.attest_independent)
        # Candidate creation rejects nonempty directories. Buffer events until
        # safe_destination has created the result folder, then persist them.
        if getattr(ns, 'out', None) is not None:
            session.attach_files(ns.out / 'logs')
        info('REFERENCE', 'COMPLETE', 'Reference operation finished; status describes the performed check only.',
             operation=ns.command, status=result.get('status'), all_match=result.get('all_match'))
        print(json.dumps(result,indent=2))
        if ns.command=='build':
            print('\nCreated:',ns.out/'reference.json')
            print('REVIEW PENDING. Mechanical agreement is not independent ground truth.')
        return 0 if result.get('all_match',True) else 1
    except (OSError,ValueError,KeyError,TypeError,yaml.YAMLError,KeyboardInterrupt) as exc:
        error('REFERENCE', 'FAILED', 'Reference operation stopped without recording an approval.',
              exception_type=type(exc).__name__, reason=str(exc))
        print(f'ERROR: {exc}',file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 2
    finally:
        session.close()


if __name__=='__main__':
    raise SystemExit(main())
