"""Final paper Sections III-D, V and VI: constructive, exhaustive diagnostics.

Settings describe synthetic populations; no reported score is a runtime input.
This module uses Python's standard library and the shared scoring contract.
"""
from __future__ import annotations
from .execution_log import checkpoint, info, debug
from collections import Counter
from fractions import Fraction
from itertools import product
from pathlib import Path
from .core import (query_witness, set_metrics, selection_metrics, support_reference,
                   weighted_divergence, finite_number)
from .io import write_json, write_csv

POLICY_NAMES = {
    'evidence_preserving': 'Evidence preserving',
    'positive_precedence': 'Positive precedence',
    'closed_world': 'Closed world',
    'always_unknown': 'Always unknown',
}


def policy_answer(state: str, policy: str) -> str:
    """Apply one explicit diagnostic policy to a four-state support outcome."""
    if state not in ('T','F','U','C'):
        raise ValueError('Invalid support state')
    if policy == 'evidence_preserving': return state
    if policy == 'positive_precedence': return 'T' if state == 'C' else state
    if policy == 'closed_world': return {'C':'T', 'U':'F'}.get(state, state)
    if policy == 'always_unknown': return 'U'
    raise ValueError('Invalid policy: ' + policy)


def transition_examples() -> tuple[list, list]:
    """Table II: compute states from explicit structured records and time rules."""
    base = {'proposition':'payment_authenticates_with_idp', 'release':'example',
            'start':0, 'end':10, 'admissible':True}
    positive = dict(base, source='binding-positive', polarity='+')
    negative = dict(base, source='binding-negative', polarity='-')
    definitions = [
        ('Current positive binding', [positive], 1, set()),
        ('Only binding removed', [positive], 1, {'binding-positive'}),
        ('Current positive and negative', [positive, negative], 1, set()),
        ('Negative support only', [negative], 1, set()),
        ('Out-of-interval binding only', [positive], 10, set()),
    ]
    rows, evidence = [], []
    for description, records, target_time, removed in definitions:
        labels, audit = support_reference([base['proposition']], records,
                  target_time=target_time, release='example', removed_sources=removed)
        state = labels[base['proposition']]
        info("DIAGNOSTICS", "IDENTITY_TRANSITION", "Apply source removal and half-open time validity to the support records.",
             condition=description, target_time=target_time, removed_sources=sorted(removed), state=state)
        rows.append({'available_evidence':description, 'state':state})
        evidence.append({'case':description, 'records':records, 'target_time':target_time,
                         'removed_sources':sorted(removed), 'state':state, 'audit':audit,
                         'kind':'CONSTRUCTED_EXAMPLE', 'not_a_deployed_identity_observation':True})
    return rows, evidence


def arithmetic_cases(sizes: list[int]) -> tuple[list, list]:
    """Construct edge insertions/deletions and zone-only changes before scoring."""
    rows, graphs = [], []
    for operation in ('Delete one true edge', 'Insert one false edge', 'Change only a zone attribute'):
        zone_scores = []
        for m in sizes:
            if isinstance(m,bool) or not isinstance(m,int) or m < 2:
                raise ValueError('Arithmetic construction requires integer m >= 2')
            gold = {(str(j),'flow',str(j+1)) for j in range(m)}
            pred = set(gold)
            zones = {str(j):'A' for j in range(m+1)}
            pred_zones = dict(zones)
            if operation.startswith('Delete'): pred.remove(('0','flow','1'))
            elif operation.startswith('Insert'): pred.add(('0','flow',str(m)))
            else: pred_zones['0'] = 'B'
            score = set_metrics(gold, pred)
            debug("DIAGNOSTICS", "STRUCTURAL_ARITHMETIC", "Apply the operation to edge/zone data before calculating F1.",
                  operation=operation, reference_edges=m, tp=score['tp'], fp=score['fp'], fn=score['fn'], f1_exact=score['f1_exact'])
            row = {'operation':operation, 'm':m, 'exact_f1':score['f1_exact'], 'edge_f1':score['f1']}
            graphs.append({**row, 'reference_edges':sorted(gold), 'predicted_edges':sorted(pred),
                           'reference_zones':zones, 'predicted_zones':pred_zones, 'counts':score})
            if operation.startswith('Change'): zone_scores.append(row)
            else: rows.append(row)
        if zone_scores:
            if len({r['exact_f1'] for r in zone_scores}) != 1:
                raise RuntimeError('Zone-only changes unexpectedly altered structural score')
            rows.append({'operation':operation, 'm':' or '.join(map(str,sizes)),
                         'exact_f1':zone_scores[0]['exact_f1'], 'edge_f1':zone_scores[0]['edge_f1']})
    return rows, graphs


