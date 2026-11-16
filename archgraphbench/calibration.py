"""Section VII-G: leave-one-application-out correctness of POSITIVE edge proposals.

Unlike membership prediction, a low probability here does not assert a negative
edge. Every candidate is an edge proposed by at least one tool. Selection uses
c >= theta directly (NOT max(c,1-c)). Self-loops and extra endpoints remain.
"""
from __future__ import annotations
from fractions import Fraction
from pathlib import Path
from .io import read_json,write_json,write_csv
from .execution_log import checkpoint,info,debug,context

STRATA=('both','code_only','micro_only')


def proposal_population(graphs:list[dict]):
    """Union proposals within each paired system; count reference edges for recall."""
    indexed={(g['system'],g['tool']):g for g in graphs}
    common=sorted({s for s,t in indexed if t=='Code2DFD'} & {s for s,t in indexed if t=='MicroDepGraph'})
    rows=[];reference_count=0
    for name in common:
        c=indexed[name,'Code2DFD'];m=indexed[name,'MicroDepGraph']
        gold=set(map(tuple,c['reference_edges']))
        if gold!=set(map(tuple,m['reference_edges'])):raise ValueError('Paired tools need the same reference')
        pc,pm=set(map(tuple,c['prediction_edges'])),set(map(tuple,m['prediction_edges']))
        reference_count+=len(gold)
        for a,b in sorted(pc|pm):
            rows.append({'system':name,'source':a,'target':b,
              'stratum':'both' if (a,b) in pc&pm else 'code_only' if (a,b) in pc else 'micro_only',
              'gold':int((a,b) in gold)})
    if not rows or len(common)<2:raise ValueError('Need at least two common applications with proposals')
    return rows,reference_count,common


def fit_predict(training:list[dict],features:list[dict]):
    """Compute c=(k+1)/(n+2) from other systems; reject labels in test features."""
    if any('gold' in r for r in features):raise ValueError('Test labels passed to probability estimator')
    fit={};out=[]
    for group in STRATA:
        keep=[r for r in training if r['stratum']==group];n=len(keep);k=sum(r['gold'] for r in keep)
        p=Fraction(k+1,n+2)
        fit[group]={'n':n,'k':k,'c':float(p),'c_exact':str(p)}
    for r in features:
        out.append({**r,'c':fit[r['stratum']]['c'],'c_exact':fit[r['stratum']]['c_exact']})
        debug('CALIBRATION','PROPOSAL','Apply a frozen stratum estimate without reading the held-out label.',system=r.get('system'),source=r.get('source'),target=r.get('target'),stratum=r['stratum'],probability=fit[r['stratum']]['c'])
    return fit,out


def reliability_bins(rows:list[dict],bins:int,field:str):
    """ECE on fixed equal-width, right-closed bins; p=0 belongs in bin 1.

    Sum count/N * abs(mean_probability - observed_correctness). Bin boundaries
    are rational, avoiding float rounding that could move .9 across a boundary.
    Empty bins are retained with undefined means and zero ECE contribution.
    """
    if not rows or bins<=0:raise ValueError('Need predictions and a positive bin count')
    result=[];ece=Fraction()
    for i in range(bins):
        lo,hi=Fraction(i,bins),Fraction(i+1,bins)
        keep=[r for r in rows if (lo<Fraction(r[field])<=hi or i==0 and Fraction(r[field])==0)]
        if keep:
            mean=sum((Fraction(r[field]) for r in keep),Fraction())/len(keep)
            observed=Fraction(sum(r['gold'] for r in keep),len(keep));gap=abs(mean-observed)
            contribution=Fraction(len(keep),len(rows))*gap;ece+=contribution
        else:mean=observed=gap=None;contribution=Fraction()
        result.append({'bin':i+1,'lower':float(lo),'upper':float(hi),'count':len(keep),
          'mean_probability':float(mean) if mean is not None else None,
          'observed_correctness':float(observed) if observed is not None else None,
          'absolute_gap':float(gap) if gap is not None else None,'ece_contribution':float(contribution),
          'interval':'[0, upper]' if i==0 else '(lower, upper]'})
    if sum(x['count'] for x in result)!=len(rows):raise ValueError('Probability outside bin range')
    return float(ece),result


