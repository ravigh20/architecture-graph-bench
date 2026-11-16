"""Sections VII-D/E: source-only M1/MP/M2 and leave-one-application-out membership.

A candidate is a same-namespace (Service, workload-template) pair, not a
runtime flow. Fitting labels come only from the other applications. Test labels
are joined AFTER probabilities and decisions have been fixed.
"""
from __future__ import annotations
from fractions import Fraction
from pathlib import Path
from .backends import load_inputs, pairs, extract, edges, score, stratum, candidate_witness
from .bookinfo import fit_strata, apply_fit, transfer_results
from .io import read_json, write_json, write_csv
from .execution_log import checkpoint, info, debug, context

METHODS={'name':'M1','prefix':'MP','selector':'M2'}


def load_population(data: Path, projects: list[str]):
    """Read source inventories and separately validate the frozen label scope."""
    refs=read_json(data/'study/reference.json')
    extra=read_json(data/'study/reference_guestbook.json')
    if set(refs)&set(extra): raise ValueError('Duplicate application references')
    refs.update(extra)
    inputs={}; gold={}; candidates=[]; inventories=[]; sources=[]; witnesses=[]
    for project in projects:
        inp=load_inputs(data/f'study/data/{project}/manifest.yaml',f'study/data/{project}/manifest.yaml')
        inputs[project]=inp
        g={s:refs[project]['queries'][s]['backends'] for s in refs[project]['services']}
        candidates_in_scope=pairs(inp)
        if set(g)!=set(inp.services) or not edges(g)<=set(candidates_in_scope):
            raise ValueError('Reference does not match the candidate scope: '+project)
        gold[project]=g
        inventories.append({'project':project,'services':len(inp.services),'workload_templates':len(inp.workloads),
                            'pairs':len(candidates_in_scope),'reference_edges':len(edges(g)),
                            'source_sha256':inp.source.digest,'excluded_resources':inp.excluded})
        for s,w in candidates_in_scope:
            candidates.append({'project':project,'service':s,'workload':w,'stratum':stratum(s,w),
                               'gold':int(w in g[s])})
        for s in sorted(inp.services):
            ns,name=s.split('/',1)
            sources.append({'project':project,'kind':'service_selector','resource':s,
                            'value':inp.services[s]['selector'],
                            'locator':inp.source.locate('Service',name,'spec/selector',ns)})
        for w in sorted(inp.workloads):
            ns,name=w.split('/',1)
            sources.append({'project':project,'kind':'workload_labels','resource':w,
                            'value':inp.workloads[w]['labels'],
                            'locator':inp.source.locate(inp.workloads[w]['kind'],name,'spec/template/metadata/labels',ns)})
        for s,w in sorted(edges(g)):
            witnesses.append({'project':project,**candidate_witness(inp,s,w)})
    return inputs,gold,candidates,inventories,sources,witnesses


