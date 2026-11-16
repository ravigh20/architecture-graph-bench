"""Submission-candidate evidence catalog: calculated artifacts versus descriptive content."""
from __future__ import annotations
from .execution_log import checkpoint, info
from collections import defaultdict
import csv,hashlib,json,difflib
from pathlib import Path
from .io import read_json,write_json,write_csv,sha256,inventory

TABLES={
'I':'table_I_related_work','II':'table_II_support_transitions','III':'table_III_tasks',
'IV':'table_IV_conventions','V':'table_V_structural_arithmetic','VI':'table_VI_support_controls',
'VII':'table_VII_boutique','VIII':'table_VIII_membership','IX':'table_IX_replay'}
FIGURES=['representation_validity','assertion_graph','dual_reference','evaluation_layers','diagnostic_workflow','weight_sensitivity']


def descriptive_tables(output:Path):
    """Export descriptive paper definitions, separately from measured evidence."""
    related=[
        ('Trace-link studies [2]–[4], [13]','Documentation/model/code links and inconsistencies.','Relates source support to typed security assertions and condition-specific evidence states.'),
        ('SARIF; static-tool comparison [14], [15]','Recovered structure and its characteristics.','Separates structural error from selected query consequences.'),
        ('ArchAgent; ArchBench [9], [10]','Architecture recovery; extensible architecture-task evaluation.','Specifies structural, query, and evidence-support evaluation for reconstructed graphs.'),
        ('SAKE [11]','Architectural-knowledge question answering.','Evaluates a recovered graph and the support for its assertions.'),
        ('EVerest [49]','Security-labeled requirements, architecture, code, and trace links.','Evaluates support labels as available security evidence changes.'),
        ('AuthentiCity [37]','Multi-source graphs, provenance-aware queries, and answerability.','Applies related concerns to software-security boundaries, controls, and reconstruction errors.')]
    write_csv(output/(TABLES['I']+'.csv'),[dict(work=a,reported_target=b,distinction=c) for a,b,c in related])
    task=[('T1','Typed entities','Canonical node and type.'),('T2','Typed relationships','Directed typed edge.'),
          ('T3','Zones and boundaries','Membership and crossing.'),('T4','Identity and controls','Binding or mediation assertion.'),
          ('T5','Provenance','Source-link validity and sufficient support.'),('T6','Epistemic state','State on aligned assertion.'),
          ('T7','Query preservation','Outcome and supporting witness.')]
    write_csv(output/(TABLES['III']+'.csv'),[dict(task=a,recovery_target=b,scoring_object=c) for a,b,c in task])
    conventions=[('Gold and prediction both empty','F1 = N/A; disclose excluded count.'),
        ('Exactly one set empty','F1 = 0 for the nonempty scoring population.'),
        ('No accepted singleton claims','UCR = N/A; coverage = 0.'),('No applicable queries','Divergence is undefined.'),
        ('Unsupported negative conclusion','Unknown unless absence is justified.'),
        ('Outside-scope assertion','Unadjudicated; no automatic truth label.'),
        ('Conflicting current sources','Preserve conflict; disclose precedence.'),
        ('Only matched attributes scored','Also report alignment coverage and recall.'),
        ('Malformed or failed output','Retain in the run inventory; do not silently drop.')]
    write_csv(output/(TABLES['IV']+'.csv'),[dict(condition=a,treatment=b) for a,b in conventions])


def read_csv(path):
    """Read a current-run CSV as structured row records."""
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def export_tables(output:Path):
    """Render current-run tables in alternate formats without changing values."""
    for numeral,stem in TABLES.items():
        p=output/(stem+'.csv')
        if not p.is_file():continue
        rows=read_csv(p);keys=list(rows[0]) if rows else []
        kind='DESCRIPTIVE_FROM_MANUSCRIPT' if numeral in ('I','III','IV') else 'COMPUTED_OR_COMPUTATION_LEDGER'
        write_json(output/'tables'/(stem+'.json'),{'table':numeral,'kind':kind,'rows':rows})
        def cell(v):return str(v).replace('|','\\|').replace('\n',' ')
        text=[f'# Table {numeral}: '+stem.split('_',2)[2].replace('_',' '),'',f'Type: {kind}.','',
              '| '+' | '.join(keys)+' |','| '+' | '.join('---' for _ in keys)+' |']
        text += ['| '+' | '.join(cell(row[k]) if row[k]!='' else 'N/A' for k in keys)+' |' for row in rows]
        path=output/'tables'/(stem+'.md');path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(text)+'\n',encoding='utf-8')


