"""Final paper Section VII-D: Bookinfo reconstruction and one held-out transfer.

Only Sock Shop, Voting App and Guestbook labels fit probabilities. Bookinfo
labels are consulted after probabilities are fixed, solely for evaluation.
"""
from __future__ import annotations
from .execution_log import checkpoint, info, debug, context
from collections import Counter
from fractions import Fraction
from pathlib import Path
from .backends import load_inputs, pairs, extract, edges, score, stratum, candidate_witness
from .io import read_json, write_json, write_csv, sha256


def fit_strata(training: list[dict], strata: list[str], positive: int=1, total: int=2) -> dict:
    """Fit Laplace-smoothed membership probabilities from training pairs only."""
    if not training: raise ValueError('Empty fitting population')
    if not 0 < positive < total: raise ValueError('Invalid smoothing pseudocounts')
    # Laplace smoothing is fitted to training projects only. Empty strata
    # receive the declared pseudocount estimate rather than a fabricated fit.
    result={}
    for category in strata:
        records=[r for r in training if r['stratum']==category]
        n=len(records);k=sum(r['gold'] for r in records)
        p=Fraction(k+positive,n+total)
        info("BOOKINFO", "FIT_STRATUM", "Fit p=(k+positive)/(n+total) using training labels only.",
             stratum=category, n=n, k=k, positive_pseudocount=positive, total_pseudocount=total,
             p_exact=str(p), p=float(p))
        result[category]={'fitting_pairs':n,'positive_pairs':k,'p':float(p),'p_exact':str(p),
                          'formula':'(k + positive_pseudocount) / (n + total_pseudocount)'}
    return result


def apply_fit(test_without_labels: list[dict], fits: dict) -> list[dict]:
    """The argument deliberately contains identifiers/features, never test labels."""
    rows=[]
    for row in test_without_labels:
        if 'gold' in row or 'reference' in row: raise ValueError('Prediction input must not contain held-out labels')
        p=Fraction(fits[row['stratum']]['p_exact'])
        prediction='T' if p>Fraction(1,2) else 'F' if p<Fraction(1,2) else 'U'
        # Predict presence/absence from p, then select confidence in that
        # prediction. Confidence is not the probability of source entailment.
        confidence=max(p,1-p)
        debug("BOOKINFO", "PREDICT_PAIR", "Apply the frozen training estimate without a held-out label.",
              service=row['service'], workload=row['workload'], stratum=row['stratum'],
              p_exact=str(p), prediction=prediction, confidence_exact=str(confidence))
        rows.append({**row,'p':float(p),'p_exact':str(p),'prediction':prediction,
                     'confidence':float(confidence),'confidence_exact':str(confidence)})
    return rows


def transfer_results(predictions: list[dict], labels: dict, thresholds: list[float]) -> tuple[dict,list,list]:
    """Evaluate already fixed held-out predictions and threshold decisions.

    Gold test labels enter here, after fit and prediction. Brier error concerns
    factual backend membership and must not be reported as evidence entailment.
    """
    rows=[]
    for pred in predictions:
        key=(pred['service'],pred['workload'])
        if key not in labels: raise ValueError('Missing held-out evaluation label')
        y=labels[key];p=Fraction(pred['p_exact'])
        raw=int(pred['stratum']=='exact')
        rows.append({**pred,'gold':y,'hard_name_prediction':raw,'squared_error':float((p-y)**2),
                     'squared_error_exact':str((p-y)**2),'hard_name_squared_error':(raw-y)**2})
    if not rows: raise ValueError('Empty held-out population')
    brier=sum((Fraction(r['squared_error_exact']) for r in rows),Fraction())/len(rows)
    hard=Fraction(sum(r['hard_name_squared_error'] for r in rows),len(rows))
    counts=[];decisions=[]
    for theta in thresholds:
        if not 0<=theta<=1: raise ValueError('Threshold outside [0,1]')
        keep=[r for r in rows if r['prediction'] in ('T','F') and Fraction(r['confidence_exact'])>=Fraction(str(theta))]
        accepted={(r['service'],r['workload']) for r in keep}
        errors=sum((r['prediction']=='T')!=bool(r['gold']) for r in keep)
        positive=[r for r in keep if r['prediction']=='T'];negative=[r for r in keep if r['prediction']=='F']
        total_positive=sum(r['gold'] for r in rows);correct_positive=sum(r['gold'] for r in positive)
        counts.append({'threshold':theta,'accepted':len(keep),'population':len(rows),'errors':errors,
                       'coverage':len(keep)/len(rows),'accepted_positive':len(positive),'accepted_negative':len(negative),
                       'accepted_true_edges':sum(r['gold'] for r in keep),
                       'withheld_true_edges':total_positive-sum(r['gold'] for r in keep),
                       'positive_precision':correct_positive/len(positive) if positive else None,
                       'true_edge_recall':correct_positive/total_positive if total_positive else None})
        info("BOOKINFO", "THRESHOLD", "Select fixed predictions at this confidence threshold.",
             threshold=theta, accepted=len(keep), population=len(rows), errors=errors,
             accepted_positive=len(positive), accepted_negative=len(negative),
             withheld_true_edges=total_positive-sum(r['gold'] for r in keep))
        for row in rows:
            accept=(row['service'],row['workload']) in accepted
            decisions.append({'threshold':theta,**row,'accepted':accept,
                              'error_if_accepted':accept and ((row['prediction']=='T')!=bool(row['gold']))})
    result={'test_pairs':len(rows),'true_edges':sum(r['gold'] for r in rows),
            'brier':float(brier),'brier_exact':str(brier),'hard_name_brier':float(hard),'hard_name_brier_exact':str(hard),
            'thresholds':counts,'target':'Factual Service-to-workload membership; not source entailment or UCR.'}
    info("BOOKINFO", "BRIER", "Average squared probability errors over held-out candidate pairs.",
         pairs=len(rows), fitted_brier=float(brier), fitted_brier_exact=str(brier),
         hard_name_brier=float(hard))
    return result,rows,decisions


