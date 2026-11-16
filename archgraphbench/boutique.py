"""Sections VII-A–C: source-only reconstruction and dual-reference Boutique evaluation.
Resolution rules are refactored from the supplied research implementation.
"""
from __future__ import annotations
from .execution_log import checkpoint, info, debug, context
import copy
import re
from pathlib import Path
from typing import Any
from .core import Assertion, Edge, graph_answer, query_weights, query_witness, set_metrics, selection_metrics, weighted_divergence
from .io import YamlSource, read_json, write_json, write_csv, sha256
MASK = "__WITHHELD__"

def key(e: dict[str,Any]) -> Edge:
    """Canonicalize a typed edge while preserving its relation semantics."""
    return (e['source'],e['relation'],e['target'])

def scoped_projection(docs:list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Stable relevant-field view for optional upstream verification, not parser input."""
    rows=[]
    for o in docs:
        row={'kind':o['kind'],'name':o['metadata']['name']}
        if o['kind']=='Deployment':
            spec=o['spec']['template']['spec']
            row.update(labels=o['spec']['template']['metadata'].get('labels',{}),
              serviceAccountName=spec.get('serviceAccountName'),
              containers=[{'name':c['name'],'ports':c.get('ports',[]),'env':c.get('env',[])}
                for c in spec.get('containers',[])])
        elif o['kind']=='Service': row['spec']=o['spec']
        rows.append(row)
    return sorted(rows,key=lambda x:(x['kind'],x['name']))

def extract(docs:list[dict[str,Any]], mode:str) -> dict[str,Any]:
    """Neither this function nor its helpers read the reference graph or query labels."""
    if mode not in ('M1','M2'): raise ValueError(mode)
    info("BOUTIQUE", "EXTRACT_START", "Reconstruct from YAML objects only; reference labels are not passed to extract().", mode=mode)
    deps={o['metadata']['name']:o for o in docs if o['kind']=='Deployment'}
    services={o['metadata']['name']:o for o in docs if o['kind']=='Service'}
    accounts={o['metadata']['name'] for o in docs if o['kind']=='ServiceAccount'}
    nodes={(n,'workload') for n in deps}|{('sa:'+n,'service_account') for n in accounts}
    edges:set[Edge]=set(); possible:set[Edge]=set(); proofs:dict[Edge,list[str]]={}; excluded=[]
    def add(e:Edge, loc:list[str]) -> None:
        # Keep unique typed relationships and retain every source field needed
        # to explain the join. This is a prediction, not a reference lookup.
        edges.add(e); proofs[e]=list(dict.fromkeys(proofs.get(e, []) + loc))
        debug("BOUTIQUE", "EDGE_ADDED", "Add a supported typed relationship and its source fields.",
              source=e[0], relation=e[1], target=e[2], locators=proofs[e])
    def targets(service_name:str,port:int|None) -> list[str]:
        if mode=='M1':
            resolved = [service_name] if service_name in deps else []
            debug("BOUTIQUE", "NAME_JOIN", "M1 uses exact resource names, not selector semantics.",
                  service=service_name, port=port, resolved=resolved)
            return resolved
        svc=services.get(service_name)
        if svc is None:return []
        selector=svc['spec'].get('selector',{})
        if not selector:return []
        ports=[p for p in svc['spec'].get('ports',[]) if port is None or p['port']==port]
        result=[]
        for name,dep in deps.items():
            template=dep['spec']['template']
            labels=template['metadata'].get('labels',{})
            labels_match = all(labels.get(k)==v for k,v in selector.items())
            debug("BOUTIQUE", "SELECTOR_JOIN", "M2 checks every selector key against pod-template labels.",
                  service=service_name, workload=name, selector=selector, labels=labels, matches=labels_match)
            if not labels_match:continue
            declared=[p for c in template['spec'].get('containers',[]) for p in c.get('ports',[])]
            for p in ports:
                target=p.get('targetPort',p['port'])
                # Preserve the experiment's declared-container-port check.
                # Numeric targetPort values do not universally require that
                # declaration in Kubernetes; this is the paper adapter's scope.
                port_match = any((d.get('containerPort')==target if isinstance(target,int) else d.get('name')==target)
                                 for d in declared)
                debug("BOUTIQUE", "PORT_JOIN", "Check the admitted Service/backend port mapping.",
                      service=service_name, workload=name, target_port=target, matches=port_match)
                if port_match:
                    result.append(name);break
        return sorted(result)
    for name,dep in sorted(deps.items()):
        spec=dep['spec']['template']['spec']
        sa=spec.get('serviceAccountName')
        if sa in accounts:
            add((name,'assigned_service_account','sa:'+sa),
                [f'Deployment/{name}/spec/template/spec/serviceAccountName',f'ServiceAccount/{sa}'])
        # Only main containers' explicit literal *_ADDR fields belong to this scope.
        for ci,c in enumerate(spec.get('containers',[])):
            for ei,env in enumerate(c.get('env',[])):
                if not env['name'].endswith('_ADDR'):continue
                loc=f'Deployment/{name}/spec/template/spec/containers/{ci}/env/{ei}/value'
                value=env.get('value')
                if value==MASK:
                    debug("BOUTIQUE", "WITHHELD_ENDPOINT", "Keep unresolved alternatives; do not manufacture an observed edge.",
                          workload=name, field=env['name'], alternative_count=len(deps)-1)
                    possible|={(name,'configured_dependency',target) for target in deps if target!=name}
                    continue
                match=re.fullmatch(r'([a-z0-9][a-z0-9-]*):(\d+)',str(value))
                if not match:
                    excluded.append({'source':name,'locator':loc,'value':value,'reason':'Unsupported/nonliteral endpoint'})
                    continue
                host,port=match.group(1),int(match.group(2))
                if host not in services and host not in deps:
                    info("BOUTIQUE", "OUTSIDE_SCOPE", "Retain an undeclared endpoint as unadjudicated, not as a false edge.",
                         workload=name, endpoint=host, field=env['name'])
                    excluded.append({'source':name,'locator':loc,'value':value,
                                     'reason':'No corresponding declared Service/workload; outside fixed deployed-resource scope'})
                    continue
                resolved=targets(host,port)
                if not resolved:
                    possible|={(name,'configured_dependency',target) for target in deps if target!=name}
                for target in resolved:
                    locs=[loc]
                    if mode=='M2':locs += [f'Service/{host}/spec/selector',f'Service/{host}/spec/ports',
                                         f'Deployment/{target}/spec/template/metadata/labels',
                                         f'Deployment/{target}/spec/template/spec/containers']
                    add((name,'configured_dependency',target),locs)
    for name,svc in sorted(services.items()):
        if svc['spec'].get('type')!='LoadBalancer':continue
        node='entry:'+name; nodes.add((node,'declared_loadbalancer_entry'))
        resolved=targets(name,None)
        if not resolved:
            info("BOUTIQUE", "ENTRY_UNRESOLVED", "No supported entry join; upper-graph alternatives remain possible.",
                 entry=node, mode=mode, possible_targets=len(deps))
            possible|={(node,'declared_entry',n) for n in deps}
        for target in resolved:
            add((node,'declared_entry',target),[f'Service/{name}/spec/type',f'Service/{name}/spec/selector',
                 f'Service/{name}/spec/ports',f'Deployment/{target}/spec/template/metadata/labels',
                 f'Deployment/{target}/spec/template/spec/containers'])
    info("BOUTIQUE", "EXTRACT_COMPLETE", "Return the reconstructed lower graph and unresolved upper-graph additions.",
         nodes=len(nodes), supported_edges=len(edges), additional_possible_edges=len(possible-edges), excluded=len(excluded))
    return {'nodes':nodes,'edges':edges,'possible':possible-edges,'proofs':proofs,'excluded':excluded}

def serial_graph(g:dict[str,Any]) -> dict[str,Any]:
    """Serialize the lower graph and additional possible edges with provenance."""
    return {'nodes':[{'id':n,'type':t} for n,t in sorted(g['nodes'])],
       'edges':[{'source':u,'relation':r,'target':v,'locators':g['proofs'][(u,r,v)]} for u,r,v in sorted(g['edges'])],
       'uncertainty_upper_edges':[{'source':u,'relation':r,'target':v} for u,r,v in sorted(g['possible'])],
       'excluded':g['excluded']}


def mask_input(objects: list[dict], config: dict) -> tuple[list[dict], dict]:
    # Perturb evidence in memory. Neither the original YAML nor the fixed
    # full-architecture reference is changed by an evidence-withholding test.
    """Withhold exactly one configured literal endpoint on an in-memory copy."""
    masked = copy.deepcopy(objects)
    changes = []
    for obj in masked:
        if obj['kind'] != config['kind'] or obj['metadata']['name'] != config['resource']:
            continue
        for ci, container in enumerate(obj['spec']['template']['spec']['containers']):
            for ei, env in enumerate(container.get('env', [])):
                if env['name'] == config['env_name']:
                    if 'value' not in env or env['value'] == config['replacement']:
                        raise ValueError('The configured mask requires one existing unmasked literal value')
                    changes.append({'resource': config['resource'], 'container': ci, 'environment_index': ei,
                                    'field': config['env_name'], 'before': env['value'], 'after': config['replacement']})
                    env['value'] = config['replacement']
    if len(changes) != config['required_change_count'] or len(changes) != 1:
        raise ValueError(f"Mask matched {len(changes)} fields; exactly one required")
    info("BOUTIQUE", "MASK_APPLIED", "Withhold exactly one endpoint on an in-memory copy; the fixed reference is unchanged.",
         resource=config['resource'], field=config['env_name'], changed_fields=len(changes), replacement=config['replacement'])
    return masked, {'changes': changes, 'change_count': len(changes), 'reference_unchanged': True}


def _validate_namespace(objects):
    """Reject namespaces outside the historical single/default-namespace scope."""
    namespaces = {o['metadata'].get('namespace', 'default') for o in objects}
    if namespaces != {'default'}:
        raise ValueError('Boutique historical adapter supports this single-default-namespace case only; use the manifest adapter for namespaced backend sets')


def run(data: Path, output: Path, config: dict, *, source_path: Path | None = None,
        reference_path: Path | None = None, allow_unreviewed_reference: bool = False) -> dict:
    """Execute the five Boutique cases and calculate their dual-reference scores.

    Inputs: retained YAML, frozen reference/questions and mask configuration.
    Outputs: predicted graphs, source witnesses, per-query answers and metrics.
    M1/M2 extraction reads YAML only. Reference answers are evaluated afterward.
    M2-CW reuses M2 resolution and changes only the treatment of unknown paths.
    """
    checkpoint("BOUTIQUE", "Load source evidence and the separately selected evaluation reference.")
    root = data / 'public_case' 
    selected_source = source_path or root / 'source/kubernetes-manifests.yaml'
    selected_reference = reference_path or root / 'reference.json'
    if source_path and not reference_path:
        raise ValueError('A custom source requires a matching reference')
    source = YamlSource(selected_source, selected_source.name if source_path else 'public_case/source/kubernetes-manifests.yaml')
    _validate_namespace(source.objects)
    reference = read_json(selected_reference)
    mask_config = config['boutique_mask']
    verification = None
    reference_mode = 'historical_retained'
    if reference_path:
        from .reference_builder import verify_reference
        verification = verify_reference(selected_source, selected_reference, allow_unreviewed=allow_unreviewed_reference)
        metadata = reference['reference_metadata']
        mask_config = metadata['mask']
        reference_mode = ('generated_unreviewed_candidate' if metadata['status']=='candidate_pending_review'
                          else 'generated_with_recorded_review')
    reference_hash = sha256(selected_reference)
    info("BOUTIQUE", "REFERENCE_SELECTED", "Use the reference only for evaluation, after YAML-only reconstruction.",
         mode=reference_mode, source=selected_source, source_sha256=source.digest,
         reference=selected_reference, reference_sha256=reference_hash, query_count=len(reference['queries']))
    queries = reference['queries']
    weights = query_weights(queries)
    reference_edges = {key(e) for e in reference['edges']}
    reference_nodes = {(n['id'], n['type']) for n in reference['nodes']}
    for q in queries:
        actual = 'T' if query_witness(reference_edges, q) is not None else 'F'
        if q['full'] != actual or q['masked'] not in ('T', 'F', 'U', 'C'):
            raise ValueError(f"Invalid frozen reference answer: {q['id']}")
    masked, mask_record = mask_input(source.objects, mask_config)
    results, answers, graphs, assertions = [], [], {}, []
    cases = [('full', 'M1'), ('full', 'M2'), ('masked', 'M1'), ('masked', 'M2'), ('masked', 'M2-CW')]
    for condition, method in cases:
        checkpoint("BOUTIQUE", "Reconstruct one evidence condition and evaluate its questions.", condition=condition, method=method)
        with context(study="boutique", condition=condition, method=method):
            graph = extract(source.objects if condition == 'full' else masked, 'M1' if method == 'M1' else 'M2')
        # Predictions now exist. The following loop is the evaluator, where
        # the fixed architecture and condition-specific support may be read.
        local_rows = []
        for q, w in zip(queries, weights):
            with context(condition=condition, method=method, query=q['id']):
                answer = graph_answer(graph['edges'], graph['possible'], q, complete=True, closed_world=method == 'M2-CW')
            support = q[condition]
            unsupported = answer['evidence'] in ('T', 'F') and answer['evidence'] != support
            if unsupported:
                answer['reason'] += f" Commitment is unsupported against the specified {support} support label."
            if answer['evidence'] == 'U':
                answer['reason'] += ' No absence of live network connectivity is established.'
            path = answer['witness']
            witness_sources = [{ 'edge': e, 'locators': [source.legacy_locator(x) for x in graph['proofs'][e]] }
                               for e in (path or [])]
            row = {'condition': condition, 'method': method, 'query': q['id'], 'kind': q['kind'],
                   'source': q['source'], 'target': q['target'], 'weight': w,
                   'architectural_reference': q['full'], 'support_reference': support,
                   'semantic_prediction': answer['semantic'], 'evidence_prediction': answer['evidence'],
                   'accepted': answer['evidence'] in ('T', 'F'), 'unsupported': unsupported,
                   'witness': path, 'witness_sources': witness_sources,
                   'possible_witness': answer['possible_witness'], 'bounded_negative': answer['bounded_negative'],
                   'explanation': answer['reason']}
            local_rows.append(row)
            info("BOUTIQUE", "QUERY", "Evaluate this query against the supported/possible graphs.",
                 condition=condition, method=method, query=q['id'],
                 architectural_reference=q['full'], support_reference=support,
                 semantic=answer['semantic'], evidence=answer['evidence'],
                 accepted=row['accepted'], unsupported=unsupported,
                 witness=path, possible_witness=answer['possible_witness'], explanation=answer['reason'])
        sem_gold, evid_gold = [q['full'] for q in queries], [q[condition] for q in queries]
        sem_pred, evid_pred = [r['semantic_prediction'] for r in local_rows], [r['evidence_prediction'] for r in local_rows]
        edge_score = set_metrics(reference_edges, graph['edges'])
        node_score = set_metrics(reference_nodes, graph['nodes'])
        select = selection_metrics(evid_gold, evid_pred)
        results.append({'condition': condition, 'method': method, 'nodes': len(graph['nodes']),
                        'edges': len(graph['edges']), 'node_f1': node_score['f1'], 'edge_f1': edge_score['f1'],
                        'edge_f1_exact': edge_score['f1_exact'], 'tp': edge_score['tp'], 'fp': edge_score['fp'], 'fn': edge_score['fn'],
                        'node_tp': node_score['tp'], 'node_fp': node_score['fp'], 'node_fn': node_score['fn'],
                        'Ds': weighted_divergence(sem_gold, sem_pred, weights),
                        'De': weighted_divergence(evid_gold, evid_pred, weights), 'accepted': select['accepted'],
                        'query_count': len(queries), 'coverage': select['coverage'], 'unsupported': select['unsupported'],
                        'UCR_q': select['ucr'], 'excluded_endpoints': len(graph['excluded']),
                        'processing': 'FRESH_DETERMINISTIC_EXTRACTION'})
        # Log the values already calculated above; logging never supplies a
        # result, changes a denominator, or chooses a reference answer.
        calculated = results[-1]
        info("BOUTIQUE", "SCORES", "Calculate structural fidelity, both divergences, coverage and UCR_q.",
             condition=condition, method=method, tp=edge_score['tp'], fp=edge_score['fp'], fn=edge_score['fn'],
             F1_exact=edge_score['f1_exact'], Ds=calculated['Ds'], De=calculated['De'],
             accepted=select['accepted'], population=len(queries), unsupported=select['unsupported'],
             coverage=select['coverage'], UCR_q=select['ucr'])
        serial = serial_graph(graph)
        for e in serial['edges']:
            e['source_witnesses'] = [source.legacy_locator(x) for x in e['locators']]
            claim = Assertion(e['source'], e['relation'], e['target'],
                              'identity' if e['relation'] == 'assigned_service_account' else 'flow',
                              e['source_witnesses'], 'observed' if e['relation'] == 'assigned_service_account' else 'inferred',
                              None, (None, None))
            assertions.append({'condition': condition, 'method': method, **claim.record(),
                               'note': 'Validity interval not reported by this manifest; not an assertion of timeless truth.'})
        serial['reference_file'] = 'reference_used.json'
        serial['reference_sha256'] = reference_hash
        serial['reference_mode'] = reference_mode
        serial['scope'] = reference.get('closure')
        graphs[f'{condition}/{method}'] = serial
        answers.extend(local_rows)
    if graphs['masked/M2']['edges'] != graphs['masked/M2-CW']['edges']:
        raise RuntimeError('Paired output policies unexpectedly changed the reconstructed graph')
    info("BOUTIQUE", "PAIRED_GRAPH_CHECK", "Masked M2 and M2-CW use identical supported edges; only their answer policy differs.",
         supported_edges=len(graphs['masked/M2']['edges']))
    checkpoint("BOUTIQUE", "Write predictions, witnesses and calculated metrics.")
    destination = output / 'boutique' 
    write_json(destination / 'reference_used.json', reference)
    write_json(destination / 'reference_provenance.json', {
        'file':str(selected_reference),'sha256':reference_hash,'mode':reference_mode,
        'source_file':str(selected_source),'source_sha256':source.digest,
        'mechanical_verification':verification,'independent_validation':False,
        'boundary':'Generated candidate agreement is not independent ground truth. The historical reference is separately specified, not independently human-validated.'})
    if sha256(selected_reference)!=reference_hash or sha256(selected_source)!=source.digest:
        raise RuntimeError('Source/reference changed during evaluation')
    write_json(destination / 'graphs.json', graphs)
    write_json(destination / 'assertions.json', assertions)
    write_json(destination / 'queries.json', answers)
    write_csv(destination / 'queries.csv', answers)
    write_json(destination / 'metrics.json', results)
    write_csv(destination / 'metrics.csv', results)
    write_json(destination / 'mask.json', mask_record)
    write_json(destination / 'masked_input.json', masked)
    write_json(destination / 'support_references.json', {condition: {q['id']: q[condition] for q in queries} for condition in ('full','masked')})
    write_json(destination / 'scoped_source_projection.json', scoped_projection(source.objects))
    write_csv(output / 'table_VII_boutique.csv', results)
    candidate = root / 'source/upstream-commit.yaml'
    comparison = {'fresh_upstream_fetch': False, 'independent_source_authentication': False}
    if candidate.is_file():
        candidate_source = YamlSource(candidate)
        comparison.update(byte_identical=source.digest == candidate_source.digest,
                          scoped_fields_identical=scoped_projection(source.objects) == scoped_projection(candidate_source.objects),
                          retained_sha256=source.digest, bundled_candidate_sha256=candidate_source.digest,
                          boundary='Compares two bundled local files. Original transcribed file is not claimed byte-identical to upstream.')
    write_json(destination / 'source_comparison.json', comparison)
    return {'cases': results, 'source_comparison': comparison, 'input': source.file_id,
            'reference_status': reference.get('reference_status'), 'reference_mode': reference_mode,
            'boundary': 'Scoped static declarations, not runtime reachability or full provenance entailment.'}