def run(data: Path, output: Path, config: dict) -> dict:
    """Reconstruct each manifest; fit and evaluate each application exactly once."""
    c=config['membership'];projects=c['projects']
    if len(projects)<2 or len(set(projects))!=len(projects): raise ValueError('Need distinct test applications')
    checkpoint('MEMBERSHIP','Read four source snapshots and enumerate same-namespace candidates.')
    inputs,gold,candidates,inventories,source_fields,witnesses=load_population(data,projects)
    dest=output/'membership';predictions={};scores=[];queries=[];table=[]
    fits={};all_predictions=[];all_decisions=[];per_project={}
    for project in projects:
        with context(study='membership',project=project):
            checkpoint('MEMBERSHIP','Run M1 exact-name, MP hyphen-prefix and M2 selector joins.',application=project)
            inp=inputs[project]
            predicted=extract(inp, include_prefix=True)  # Contains no reference labels or expected outcomes.
            predictions[project]=predicted
            app_scores={}
            for name,g in predicted.items():
                result=score(g,gold[project],inp);app_scores[name]=result
                scores.append({'project':project,'method':METHODS[name],**{k:v for k,v in result.items() if k!='queries'}})
                for q in result['queries']:
                    for cardinality in (1,2):
                        state=q[f'ge{cardinality}']
                        queries.append({'project':project,'method':METHODS[name],'service':q['service'],
                          'minimum_backends':cardinality,'reference_answer':state['gold'],'prediction':state['pred'],
                          'wrong':state['gold']!=state['pred'],'reference_backends':q['reference'],
                          'predicted_backends':q['prediction']})
            checkpoint('MEMBERSHIP','Fit probabilities on all applications except this test application.',held_out=project)
            train=[r for r in candidates if r['project']!=project];test=[r for r in candidates if r['project']==project]
            fitted=fit_strata(train,c['strata'])
            n=len(train);k=sum(r['gold'] for r in train)
            # The prevalence comparator has no name-stratum feature. Use the
            # empirical training prevalence (not the held-out prevalence).
            prior=Fraction(k,n)
            fits[project]={'test_project':project,'training_projects':[p for p in projects if p!=project],
                          'training_pairs':n,'training_positive':k,'strata':fitted,'prevalence_exact':str(prior)}
            features=[{key:r[key] for key in ('project','service','workload','stratum')} for r in test]
            fixed=apply_fit(features,fitted)
            # Only now may test labels be read for evaluation.
            labels={(r['service'],r['workload']):r['gold'] for r in test}
            result,evaluated,decisions=transfer_results(fixed,labels,c['thresholds'])
            for r in evaluated:
                p_fixed=Fraction(9,10) if r['stratum']=='exact' else Fraction(1,10)
                r.update(fixed_09_probability=float(p_fixed),fixed_09_squared_error=float((p_fixed-r['gold'])**2),
                         fixed_09_squared_error_exact=str((p_fixed-r['gold'])**2),
                         prevalence_probability=float(prior),prevalence_squared_error=float((prior-r['gold'])**2),
                         prevalence_squared_error_exact=str((prior-r['gold'])**2))
            result['fixed_09_brier']=float(sum((Fraction(r['fixed_09_squared_error_exact']) for r in evaluated),Fraction())/len(evaluated))
            result['prevalence_brier']=float(sum((Fraction(r['prevalence_squared_error_exact']) for r in evaluated),Fraction())/len(evaluated))
            per_project[project]=result;all_predictions.extend(evaluated);all_decisions.extend(decisions)
            table.append({'application':project,'pairs':len(test),'reference_edges':len(edges(gold[project])),
                          **{f'{METHODS[m]}_edge_f1':r['f1'] for m,r in app_scores.items()},
                          **{f'{METHODS[m]}_wrong_answers':r['query_mismatches'] for m,r in app_scores.items()},
                          'queries':2*len(inp.services),'fitted_brier':result['brier'],
                          'hard_name_brier':result['hard_name_brier'],'fixed_09_brier':result['fixed_09_brier']})
            info('MEMBERSHIP','APPLICATION_COMPLETE','Calculated backend sets, query answers and held-out scores.',
                 application=project, pairs=len(test), fitted_brier=result['brier'],hard_name_brier=result['hard_name_brier'])
    sums={}
    for key,field in [('fitted','squared_error_exact'),('hard_name','hard_name_squared_error'),
                      ('fixed_09','fixed_09_squared_error_exact'),('prevalence','prevalence_squared_error_exact')]:
        v=sum((Fraction(r[field]) for r in all_predictions),Fraction())/len(all_predictions)
        sums[key]={'pair_weighted_brier':float(v),'pair_weighted_brier_exact':str(v),
                   'equal_system_brier':sum(per_project[p][{'fitted':'brier','hard_name':'hard_name_brier',
                                      'fixed_09':'fixed_09_brier','prevalence':'prevalence_brier'}[key]] for p in projects)/len(projects)}
    summary={'applications':len(projects),'pairs':len(candidates),'positive_pairs':sum(r['gold'] for r in candidates),
             'cardinality_queries':sum(2*len(inputs[p].services) for p in projects),
             'service_selector_records':sum(len(inputs[p].services) for p in projects),
             'workload_label_records':sum(len(inputs[p].workloads) for p in projects),
             'positive_witnesses':len(witnesses),'methods':scores,'per_application':per_project,'baselines':sums,
             'scope':'Service/workload membership, not network reachability; references share selector semantics.'}
    write_json(dest/'predictions.json',predictions);write_csv(dest/'method_scores.csv',scores)
    write_csv(dest/'queries.csv',queries);write_json(dest/'queries.json',queries)
    write_csv(dest/'candidates.csv',candidates);write_json(dest/'source_field_records.json',source_fields)
    write_json(dest/'reference_edge_witnesses.json',witnesses);write_json(dest/'inventory.json',inventories)
    write_json(dest/'confidence_folds.json',fits);write_csv(dest/'confidence_predictions.csv',all_predictions)
    write_csv(dest/'confidence_decisions.csv',all_decisions);write_json(dest/'summary.json',summary)
    write_csv(output/'table_VIII_membership.csv',table)
    return summary
