#!/usr/bin/env python3
"""Verify local hashes of a completed evidence directory."""
import argparse,json,sys
from pathlib import Path
from archgraphbench.io import sha256,read_json,child

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args(argv)
    try:
        manifest=read_json(a.run/'evidence_manifest.json');bad=[]
        for name,expected in manifest.items():
            f=child(a.run,name)
            if not f.is_file() or sha256(f)!=expected:bad.append(name)
        print(json.dumps({'checked':len(manifest),'mismatches':bad,'meaning':'Local integrity, not independent provenance'},indent=2))
        return 1 if bad else 0
    except (OSError,ValueError) as e:print('ERROR:',e,file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