def evaluate(rows:list[dict],reference_count:int,thresholds:list[float],fixed:Fraction):
    """Score frozen positive-proposal probabilities and retain every decision."""
    rows=[{**r,'fixed_exact':str(fixed),'fixed':float(fixed)} for r in rows]
    brier=sum((Fraction(r['c_exact'])-r['gold'])**2 for r in rows)/len(rows)
    fixed_brier=sum((fixed-r['gold'])**2 for r in rows)/len(rows)
    bins={};ece={}
    for n in (10,5):
        for field,label in [('c_exact','fitted'),('fixed_exact','fixed_09')]:
            value,binrows=reliability_bins(rows,n,field);ece[f'{label}_{n}']=value;bins[f'{label}_{n}']=binrows
    counts=[];decisions=[]
    for theta in thresholds:
        t=Fraction(str(theta))
        for field,method in [('c_exact','fitted'),('fixed_exact','fixed_09')]:
            keep=[r for r in rows if Fraction(r[field])>=t];correct=sum(r['gold'] for r in keep)
            counts.append({'method':method,'threshold':theta,'accepted':len(keep),'correct':correct,
              'errors':len(keep)-correct,'precision':correct/len(keep) if keep else None,
              'proposal_coverage':len(keep)/len(rows),'reference_edge_recall':correct/reference_count if reference_count else None,
              'applications':len({r['system'] for r in keep})})
            for r in rows:
                decisions.append({**r,'method':method,'threshold':theta,'accepted':Fraction(r[field])>=t})
            info('CALIBRATION','THRESHOLD','Select positive-edge proposals by correctness probability.',
                 method=method,threshold=theta,accepted=len(keep),correct=correct,total_proposals=len(rows))
    return {'proposals':len(rows),'correct_proposals':sum(r['gold'] for r in rows),
        'reference_edges':reference_count,'brier':float(brier),'brier_exact':str(brier),
        'fixed_09_brier':float(fixed_brier),'fixed_09_brier_exact':str(fixed_brier),
        'ece':ece,'thresholds':counts,'target':'Correctness of positive-edge proposals, not support entailment; low c is not a negative edge.'},bins,decisions,rows


def run(data:Path,output:Path,config:dict):
    checkpoint('CALIBRATION','Fit edge-proposal correctness on other applications, then evaluate held-out proposals.')
    config=config['calibration'];dest=output/'calibration';summaries={}
    for mode in ('annotated','raw_normalized','raw_published_aliases'):
        source=output/f'replay/{mode}_graphs.json'
        if not source.is_file():raise FileNotFoundError('Run replay before calibration: '+str(source))
        population,reference_count,projects=proposal_population(read_json(source));folds=[];predictions=[]
        for project in projects:
            with context(study='calibration',mode=mode,test_project=project):
                training=[r for r in population if r['system']!=project]
                test=[r for r in population if r['system']==project]
                features=[{k:r[k] for k in ('system','source','target','stratum')} for r in test]
                fit,frozen=fit_predict(training,features)
                # Labels are attached only after the prediction function returns.
                labels={(r['source'],r['target']):r['gold'] for r in test}
                for r in frozen:r['gold']=labels[r['source'],r['target']]
                predictions.extend(frozen)
                folds.append({'test_application':project,'training_applications':[x for x in projects if x!=project],
                              'training_proposals':len(training),'test_proposals':len(test),'fits':fit})
                info('CALIBRATION','FOLD','Fit three fixed groups using other applications only.',
                     mode=mode,held_out=project,training=len(training),test=len(test),fits=fit)
        result,bins,decisions,predictions=evaluate(predictions,reference_count,config['thresholds'],Fraction(str(config['fixed_confidence'])))
        summaries[mode]=result;folder=dest/mode
        write_json(folder/'folds.json',folds);write_csv(folder/'proposals.csv',predictions)
        write_json(folder/'bins.json',bins);write_csv(folder/'thresholds.csv',result['thresholds'])
        write_csv(folder/'selection_decisions.csv',decisions);write_json(folder/'results.json',result)
        bin_rows=[{'method_and_bin_count':name,**row} for name,rs in bins.items() for row in rs]
        write_csv(folder/'bins.csv',bin_rows)
    write_json(dest/'summary.json',summaries)
    return summaries
