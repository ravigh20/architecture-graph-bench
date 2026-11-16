#!/usr/bin/env python3
"""Optionally acquire or locally read full annotated source files and verify projection.

Normal experiment runs are offline. This utility does not change data/ and does
not replace predictions or fit scores. A failed acquisition is recorded, not
reported as successful source authentication.
"""
from __future__ import annotations
import argparse,json,hashlib,urllib.request,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def connection_records(text:str):
    """Extract source-study TP/FN connection annotations and identified FP edges."""
    section=None;rows=[]
    for number,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if line in ('Components:','Connections:','Endpoints:','FP:'):
            section=line;continue
        if ' -> ' not in line:continue
        if section=='Connections:':
            label,pair=line.split(' ',1)
            if label not in ('TP','FN'):raise ValueError('Unexpected connection label')
        elif section=='FP:':label,pair='FP',line
        else:continue
        ends=pair.split(' -> ')
        if len(ends)!=2:raise ValueError('Malformed annotated edge')
        rows.append({'status':label,'source':ends[0].strip(),'target':ends[1].strip(),'line':number})
    return rows


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=ROOT/'data')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--source-directory',type=Path,help='Extracted archive root containing tool_comparison; no network used')
    a=p.parse_args(argv)
    if a.out.exists():p.error('Use a new output directory')
    if a.out.resolve().is_relative_to(a.data.resolve()):p.error('Output must be outside data/')
    a.out.mkdir(parents=True);records=json.loads((a.data/'replay/annotated_connections.json').read_text())['records'];results=[]
    key=lambda r:(r['status'],r['source'],r['target'])
    for r in records:
        entry={'system':r['system'],'tool':r['tool'],'url':r['source_url'],'status':'FAILED'}
        try:
            relative=r['source_url'].split('/v1.1/',1)[1]
            if a.source_directory:raw=(a.source_directory/relative).read_bytes()
            else:
                req=urllib.request.Request(r['source_url'],headers={'User-Agent':'ArchGraphBench-source-verifier/4.0'})
                with urllib.request.urlopen(req,timeout=30) as response:raw=response.read()
            local=a.out/'source'/relative;local.parent.mkdir(parents=True,exist_ok=True);local.write_bytes(raw)
            fresh=connection_records(raw.decode('utf-8-sig'));expected={key(x) for x in r['connections']};actual={key(x) for x in fresh}
            entry.update(status='MATCH' if expected==actual else 'MISMATCH',sha256=hashlib.sha256(raw).hexdigest(),
              source_file=local.relative_to(a.out).as_posix(),missing=sorted(expected-actual),additional=sorted(actual-expected),
              upstream_records=fresh)
        except Exception as exc:entry['error']=str(exc)
        results.append(entry)
        print(r['system'],r['tool'],entry['status'],flush=True)
        (a.out/'verification.json').write_text(json.dumps({'records':results},indent=2)+'\n')
    return 0 if all(x['status']=='MATCH' for x in results) else 1
if __name__=='__main__':raise SystemExit(main())