def run(data: Path, output: Path, config: dict) -> dict:
    """Run Bookinfo extraction and transfer confidence from the other three apps.

    The saved model record is an input to re-scoring, not a fresh model call.
    Training/test project separation is checked before any fitting occurs.
    """
    checkpoint("BOOKINFO", "Load Bookinfo test evidence and separate confidence-fitting projects.")
    c=config['bookinfo'];root=data/'study';dest=output/'bookinfo' 
    test=c['test_project'];training=c['training_projects']
    if len(set(training))!=len(training) or test in training: raise ValueError('Training/test project overlap')
    info("BOOKINFO", "SPLIT", "Keep the test application out of probability fitting.",
         test_project=test, fitting_projects=training)
    reference=read_json(root/'reference.json');extra=read_json(root/'reference_guestbook.json')
    if set(reference)&set(extra): raise ValueError('Duplicate project reference')
    reference.update(extra)
    inventories=[];all_candidates=[];source_records=[];edge_witnesses=[];inputs={};gold_sets={}
    for project in [test,*training]:
        inp=load_inputs(root/'data'/project/'manifest.yaml',f'study/data/{project}/manifest.yaml')
        inputs[project]=inp
        gold={s:reference[project]['queries'][s]['backends'] for s in reference[project]['services']}
        candidates=pairs(inp)
        if set(gold)!=set(inp.services) or not edges(gold)<=set(candidates):
            raise ValueError('Reference scope mismatches manifest: '+project)
        gold_sets[project]=gold
        inventories.append({'project':project,'role':'held_out_test' if project==test else 'confidence_fitting',
                            'services':len(inp.services),'workload_templates':len(inp.workloads),'candidate_pairs':len(candidates),
                            'positive_pairs':len(edges(gold)),'field_records':len(inp.services)+len(inp.workloads),
                            'excluded_resources':inp.excluded,'input_sha256':inp.source.digest})
        for s,w in candidates:
            all_candidates.append({'project':project,'service':s,'workload':w,'stratum':stratum(s,w),
                                   'gold':int(w in gold[s])})
        for s in sorted(inp.services):
            ns,name=s.split('/',1)
            source_records.append({'project':project,'record_type':'service_selector','resource':s,
                                    'value':inp.services[s]['selector'],'locator':inp.source.locate('Service',name,'spec/selector',ns)})
        for w in sorted(inp.workloads):
            ns,name=w.split('/',1)
            source_records.append({'project':project,'record_type':'workload_labels','resource':w,
                                    'value':inp.workloads[w]['labels'],
                                    'locator':inp.source.locate(inp.workloads[w]['kind'],name,'spec/template/metadata/labels',ns)})
        for s,w in sorted(edges(gold)):
            edge_witnesses.append({'project':project,'reference_role':'supplied_frozen_reference',**candidate_witness(inp,s,w)})
    inp=inputs[test]
    # Pure deterministic extraction reads only parsed source objects.
    checkpoint("BOOKINFO", "Reconstruct backend sets from the Bookinfo YAML only.")
    with context(study="bookinfo", project=test):
        predictions=extract(inp)
    saved=root/'llm'/f'{test}.json'
    predictions['saved_llm']=read_json(saved)
    info("BOOKINFO", "SAVED_MODEL_INPUT", "Re-score a retained prediction record; no model API call is made.",
         file=saved, sha256=sha256(saved), processing="PRESERVED_LLM_RESCORING")
    scores={name:score(g,gold_sets[test],inp) for name,g in predictions.items()}
    rows=[];query_rows=[]
    for method,result in scores.items():
        result['Ds']=result['query_mismatches']/result['query_total']
        rows.append({'method':method,'predicted_edges':result['predicted_count'],'tp':result['tp'],
                     'fp':result['fp'],'fn':result['fn'],'edge_f1':result['f1'],
                     'wrong_answers':result['query_mismatches'],'queries':result['query_total'],'Ds':result['Ds'],
                     'processing':'PRESERVED_LLM_RESCORING' if method=='saved_llm' else 'FRESH_DETERMINISTIC_EXTRACTION'})
        info("BOOKINFO", "METHOD_SCORE", "Compare predicted backend sets and their Boolean query answers.",
             method=method, tp=result['tp'], fp=result['fp'], fn=result['fn'],
             edge_F1=result['f1'], wrong_answers=result['query_mismatches'],
             queries=result['query_total'], Ds=result['Ds'])
        for q in result['queries']:
            for n in (1,2):
                debug("BOOKINFO", "QUERY", "Ask whether this Service selects at least n distinct templates.",
                      method=method, service=q['service'], minimum=n,
                      reference=q[f'ge{n}']['gold'], prediction=q[f'ge{n}']['pred'],
                      predicted_backends=q['prediction'])
                query_rows.append({'method':method,'query':f"{q['service']}::at_least_{n}",'service':q['service'],
                                   'predicate':f'at_least_{n}_distinct_workload_templates',
                                   'architectural_reference':'T' if q[f'ge{n}']['gold'] else 'F',
                                   'prediction':'T' if q[f'ge{n}']['pred'] else 'F',
                                   'reference_backends':q['reference'],'predicted_backends':q['prediction'],
                                   'witnesses':[candidate_witness(inp,q['service'],w) for w in q['prediction'] if w in inp.workloads],
                                   'scope':'Declared backend membership, not runtime paths.'})
    fit_rows=[r for r in all_candidates if r['project'] in training]
    held_out=[r for r in all_candidates if r['project']==test]
    checkpoint("BOOKINFO", "Fit on other applications, then predict Bookinfo without test labels.",
               fitting_pairs=len(fit_rows), held_out_pairs=len(held_out))
    fits=fit_strata(fit_rows,c['strata'],c['laplace_positive'],c['laplace_total'])
    feature_rows=[{k:v for k,v in r.items() if k!='gold'} for r in held_out]
    fitted=apply_fit(feature_rows,fits)
    labels={(r['service'],r['workload']):r['gold'] for r in held_out}
    checkpoint("BOOKINFO", "Evaluate the frozen held-out predictions and apply acceptance thresholds.")
    confidence,scored,decisions=transfer_results(fitted,labels,c['thresholds'])
    confidence.update(training_projects=training,test_project=test,training_pairs=len(fit_rows),strata=fits,
                      saved_response_metadata={'file':f'study/llm/{test}.json','sha256':sha256(saved),
                       'representation':'Retained structured prediction record; not a new API call or full session transcript.',
                       'seed':None,'temperature':None,'dated_model_snapshot':None})
    checkpoint("BOOKINFO", "Write backend predictions, witnesses, fitting records and confidence evidence.")
    write_json(dest/'predictions.json',predictions);write_json(dest/'scores.json',scores)
    write_csv(dest/'method_scores.csv',rows);write_json(dest/'queries.json',query_rows);write_csv(dest/'queries.csv',query_rows)
    write_csv(dest/'inventory.csv',inventories);write_json(dest/'inventory.json',inventories)
    write_csv(dest/'candidate_pairs.csv',all_candidates)
    write_json(dest/'source_field_records.json',source_records);write_json(dest/'reference_edge_witnesses.json',edge_witnesses)
    write_json(dest/'candidate_witnesses.json',[{'project':test,**candidate_witness(inp,s,w)} for s,w in pairs(inp)])
    write_json(dest/'reference_used.json',{p:reference[p] for p in [test,*training]})
    write_json(dest/'saved_prediction_record.json',read_json(saved))
    write_csv(dest/'confidence_fitting_pairs.csv',fit_rows);write_csv(dest/'confidence_test_predictions.csv',scored)
    write_csv(dest/'confidence_decisions.csv',decisions);write_csv(dest/'confidence_thresholds.csv',confidence['thresholds'])
    write_json(dest/'confidence_fit.json',{'training_projects':training,'test_project':test,
               'fit_pair_count':len(fit_rows),'strata':fits,'test_labels_used_for_fitting':False})
    write_json(dest/'confidence.json',confidence)
    footprint={'bookinfo':{'field_records':sum(r['field_records'] for r in inventories if r['project']==test),
                           'positive_edge_witnesses':len(edges(gold_sets[test])),'queries':2*len(inp.services)},
               'confidence_fitting':{'field_records':sum(r['field_records'] for r in inventories if r['project'] in training),
                                     'positive_edge_witnesses':sum(len(edges(gold_sets[p])) for p in training)},
               'human_annotation_hours':None,'human_agreement':None,'meaning':'Review work items, not measured human effort.'}
    write_json(dest/'review_footprint.json',footprint)
    summary={'methods':rows,'confidence':confidence,'inventory':inventories,'review_footprint':footprint,
             'boundary':'Frozen model-assisted reference, no independent human adjudication; one saved LLM prediction record.'}
    write_json(dest/'summary.json',summary)
    return summary
