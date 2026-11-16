"""Section VII-F: source-study-annotated connection replay and raw sensitivity.

Primary predictions are TP + identified FP connection records supplied by the
source study. FN annotations are retained for audit but never inserted into a
prediction. This inherits the source study's interpretation: it is not a fresh
run of either tool and is not independent raw-direction validation.
"""
from __future__ import annotations
from collections import defaultdict, deque
from fractions import Fraction
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .io import read_json,write_json,write_csv,sha256
from .core import set_metrics
from .execution_log import checkpoint,info,debug,context

TOOLS=('Code2DFD','MicroDepGraph')


def normal_name(name: str) -> str:
    """Only spelling normalization; never infer a missing edge or flip direction."""
    if not isinstance(name,str) or not name.strip(): raise ValueError('Empty connection endpoint')
    return name.strip().casefold().replace('-','_')


def read_reference(path: Path):
    text=path.read_text(encoding='utf-8')
    comp,con=text.split('Connections:',1)
    nodes={s.strip() for s in comp.split('Components:',1)[1].splitlines() if s.strip()}
    edges={tuple(x.strip() for x in line.split('->')) for line in con.split('Endpoints:',1)[0].splitlines() if line.strip()}
    if any(len(e)!=2 or not set(e)<=nodes for e in edges):raise ValueError('Malformed external reference: '+str(path))
    return nodes,edges


def parse_annotated(record: dict):
    """Recover only the supplied positive proposals; preserve the source text."""
    pred=set();audit=[]
    for item in record['connections']:
        status=item['status']
        if status not in ('TP','FP','FN'):raise ValueError('Unknown source annotation: '+status)
        edge=tuple(normal_name(item[k]) for k in ('source','target'))
        included=status in ('TP','FP')
        if included:pred.add(edge)
        audit.append({**item,'normalized_edge':list(edge),'included_in_prediction':included,
                      'reason':'Source-study recovered connection' if included else 'FN is not a prediction',
                      'source_url':record['source_url']})
        debug('REPLAY','ANNOTATION','Read a source-study annotation without replacing its edge direction.',
              system=record['system'],tool=record['tool'],edge=edge,status=status,included=included)
    return pred,audit


def aliases(path: Path):
    """Optional sensitivity variant: use the archived component-only mappings."""
    mapping={}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('TP '):
            m=re.fullmatch(r'TP\s+(\S+)\s+\(([^()]+)\)\s*',line)
            if m:
                canonical,raw=m.groups();key=normal_name(raw)
                if key in mapping and mapping[key]!=canonical:raise ValueError('Ambiguous raw alias')
                mapping[key]=canonical
    return mapping


def parse_raw(path: Path, tool: str, mapping: dict | None=None):
    """Read sender/receiver or SVG arrow titles. Never use connection TP labels.

    Default: identical spelling normalization for both source endpoints. A
    separately named sensitivity may use published component aliases instead.
    These explicit alternatives expose an underspecified raw-alignment choice.
    """
    raw=[]
    if tool=='Code2DFD':
        for key,row in read_json(path)['information_flows'].items():
            raw.append((row['sender'],row['receiver'],{'pointer':f'/information_flows/{key}'}))
    elif tool=='MicroDepGraph':
        root=ET.parse(path).getroot()
        for i,g in enumerate(root.findall('.//{*}g[@class="edge"]')):
            title=g.find('{*}title')
            if title is None or not title.text or len(title.text.split('->'))!=2:raise ValueError('Malformed SVG edge title')
            a,b=title.text.split('->');raw.append((a,b,{'svg_edge_index':i,'title':title.text}))
    else:raise ValueError(tool)
    convert=lambda x:(mapping or {}).get(normal_name(x),normal_name(x))
    return {(convert(a),convert(b)) for a,b,_ in raw},[
      {'raw_source':a,'raw_target':b,'source':convert(a),'target':convert(b),'locator':loc,
       'input_file':str(path.name),'input_sha256':sha256(path)} for a,b,loc in raw]