def source_ledger(data:Path,output:Path) -> dict:
    """Resolve recorded locators against local source bytes and retain excerpts."""
    by_digest=defaultdict(list)
    for p in sorted(data.rglob('*')):
        if p.is_file():by_digest[sha256(p)].append(p)
    locators=[]
    def walk(v):
        if isinstance(v,dict):
            if all(k in v for k in ['file','lines','sha256']):locators.append(v)
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    for name in ['boutique/assertions.json','boutique/queries.json','boutique/reference_used.json',
                 'membership/source_field_records.json','membership/reference_edge_witnesses.json']:
        path=output/name
        if path.exists():walk(read_json(path))
    unique={json.dumps(v,sort_keys=True):v for v in locators};records=[]
    for text,loc in sorted(unique.items()):
        rec={'id':'loc-'+hashlib.sha256(text.encode()).hexdigest()[:16],'locator':loc,
             'status':'UNRESOLVED_SOURCE','source':None,'excerpt':None}
        matches=by_digest.get(loc['sha256'],[])
        if matches:
            p=next((x for x in matches if x.name==Path(loc['file']).name),matches[0])
            lines=p.read_text(encoding='utf-8').splitlines();lo,hi=loc['lines']
            if isinstance(lo,int) and isinstance(hi,int) and 1<=lo<=hi<=len(lines):
                rec.update(status='RESOLVED',source=p.relative_to(data).as_posix(),
                           excerpt='\n'.join(f'{i}: {lines[i-1]}' for i in range(lo,hi+1)))
            else:rec.update(status='INVALID_RANGE',source=p.relative_to(data).as_posix())
        records.append(rec)
    write_json(output/'evidence/source_locator_ledger.json',records)
    write_csv(output/'evidence/source_locator_ledger.csv',records,fields=['id','locator','status','source','excerpt'])
    return {'unique':len(records),'resolved':sum(r['status']=='RESOLVED' for r in records),
            'unresolved':sum(r['status']!='RESOLVED' for r in records)}


def graph_exports(output:Path):
    """Write portable DOT files from current predictions, never source-paper images."""
    dest=output/'graphs';dest.mkdir(exist_ok=True)
    def save(name,edges,nodes=()):
        lines=['digraph architecture {','  rankdir=LR;']
        lines += ['  '+json.dumps(n)+';' for n in nodes]
        lines += ['  '+json.dumps(a)+' -> '+json.dumps(b)+';' for a,b in edges]
        (dest/(name+'.dot')).write_text('\n'.join(lines+['}'])+'\n',encoding='utf-8')
    for key,g in read_json(output/'boutique/graphs.json').items():
        save(key.replace('/','_'),[(e['source'],e['target']) for e in g['edges']],[n['id'] for n in g['nodes']])
    for project,methods in read_json(output/'membership/predictions.json').items():
        for method,sets in methods.items():
            save(project+'_'+method,[('svc:'+s,'workload:'+w) for s,ws in sets.items() for w in ws])
    for g in read_json(output/'replay/annotated_graphs.json'):
        save(g['system']+'_'+g['tool'],g['prediction_edges'],g['reference_nodes'])