def run(output: Path, config: dict) -> dict:
    """Execute the paper-defined bridge, support-state and weight experiments.

    The support population is exhaustive (four states per proposition); rates
    are pooled over commitments, not averaged over undefined per-case UCRs.
    Confidence thresholds affect selection only. Fixed query errors are then
    reweighted to examine rank reversals using exact rational arithmetic.
    """
    checkpoint("DIAGNOSTICS", "Construct chain graphs and delete one bridge in each.")
    c = config['diagnostics']; dest = output/'diagnostics' 
    bridges, witnesses, graphs = [], [], []
    for m in c['chain_edge_counts']:
        if isinstance(m,bool) or not isinstance(m,int) or m < 8:
            raise ValueError('Four final targets must lie beyond the deleted bridge; require m>=8')
        gold = {(str(j),'flow',str(j+1)) for j in range(m)}
        deleted = (str(m//2),'flow',str(m//2+1)); pred = gold - {deleted}
        rows = []
        for target in range(m-3, m+1):
            q = {'id':f'chain-{m}-{target}', 'kind':'path', 'source':'0', 'target':str(target), 'relations':['flow']}
            a,b = query_witness(gold,q), query_witness(pred,q)
            rows.append({'m':m, 'query':q, 'reference':'T' if a else 'F', 'prediction':'T' if b else 'F',
                         'reference_witness':a, 'prediction_witness':b})
        score = set_metrics(gold,pred)
        bridges.append({'edges':m, 'deleted_edge':deleted, 'edge_f1':score['f1'], 'f1_exact':score['f1_exact'],
                        'Ds':weighted_divergence([r['reference'] for r in rows],[r['prediction'] for r in rows],[1]*len(rows)),
                        'changed_queries':sum(r['reference']!=r['prediction'] for r in rows),'query_count':len(rows)})
        info("DIAGNOSTICS", "BRIDGE_RESULT", "Compare the edge sets and search all selected target paths again.",
             edges=m, deleted_edge=deleted, F1_exact=score['f1_exact'],
             changed_queries=bridges[-1]['changed_queries'], Ds=bridges[-1]['Ds'])
        witnesses.extend(rows); graphs.append({'m':m, 'reference':sorted(gold), 'prediction':sorted(pred)})
    slots,states,policies = c['proposition_slots'],c['support_states'],c['policies']
    if len(slots)!=4 or len(set(slots))!=4 or len(states)!=4 or set(states)!={'T','F','U','C'}:
        raise ValueError('This diagnostic defines four unique slots and T/F/U/C states')
    if len(set(policies))!=len(policies) or set(policies)!=set(POLICY_NAMES):
        raise ValueError('Final-paper diagnostic requires exactly its four declared policies')
    confidence = finite_number(c['singleton_confidence'])
    if not 0 <= confidence <= 1: raise ValueError('Confidence outside [0,1]')
    thresholds = c['thresholds']; schemes = c['weight_schemes']
    for theta in thresholds:
        if not 0 <= finite_number(theta) <= 1: raise ValueError('Threshold outside [0,1]')
    for weights in schemes.values():
        weighted_divergence(['T']*len(slots), ['T']*len(slots), weights)
    # Exhaustive enumeration, not a sample of deployments. Each reference
    # state is obtained from constructed positive/negative support records.
    configurations=list(product(states,repeat=len(slots)))
    checkpoint("DIAGNOSTICS", "Enumerate support states and apply four policies at each threshold.",
               configurations=len(configurations), policies=policies, thresholds=thresholds)
    sources, raw, decisions, pooled = [], [], [], []
    for index, state_vector in enumerate(configurations):
        records = []
        for slot,state in zip(slots,state_vector):
            polarities = ('+',) if state=='T' else ('-',) if state=='F' else ('+','-') if state=='C' else ()
            for polarity in polarities:
                records.append({'proposition':slot,'source':f'synthetic-{index}-{slot}-{polarity}',
                                'polarity':polarity,'release':'diagnostic','start':0,'end':1,'admissible':True})
        labels,audit = support_reference(slots,records,target_time=0,release='diagnostic')
        gold = [labels[s] for s in slots]
        sources.append({'configuration':index,'support_records':records,'reference_states':labels,'audit':audit})
        debug("DIAGNOSTICS", "SUPPORT_CONFIGURATION", "Derive reference states from admissible synthetic support.",
              configuration=index, support_records=len(records), labels=labels)
        for policy in policies:
            prediction = [policy_answer(s,policy) for s in gold]
            divs = {name:weighted_divergence(gold,prediction,weights) for name,weights in schemes.items()}
            for theta in thresholds:
                selection = selection_metrics(gold,prediction,[confidence]*len(slots),theta)
                raw.append({'configuration':index,'policy':policy,'threshold':theta,'confidence':confidence,
                            'reference':gold,'prediction':prediction,'De':divs,
                            'accepted':selection['accepted'],'unsupported':selection['unsupported'],
                            'coverage':selection['coverage'],'UCR':selection['ucr']})
                debug("DIAGNOSTICS", "POLICY_DECISION", "Transform states, then select definite commitments without changing D_e.",
                      configuration=index, policy=policy, threshold=theta,
                      reference=gold, prediction=prediction, accepted=selection['accepted'],
                      unsupported=selection['unsupported'], De=divs)
                accepted=set(selection['accepted_indices'])
                for j,slot in enumerate(slots):
                    decisions.append({'configuration':index,'policy':policy,'threshold':theta,'proposition':slot,
                                      'reference':gold[j],'prediction':prediction[j],
                                      'confidence':confidence if prediction[j] in ('T','F') else None,
                                      'accepted':j in accepted,'unsupported':j in accepted and prediction[j]!=gold[j]})
    for theta in thresholds:
        for scheme in schemes:
            for policy in policies:
                rows=[r for r in raw if r['threshold']==theta and r['policy']==policy]
                denominator=len(rows)*len(slots); accepted=sum(r['accepted'] for r in rows)
                unsupported=sum(r['unsupported'] for r in rows)
                mean=sum((Fraction(str(r['De'][scheme])) for r in rows),Fraction())/len(rows)
                # Exact integer weighting for the pooled mean avoids rounding every condition.
                total_weight=sum(Fraction(str(w)) for w in schemes[scheme])
                exact=sum((sum((Fraction(str(w)) for a,b,w in zip(r['reference'],r['prediction'],schemes[scheme]) if a!=b),Fraction())/total_weight for r in rows),Fraction())/len(rows)
                pooled.append({'policy':POLICY_NAMES[policy],'policy_id':policy,'threshold':theta,'weight_scheme':scheme,
                               'De':float(exact),'De_exact':str(exact),'accepted':accepted,'population':denominator,
                               'coverage':accepted/denominator,'unsupported':unsupported,
                               'UCR':unsupported/accepted if accepted else None,
                               'UCR_exact':str(Fraction(unsupported,accepted)) if accepted else None})
    for summary_row in pooled:
        info("DIAGNOSTICS", "SUPPORT_SUMMARY", "Pool accepted commitments; N/A UCR is preserved when none are accepted.",
             **summary_row)
    checkpoint("DIAGNOSTICS", "Evaluate fixed error profiles under every configured query-weight vector.")
    weights_out,coordinates,ranks=[],Counter(),Counter()
    vals=c['weight_values']; ia=c['profile_A_errors'];ib=c['profile_B_errors']
    if any(finite_number(v)<=0 for v in vals): raise ValueError('Positive query weights required')
    if any(j not in range(1,5) for j in ia+ib): raise ValueError('Error-profile index out of range')
    for w in product(vals,repeat=4):
        denom=sum(map(Fraction,w));a=sum((Fraction(w[j-1]) for j in ia),Fraction())/denom
        b=sum((Fraction(w[j-1]) for j in ib),Fraction())/denom
        rank='A' if a<b else 'B' if b<a else 'Tie'
        ranks[rank]+=1;coordinates[a,b]+=1
        debug("DIAGNOSTICS", "WEIGHT_SETTING", "Calculate two weighted disagreements with exact fractions.",
              weights=w, D_A_exact=str(a), D_B_exact=str(b), preferred=rank)
        weights_out.append({'weights':w,'D_A':float(a),'D_B':float(b),'D_A_exact':str(a),'D_B_exact':str(b),'preferred':rank})
    info("DIAGNOSTICS", "WEIGHT_SUMMARY", "Aggregate ranking outcomes and coincident plotting coordinates.",
         settings=len(weights_out), ranks=dict(ranks), distinct_coordinates=len(coordinates))
    checkpoint("DIAGNOSTICS", "Calculate identity-state transitions and structural edge arithmetic.")
    transitions,transition_evidence = transition_examples()
    arithmetic,arithmetic_graphs = arithmetic_cases(c['arithmetic_edge_counts'])
    points=[{'D_A':float(a),'D_B':float(b),'D_A_exact':str(a),'D_B_exact':str(b),'multiplicity':n}
            for (a,b),n in sorted(coordinates.items())]
    checkpoint("DIAGNOSTICS", "Save constructed inputs, intermediate decisions and calculated summaries.")
    write_json(dest/'bridge_graphs.json',graphs);write_json(dest/'bridge_query_witnesses.json',witnesses)
    write_csv(dest/'bridge_results.csv',bridges);write_json(dest/'generated_support_records.json',sources)
    write_json(dest/'support_raw.json',raw);write_csv(dest/'support_raw.csv',raw)
    write_csv(dest/'support_decisions.csv',decisions);write_csv(dest/'support_summary.csv',pooled)
    write_csv(dest/'weight_settings.csv',weights_out);write_csv(dest/'weight_points.csv',points)
    write_json(dest/'arithmetic_graphs.json',arithmetic_graphs)
    write_json(dest/'identity_transition_evidence.json',transition_evidence)
    write_csv(output/'table_II_support_transitions.csv',transitions)
    write_csv(output/'table_V_structural_arithmetic.csv',arithmetic)
    table6=[{k:r[k] for k in ('policy','De','accepted','coverage','UCR')} for r in pooled
            if r['threshold']==0.8 and r['weight_scheme']=='equal']
    if not table6: raise ValueError('Table VI requires the 0.8 threshold and equal weights')
    write_csv(output/'table_VI_support_controls.csv',table6)
    result={'bridge':bridges,'support_configurations':len(configurations),'policy_count':len(policies),
            'thresholds':thresholds,'support_summary':pooled,
            'configuration_policy_outputs_per_threshold':len(configurations)*len(policies),
            'proposition_policy_evaluations_per_threshold':len(configurations)*len(policies)*len(slots),
            'weight_settings':len(weights_out),'weight_ranks':dict(ranks),'distinct_plot_coordinates':len(points),
            'boundary':'Constructed populations; assigned confidence, not calibrated probabilities or sampled deployments.'}
    write_json(dest/'summary.json',result)
    return result