def all_paths(edges:set):
    """Directed transitive closure, excluding zero-length/self endpoint queries."""
    adjacency=defaultdict(set)
    for a,b in edges:adjacency[a].add(b)
    result=set()
    for first in sorted(adjacency):
        todo=list(adjacency[first]);seen=set()
        while todo:
            nxt=todo.pop()
            if nxt in seen:continue
            seen.add(nxt);todo.extend(adjacency[nxt]-seen)
        result.update((first,last) for last in seen if last!=first)
    return result


def witness(edges:set,a:str,b:str):
    """Deterministic BFS; extra prediction endpoints remain traversable."""
    if a==b:return []
    adj=defaultdict(set)
    for x,y in edges:adj[x].add(y)
    todo=deque([a]);previous={a:None}
    while todo:
        x=todo.popleft()
        for y in sorted(adj[x]):
            if y in previous:continue
            previous[y]=x
            if y==b:
                path=[]
                while previous[y] is not None:path.append([previous[y],y]);y=previous[y]
                return path[::-1]
            todo.append(y)
    return None


def evaluate(system,tool,nodes,gold,pred,mode):
    metrics=set_metrics(gold,pred)
    rp,pp=all_paths(gold),all_paths(pred);answers=[]
    for a in sorted(nodes):
        for b in sorted(nodes-{a}):
            t,p=(a,b) in rp,(a,b) in pp
            debug('REPLAY','PATH_QUERY','Evaluate a declared directed path, not runtime connectivity.',source=a,target=b,reference=t,prediction=p,wrong=t!=p)
            rw,pw=witness(gold,a,b),witness(pred,a,b)
            answers.append({'system':system,'tool':tool,'mode':mode,'source':a,'target':b,
                'reference_answer':t,'predicted_answer':p,'wrong':t!=p,
                'reference_witness':rw,'prediction_witness':pw,
                'missing_on_reference_witness':[e for e in rw or [] if tuple(e) not in pred],
                'extra_on_prediction_witness':[e for e in pw or [] if tuple(e) not in gold]})
    wrong=sum(r['wrong'] for r in answers)
    row={'system':system,'tool':tool,'mode':mode,'reference_nodes':len(nodes),'reference_edges':len(gold),
         'prediction_edges':len(pred),**metrics,'wrong_answers':wrong,'queries':len(answers),
         'Ds':wrong/len(answers) if answers else None,'UCR':None,
         'support_score_status':'UNMEASURED: no condition-specific support labels for this replay'}
    return row,answers


def rankings(rows):
    paired=sorted({r['system'] for r in rows if r['tool']=='Code2DFD'} & {r['system'] for r in rows if r['tool']=='MicroDepGraph'})
    comparisons=[]
    for app in paired:
        c=next(r for r in rows if r['system']==app and r['tool']=='Code2DFD')
        m=next(r for r in rows if r['system']==app and r['tool']=='MicroDepGraph')
        cf=Fraction(2*c['tp'],2*c['tp']+c['fp']+c['fn']);mf=Fraction(2*m['tp'],2*m['tp']+m['fp']+m['fn'])
        dq=Fraction(c['wrong_answers'],c['queries'])-Fraction(m['wrong_answers'],m['queries'])
        comparisons.append({'application':app,'C_F1':float(cf),'M_F1':float(mf),
                            'C_errors':c['wrong_answers'],'M_errors':m['wrong_answers'],'queries':c['queries'],
                            'F1_tied':cf==mf,'ranking_reversed':(cf-mf)*dq>0})
    return comparisons