def all_evidence(data:Path,output:Path,plots:bool) -> dict:
    """Index calculated artifacts in this manuscript's table/section numbering."""
    checkpoint('EVIDENCE','Write the nine paper tables, six figures and their supporting records.')
    d=read_json(output/'diagnostics/summary.json');m=read_json(output/'membership/summary.json')
    r=read_json(output/'replay/summary.json');c=read_json(output/'calibration/summary.json')
    b=read_json(output/'boutique/metrics.json');qs=read_json(output/'boutique/queries.json')
    graphs=read_json(output/'boutique/graphs.json')
    edge_set=lambda g:{(e['source'],e['relation'],e['target']) for e in g['edges']}
    findings={'diagnostics':d,'membership':m,'replay':r,'edge_proposal_calibration':c,
       'boutique':{'cases':b,'masked_graphs_identical':edge_set(graphs['masked/M2'])==edge_set(graphs['masked/M2-CW']),
                   'unsupported_closed_world_queries':[q['query'] for q in qs if q['method']=='M2-CW' and q['unsupported']]},
       'reference_mode':read_json(output/'boutique/reference_provenance.json')['mode']}
    write_json(output/'evidence/calculated_findings.json',findings)
    descriptive_tables(output);export_tables(output)
    if plots:
        from .paper_figures import generate
        generate(output)
    graph_exports(output);locs=source_ledger(data,output)
    a=data/'public_case/source/kubernetes-manifests.yaml';bb=data/'public_case/source/upstream-commit.yaml'
    if bb.exists():
        text=''.join(difflib.unified_diff(a.read_text().splitlines(keepends=True),bb.read_text().splitlines(keepends=True),
                      fromfile='retained_experiment.yaml',tofile='bundled_upstream_candidate.yaml'))
        (output/'boutique/source_bytes.diff').write_text(text,encoding='utf-8')
    review={'manifest_service_selectors':m['service_selector_records'],
       'manifest_workload_label_maps':m['workload_label_records'],'manifest_positive_witnesses':m['positive_witnesses'],
       'candidate_pairs':m['pairs'],'cardinality_queries':m['cardinality_queries'],
       'boutique_nodes':b[0]['nodes'],'boutique_edges':b[0]['tp']+b[0]['fn'],'boutique_queries':b[0]['query_count'],
       'external_references_reused':r['annotated']['applications'],
       'human_review_time':None,'independent_human_annotations':False,
       'interpretation':'Record counts are not elapsed time or additional independent annotations.'}
    write_json(output/'evidence/review_footprint.json',review)
    records=[]
    def add(ident,loc,kind,inputs,algorithm,files,boundary=''):
        records.append({'id':ident,'paper_location':loc,'kind':kind,'inputs':inputs,'algorithm':algorithm,'outputs':files,
                        'status':'GENERATED' if all((output/p).is_file() for p in files) else 'NOT_GENERATED','boundary':boundary})
    for n,stem in TABLES.items():
        desc=n in ('I','III','IV')
        add('table_'+n,'Table '+n,'DESCRIPTIVE_FROM_MANUSCRIPT' if desc else 'COMPUTED_EVIDENCE',
            ['method definitions'] if desc else ['study-specific inputs and current calculated outputs'],
            'See METHOD_MAP.md',[stem+'.csv','tables/'+stem+'.json'])
    for i,stem in enumerate(FIGURES,1):
        add('figure_'+str(i),'Figure '+str(i),'COMPUTED_PLOT' if i==6 else 'METHOD_ILLUSTRATION',
          ['diagnostics/weight_points.csv'] if i==6 else ['declared method layout'],
          'paper_figures.generate',[f'figures/figure_{i}_{stem}.{ext}' for ext in ('png','svg')],
          'Illustrations are not empirical observations; plots use current-run data.')
    extra=[
      ('bridge','Sections V-A, VI-A','diagnostics.run',['experiment_config.json'],['diagnostics/bridge_graphs.json','diagnostics/bridge_results.csv','diagnostics/bridge_query_witnesses.json']),
      ('support','Sections V-B, VI-B','diagnostics.run',['experiment_config.json'],['diagnostics/generated_support_records.json','diagnostics/support_decisions.csv','diagnostics/support_summary.csv']),
      ('weights','Section VI-C','diagnostics.run',['experiment_config.json'],['diagnostics/weight_settings.csv','diagnostics/weight_points.csv']),
      ('boutique','Sections VII-A–C','boutique.run',['Boutique YAML','fixed reference and queries'],['boutique/graphs.json','boutique/assertions.json','boutique/queries.json','boutique/mask.json']),
      ('membership','Sections VII-D/E','membership.run',['four manifests and backend references'],['membership/predictions.json','membership/method_scores.csv','membership/queries.json']),
      ('membership_confidence','Section VII-E','membership.run',['same-namespace pairs; other-application labels'],['membership/confidence_folds.json','membership/confidence_predictions.csv','membership/confidence_decisions.csv']),
      ('annotated_replay','Section VII-F','replay.run',['annotated TP/FP/FN source records and reference DFDs'],['replay/annotated_graphs.json','replay/annotation_records.json','replay/annotated_path_answers.csv']),
      ('raw_sensitivity','Sections VII-F/G','replay.run; calibration.run',['raw JSON/SVG, optional component aliases'],['replay/raw_normalized_graphs.json','replay/raw_published_aliases_graphs.json','replay/direction_differences.json','calibration/raw_normalized/results.json']),
      ('proposal_calibration','Section VII-G','calibration.run',['current paired positive proposals'],['calibration/annotated/folds.json','calibration/annotated/proposals.csv','calibration/annotated/bins.csv','calibration/annotated/selection_decisions.csv','calibration/annotated/results.json']),
      ('review_footprint','Section VIII','evidence.all_evidence',['source inventories and current-run records'],['evidence/review_footprint.json','membership/source_field_records.json','membership/reference_edge_witnesses.json']),
      ('source_binding','Section IX','boutique.run; evidence.source_ledger',['retained source bytes'],['boutique/source_comparison.json','boutique/source_bytes.diff','evidence/source_locator_ledger.json']),
      ('findings','Sections VI–IX','evidence.all_evidence',['current computed records'],['evidence/calculated_findings.json'])]
    for ident,loc,algorithm,inputs,files in extra:add(ident,loc,'COMPUTED_EVIDENCE',inputs,algorithm,files)
    write_json(output/'evidence/evidence_index.json',records);write_csv(output/'evidence/evidence_index.csv',records)
    missing=[x['id'] for x in records if x['status']=='NOT_GENERATED']
    coverage={'registered_groups':len(records),'generated_groups':len(records)-len(missing),'missing':missing,
      'source_locators':locs,'reference_mode':findings['reference_mode'],'human_validation_performed':False,
      'llm_runs':'No new LLM inference; related-work aggregate scores are not experiments of this implementation.',
      'not_measured':['runtime security','source entailment','independent human adjudication','reviewer timing'],
      'scope':'Uploaded proofread submission candidate; raw-alignment conventions and acquisition qualifications are explicit.'}
    write_json(output/'evidence/coverage.json',coverage)
    text=[ '# Generated evidence — proofread submission candidate','',
       'Start with the calculated CSV tables in this directory. Follow each query back to source records.','',
       '| Output | Meaning |','|---|---|',
       '| `table_V_structural_arithmetic.csv` | Single-edge and attribute perturbations. |',
       '| `table_VI_support_controls.csv` | Four policies over all structured support states. |',
       '| `table_VII_boutique.csv` | Full/masked M1/M2/M2-CW reconstruction. |',
       '| `table_VIII_membership.csv` | Four-application M1/MP/M2 and held-out membership confidence. |',
       '| `table_IX_replay.csv` | Annotated connection/path results for ten paired applications. |',
       '| `calibration/annotated/results.json` | Positive-proposal calibration, ECE and selection. |','',
       '## Trace the evidence','',
       '`boutique/queries.json` records Q2/Q4 paths and source locators. '
       '`membership/confidence_predictions.csv` records each held-out pair. '
       '`replay/annotation_records.json` preserves source-study labels and acquisition locations. '
       '`calibration/annotated/folds.json` shows exactly which other applications fitted each score.','',
       '## Scope','',
       'The default replay uses annotated TP/FP connection records, not rerun external tools. '
       'Raw directions are separately evaluated using explicitly named alignment variants. '
       'Input annotations are a documented browser transcription; raw exports are retained projections. '
       'See `validation/VERIFICATION.md` in the code package for claim-level checks and the unresolved raw-sensitivity threshold statement. '
       'Tables I, III and IV and Figures 1–5 describe the method; they are not new observations.','',
       'Complete mapping: `evidence/evidence_index.csv`.']
    (output/'EVIDENCE_README.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    info('EVIDENCE','COMPLETE','Wrote evidence catalog and source ledger.',groups=len(records),resolved=locs['resolved'])
    if locs['unresolved']:raise ValueError('Unresolved YAML source locators')
    if plots and missing:raise ValueError('Missing output files: '+str(missing))
    return coverage