def run(data:Path,output:Path,config:dict):
    checkpoint('REPLAY','Load source-study connection annotations and archived raw exports.')
    root=data/'replay';base=root/'tool_comparison';bundle=read_json(root/'annotated_connections.json')
    modes=('annotated','raw_normalized','raw_published_aliases')
    graphs={k:[] for k in modes};scores={k:[] for k in modes};queries={k:[] for k in modes}
    annotation_audit=[];raw_audit=[];differences=[];seen=set()
    for record in bundle['records']:
        system,tool=record['system'],record['tool'];ident=(system,tool)
        if ident in seen:raise ValueError('Duplicate tool/application record')
        seen.add(ident)
        refpath=base/'groundtruth_textual'/f'{system}.txt';nodes,gold=read_reference(refpath)
        pred,ann=parse_annotated(record)
        # This check detects a corrupt/transcribed annotation universe; FN still
        # stays outside the prediction. It does not repair missing annotations.
        declared={tuple(normal_name(r[k]) for k in ('source','target')) for r in record['connections'] if r['status'] in ('TP','FN')}
        if declared!=gold:raise ValueError(f'Annotated universe differs from reference: {ident}')
        directory=base/'results/recovery_correctness';suffix='-code2dfd-raw' if tool=='Code2DFD' else ''
        paths=[p for p in (directory/'raw_results'/tool).iterdir() if p.is_file() and
               (p.stem.casefold()==system+suffix if suffix else p.stem.split('_',1)[-1].casefold()==system)]
        af=[p for p in (directory/'processed_results'/('code2DFD' if tool=='Code2DFD' else tool)).iterdir()
            if p.name.casefold()==f'{system}-{tool.casefold()}-processed.txt']
        if len(paths)!=1 or len(af)!=1:raise ValueError('Missing/ambiguous raw export or alignment: '+str(ident))
        raw,raw_records=parse_raw(paths[0],tool);aligned,aligned_records=parse_raw(paths[0],tool,aliases(af[0]))
        raw_audit.extend({'system':system,'tool':tool,'mode':'raw_normalized',**r} for r in raw_records)
        raw_audit.extend({'system':system,'tool':tool,'mode':'raw_published_aliases',**r} for r in aligned_records)
        annotation_audit.extend({'system':system,'tool':tool,**r} for r in ann)
        for mode,edges in [('annotated',pred),('raw_normalized',raw),('raw_published_aliases',aligned)]:
            with context(study='replay',system=system,tool=tool,mode=mode):
                row,answers=evaluate(system,tool,nodes,gold,edges,mode)
                scores[mode].append(row);queries[mode].extend(answers)
                graphs[mode].append({'system':system,'tool':tool,'reference_nodes':sorted(nodes),
                  'reference_edges':sorted(gold),'prediction_edges':sorted(edges),'mode':mode,
                  'input_reference':refpath.relative_to(data).as_posix(),'reference_sha256':sha256(refpath)})
                info('REPLAY','RECORD_COMPLETE','Evaluate every ordered pair of distinct reference nodes.',
                     edges=len(edges),F1=row['f1'],wrong=row['wrong_answers'],queries=row['queries'])
        for mode,edges in [('raw_normalized',raw),('raw_published_aliases',aligned)]:
            differences.append({'system':system,'tool':tool,'mode':mode,'differs':pred!=edges,
              'only_annotated':sorted(pred-edges),'only_raw':sorted(edges-pred)})
    references=list((base/'groundtruth_textual').glob('*.txt'))
    missing=[{'system':p.stem,'tool':t,'reason':'No archived record; not an empty prediction'}
             for p in references for t in TOOLS if (p.stem,t) not in seen]
    dest=output/'replay';summaries={}
    for mode in modes:
        rs=scores[mode];comparison=rankings(rs)
        summaries[mode]={'records':len(rs),'applications':len({r['system'] for r in rs}),
           'ordered_pair_evaluations':sum(r['queries'] for r in rs),
           'records_with_errors':sum(r['wrong_answers']>0 for r in rs),
           'applications_with_errors':len({r['system'] for r in rs if r['wrong_answers']}),
           'paired_applications':len(comparison),'queries_per_paired_method':sum(r['queries'] for r in comparison),
           'ranking_reversals':sum(r['ranking_reversed'] for r in comparison),
           'rankings':comparison,'different_from_annotated':sum(r['differs'] for r in differences if r['mode']==mode)}
        write_json(dest/f'{mode}_graphs.json',graphs[mode]);write_csv(dest/f'{mode}_scores.csv',rs)
        write_csv(dest/f'{mode}_path_answers.csv',queries[mode]);write_csv(dest/f'{mode}_paired.csv',comparison)
    write_csv(output/'table_IX_replay.csv',summaries['annotated']['rankings'])
    write_json(dest/'annotation_records.json',annotation_audit);write_json(dest/'raw_records.json',raw_audit)
    write_json(dest/'direction_differences.json',differences);write_json(dest/'missing_records.json',missing)
    summaries['scope']='Source-study-annotated positive connections; FN excluded. Raw sensitivity variants disclose alignment rules.'
    write_json(dest/'summary.json',summaries)
    return summaries
