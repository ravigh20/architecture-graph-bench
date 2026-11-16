"""Build a reviewable reference candidate from YAML, not participant output.

This is a new preparation utility, not a historical source of the paper's labels.
It uses a separately written declarative join implementation. Shared Kubernetes
scope rules and YAML parsing with the evaluated methods prevent any claim that
automatic generation alone is independent scientific ground truth.
"""
from __future__ import annotations
from .execution_log import checkpoint, info, debug, context

from collections import deque
import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .io import YamlSource, read_json, sha256, write_csv, write_json

BUILDER_VERSION = '1.1.0'
SCOPE_ID = 'boutique-declared-v1'
FLOW = {'configured_dependency', 'declared_entry'}
RELATIONS = FLOW | {'assigned_service_account'}
CLOSURE = ('Finite declared-resource projection: Deployment workloads, declared '
           'ServiceAccounts, LoadBalancer entry nodes, and literal main-container '
           '*_ADDR endpoints joined through Service selectors and declared ports. '
           'F means a nonedge/nonpath only in this projection, not runtime isolation. '
           'An explicit __WITHHELD__ marker creates possible edges.')
BOUNDARY = ('Automatically generated candidate; not independently validated. '
            'A separate implementation does not eliminate shared-rule bias with M2. '
            'Source hashes detect byte changes; they do not authenticate origins, '
            'reviewer identity, or the correctness of the reference.')
REVIEW_FIELDS = ['record_id', 'record_type', 'item', 'source_locations',
                 'candidate_sha256', 'decision', 'reviewer', 'notes']


def stamp() -> str:
    """Record an execution timestamp; timestamps do not validate an annotation."""
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    """Produce stable JSON for comparing protected review records."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def edge_key(edge: dict) -> tuple[str, str, str]:
    """Represent a typed candidate relationship as an immutable triple."""
    return edge['source'], edge['relation'], edge['target']


def _plain(value: Any, description: str) -> str:
    """Require a nonempty identifier or field name."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{description} must be a nonempty string')
    return value


def validate_profile(profile: dict) -> None:
    """Accept only scope, mask and question definitions; reject expected answers."""
    if profile.get('schema_version') != 1 or profile.get('scope') != SCOPE_ID:
        raise ValueError(f'Profile must have schema_version=1 and scope={SCOPE_ID!r}')
    forbidden = {'edges', 'nodes', 'results', 'scores', 'expected', 'reference'}
    if forbidden & profile.keys():
        raise ValueError('A profile may not contain a reference graph or expected results')
    queries = profile.get('queries')
    if not isinstance(queries, list) or not queries:
        raise ValueError('Profile requires a nonempty list of query definitions')
    seen = set()
    allowed = {'id', 'kind', 'source', 'target', 'family', 'scope', 'weight'}
    for q in queries:
        if not isinstance(q, dict) or set(q) - allowed:
            raise ValueError('Queries accept definitions only, not expected/full/masked labels')
        for key in ('id', 'kind', 'source', 'target'):
            _plain(q.get(key), 'Query '+key)
        if q['id'] in seen:
            raise ValueError(f'Duplicate query ID: {q["id"]}')
        seen.add(q['id'])
        if q['kind'] not in {'path', 'identity', 'direct_entry'}:
            raise ValueError('Reference builder supports path, identity and direct_entry queries')
        w = q.get('weight', 1)
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0:
            raise ValueError('Query weights must be positive finite numbers')
    mask = profile.get('mask', {})
    needed = {'kind', 'resource', 'env_name', 'replacement', 'required_change_count'}
    if set(mask) != needed or mask.get('kind') != 'Deployment':
        raise ValueError('Profile requires the explicit single-Deployment environment-value mask')
    if mask['replacement'] != '__WITHHELD__' or mask['required_change_count'] != 1:
        raise ValueError('Use __WITHHELD__ and required_change_count=1 for this experiment')
    _plain(mask['resource'], 'Mask resource'); _plain(mask['env_name'], 'Mask env_name')
    if not mask['env_name'].endswith('_ADDR'):
        raise ValueError('The mask must target an in-scope *_ADDR variable')


def apply_mask(objects: list[dict], mask: dict) -> tuple[list[dict], list[dict]]:
    """Separate reference-side perturbation; never edits the original source file."""
    result = copy.deepcopy(objects)
    changes = []
    for obj in result:
        if obj['kind'] != mask['kind'] or obj['metadata']['name'] != mask['resource']:
            continue
        for ci, container in enumerate(obj['spec']['template']['spec'].get('containers', [])):
            for ei, env in enumerate(container.get('env', [])):
                if env['name'] != mask['env_name']:
                    continue
                value = env.get('value')
                if not isinstance(value, str) or value == mask['replacement']:
                    raise ValueError('Mask requires an existing, unmasked literal string value')
                changes.append({'kind': obj['kind'], 'resource': obj['metadata']['name'],
                                'field': f'spec/template/spec/containers/{ci}/env/{ei}/value',
                                'environment_name': env['name'], 'before': value,
                                'after': mask['replacement']})
                env['value'] = mask['replacement']
    if len(changes) != 1:
        raise ValueError(f'Mask matched {len(changes)} fields, expected exactly one')
    return result, changes


def declared_projection(source: YamlSource, objects: list[dict]) -> dict:
    """Enumerate declared facts and join source records. Does not call M1/M2."""
    deployments, services, accounts = {}, {}, {}
    for obj in objects:
        name, kind = obj['metadata']['name'], obj['kind']
        _plain(name, 'Resource name')
        if obj['metadata'].get('namespace', 'default') != 'default':
            raise ValueError('Reference builder supports the single default namespace only')
        if kind == 'Deployment': deployments[name] = obj
        elif kind == 'Service': services[name] = obj
        elif kind == 'ServiceAccount': accounts[name] = obj
        else:
            raise ValueError(f'Unsupported kind {kind!r}; this builder is not a general Kubernetes analyzer')
    if not deployments:
        raise ValueError('No Deployment workloads found in the source')
    nodes, edges, possible, excluded, unresolved = {}, {}, set(), [], []

    def loc(kind, name, field=''):
        return source.locate(kind, name, field)

    def add_node(ident, typ, support):
        nodes[ident] = {'id': ident, 'type': typ, 'support': support}
        debug("REFERENCE", "NODE", "Create an in-scope candidate node from a source declaration.",
              node=ident, node_type=typ, source_locations=support)

    def add_edge(u, relation, v, support, interpretation):
        key = (u, relation, v)
        if key not in edges:
            edges[key] = {'source': u, 'relation': relation, 'target': v,
                          'support': [], 'interpretation': interpretation}
        debug("REFERENCE", "EDGE", "Join source fields to propose a reference relationship, not a validated fact.",
              source=u, relation=relation, target=v, interpretation=interpretation, source_locations=support)
        known = {canonical(x) for x in edges[key]['support']}
        for item in support:
            if canonical(item) not in known:
                edges[key]['support'].append(item); known.add(canonical(item))

    for name in sorted(deployments):
        add_node(name, 'workload', [loc('Deployment', name, 'metadata/name')])
    for name in sorted(accounts):
        add_node('sa:'+name, 'service_account', [loc('ServiceAccount', name, 'metadata/name')])

    # Compute a Service/port -> workload witness relation before reading consumers.
    service_backends = {}
    for svc_name, svc in sorted(services.items()):
        spec = svc.get('spec', {})
        selector = spec.get('selector', {})
        if selector and not isinstance(selector, dict):
            raise ValueError(f'Invalid selector in Service {svc_name}')
        pairs = []
        for port_i, port in enumerate(spec.get('ports', [])):
            number = port.get('port')
            if isinstance(number, bool) or not isinstance(number, int):
                raise ValueError(f'Invalid Service port in {svc_name}')
            target = port.get('targetPort', number)
            for dep_name, dep in sorted(deployments.items()):
                template = dep['spec']['template']
                labels = template.get('metadata', {}).get('labels', {})
                if not selector or any(labels.get(k) != v for k, v in selector.items()):
                    continue
                for ci, container in enumerate(template['spec'].get('containers', [])):
                    for pi, cp in enumerate(container.get('ports', [])):
                        matches = (cp.get('containerPort') == target if isinstance(target, int)
                                   else cp.get('name') == target)
                        if matches:
                            witnesses = [loc('Service', svc_name, 'spec/selector'),
                                         loc('Service', svc_name, f'spec/ports/{port_i}'),
                                         loc('Deployment', dep_name, 'spec/template/metadata/labels'),
                                         loc('Deployment', dep_name,
                                             f'spec/template/spec/containers/{ci}/ports/{pi}')]
                            pairs.append((number, dep_name, witnesses))
        service_backends[svc_name] = pairs
        debug("REFERENCE", "SERVICE_JOIN", "Resolve candidate backends by selector and admitted declared ports.",
              service=svc_name, backends=[{'port':p,'workload':w} for p,w,_ in pairs])

    for name, dep in sorted(deployments.items()):
        spec = dep['spec']['template']['spec']
        account = spec.get('serviceAccountName')
        if account in accounts:
            add_edge(name, 'assigned_service_account', 'sa:'+account,
                     [loc('Deployment', name, 'spec/template/spec/serviceAccountName'),
                      loc('ServiceAccount', account, 'metadata/name')],
                     'Explicit assignment to a declared ServiceAccount; not an authorization outcome.')
        elif account:
            excluded.append({'source': name, 'field': 'serviceAccountName', 'value': account,
                             'reason': 'Assignment points to an undeclared account; outside declared-resource scope.',
                             'support': [loc('Deployment', name, 'spec/template/spec/serviceAccountName')]})
        for ci, container in enumerate(spec.get('containers', [])):
            env_names = set()
            for ei, env in enumerate(container.get('env', [])):
                env_name = _plain(env.get('name'), 'Environment name')
                if env_name in env_names:
                    raise ValueError(f'Duplicate environment name {env_name} in {name}')
                env_names.add(env_name)
                if not env_name.endswith('_ADDR'):
                    continue
                env_field = f'spec/template/spec/containers/{ci}/env/{ei}'
                origin = loc('Deployment', name, env_field)
                value = env.get('value')
                if value == '__WITHHELD__':
                    possible.update((name, 'configured_dependency', target)
                                    for target in deployments if target != name)
                    unresolved.append({'source': name, 'field': env_name,
                                       'reason': 'Explicitly withheld endpoint', 'support': [origin]})
                    continue
                match = re.fullmatch(r'([a-z0-9][a-z0-9-]*):(\d+)', value) if isinstance(value, str) else None
                if not match:
                    excluded.append({'source': name, 'field': env_name, 'value': value,
                                     'reason': 'Not an admitted literal host:port endpoint.', 'support': [origin]})
                    continue
                host, number = match.group(1), int(match.group(2))
                if host not in services and host not in deployments:
                    excluded.append({'source': name, 'field': env_name, 'value': value,
                                     'reason': 'No declared Service/workload for endpoint; outside declared-resource scope.',
                                     'support': [origin]})
                    continue
                matches = [pair for pair in service_backends.get(host, []) if pair[0] == number]
                if not matches:
                    possible.update((name, 'configured_dependency', target)
                                    for target in deployments if target != name)
                    unresolved.append({'source': name, 'field': env_name,
                                       'reason': 'Endpoint cannot be resolved under selector/declared-port rules.',
                                       'support': [origin]})
                for _, target, support in matches:
                    add_edge(name, 'configured_dependency', target, [origin, *support],
                             'Literal configured endpoint joined to Service selector and declared port; not observed traffic.')

    for name, svc in sorted(services.items()):
        if svc.get('spec', {}).get('type') != 'LoadBalancer':
            continue
        entry = 'entry:'+name
        origin = loc('Service', name, 'spec/type')
        add_node(entry, 'declared_loadbalancer_entry', [loc('Service', name, 'metadata/name'), origin])
        matches = service_backends[name]
        if not matches:
            possible.update((entry, 'declared_entry', target) for target in deployments)
            unresolved.append({'source': entry, 'reason': 'Unresolved LoadBalancer selector/declared-port join.',
                               'support': [origin]})
        for _, target, support in matches:
            add_edge(entry, 'declared_entry', target, [origin, *support],
                     'Declared LoadBalancer Service selects the workload and matches declared ports; not proven external reachability.')

    return {'nodes': [nodes[k] for k in sorted(nodes)],
            'edges': [edges[k] for k in sorted(edges)],
            'possible': sorted(possible-set(edges)), 'excluded': excluded, 'unresolved': unresolved}


def witness(edges: set[tuple[str, str, str]], q: dict) -> list | None:
    """Reference-side typed reachability; no predicted answers or scoring targets."""
    if q['kind'] in ('identity', 'direct_entry'):
        rel = 'assigned_service_account' if q['kind'] == 'identity' else 'declared_entry'
        e = (q['source'], rel, q['target'])
        return [list(e)] if e in edges else None
    adjacency = {}
    for u, r, v in sorted(edges):
        if r in FLOW:
            adjacency.setdefault(u, []).append((u, r, v))
    queue, visited = deque([(q['source'], [])]), {q['source']}
    while queue:
        current, path = queue.popleft()
        for e in adjacency.get(current, []):
            new_path = path + [list(e)]
            if e[2] == q['target']:
                return new_path
            if e[2] not in visited:
                visited.add(e[2]); queue.append((e[2], new_path))
    return None


def answer(graph: dict, q: dict) -> dict:
    """Compute a candidate support answer from lower/upper declared projections."""
    edges = {edge_key(e) for e in graph['edges']}
    by_edge = {edge_key(e): e for e in graph['edges']}
    positive = witness(edges, q)
    upper = witness(edges | {tuple(e) for e in graph['possible']}, q)
    state = 'T' if positive is not None else 'U' if upper is not None else 'F'
    return {'state': state, 'witness': positive, 'possible_witness': upper if state == 'U' else None,
            'source_witnesses': [{'edge': e, 'support': by_edge[tuple(e)]['support']}
                                 for e in positive or []],
            'bounded_negative': state == 'F',
            'explanation': {'T': 'A typed path/edge is supported by the admitted YAML fields.',
                            'U': 'The relationship remains possible, but a supported witness is missing.',
                            'F': 'No admitted witness exists in either graph under the declared finite-scope assumption; not runtime isolation.'}[state]}


def build_candidate(source_path: Path, profile_path: Path) -> tuple[dict, dict]:
    """Build candidate graph and full/masked answers directly from source records.

    The answer-free profile selects scope and questions. No existing reference,
    participant output or expected metric is read. Shared interpretation rules
    with M2 still require independent review of the resulting candidate.
    """
    checkpoint("REFERENCE", "Read source YAML and answer-free scope/query definitions.")
    profile = read_json(profile_path)
    validate_profile(profile)
    source = YamlSource(source_path, source_path.name)
    info("REFERENCE", "INPUTS", "The builder does not read M1/M2 predictions or historical answer labels.",
         source=source_path, source_sha256=source.digest, profile=profile_path,
         query_count=len(profile['queries']), scope=profile['scope'])
    checkpoint("REFERENCE", "Build a full candidate graph using the declared interpretation rules.")
    with context(condition="full", role="reference_candidate"):
        full = declared_projection(source, source.objects)
    if full['unresolved']:
        raise ValueError('Cannot freeze a complete architectural candidate from unresolved full input: '+
                         canonical(full['unresolved'])+'. Correct the source or explicitly redesign the scope/profile.')
    node_ids = {n['id'] for n in full['nodes']}
    for q in profile['queries']:
        if not {q['source'], q['target']} <= node_ids:
            raise ValueError(f'Query {q["id"]} references absent nodes; use a profile for this application')
    checkpoint("REFERENCE", "Withhold the configured field in memory and derive the support reference.")
    masked_objects, changes = apply_mask(source.objects, profile['mask'])
    info("REFERENCE", "MASK", "Only the support evidence changes; preserve the full architectural candidate.",
         resource=profile['mask']['resource'], field=profile['mask']['env_name'], changes=len(changes))
    with context(condition="masked", role="reference_candidate"):
        masked = declared_projection(source, masked_objects)
    checkpoint("REFERENCE", "Calculate full and masked answers to the predefined questions.")
    labels, query_records = [], []
    for q0 in profile['queries']:
        q = copy.deepcopy(q0)
        q.setdefault('weight', 1)
        for condition, graph in [('full', full), ('masked', masked)]:
            result = answer(graph, q)
            q[condition] = result['state']
            info("REFERENCE", "QUERY", "Derive the reference answer from candidate supported/possible relationships.",
                 condition=condition, query=q['id'], state=result['state'], witness=result['witness'],
                 possible_witness=result['possible_witness'], explanation=result['explanation'])
            query_records.append({'condition': condition, 'query': q['id'], 'kind': q['kind'],
                                  'source': q['source'], 'target': q['target'], **result})
        labels.append(q)
    meta = {'builder': 'archgraphbench.reference_builder', 'builder_version': BUILDER_VERSION,
            'scope_id': SCOPE_ID, 'status': 'candidate_pending_review',
            'independent_validation': False, 'source_file': source_path.name,
            'source_sha256': source.digest, 'profile_sha256': sha256(profile_path),
            'profile_id': profile['profile_id'], 'profile_snapshot': profile,
            'source_attribution': profile.get('source_attribution', {}),
            'mask': profile['mask'], 'boundary': BOUNDARY,
            'builder_code_sha256': sha256(Path(__file__))}
    reference = {'schema_version': 1, 'reference_metadata': meta,
                 'reference_status': 'Automatically generated candidate; human review pending; not independent ground truth.',
                 'nodes': full['nodes'], 'edges': full['edges'], 'queries': labels,
                 'excluded': full['excluded'], 'closure': CLOSURE}
    artifacts = {'full_graph': full, 'masked_graph': masked, 'query_evidence': query_records,
                 'mask': {'changes': changes, 'change_count': len(changes), 'reference_unchanged': True},
                 'source_manifest': {'input_path': str(source_path.resolve()), 'source_sha256': source.digest,
                                     'profile_path': str(profile_path.resolve()), 'profile_sha256': sha256(profile_path),
                                     'independent_source_authentication': False}}
    if sha256(source_path) != source.digest:
        raise RuntimeError('Source changed during candidate generation')
    info("REFERENCE", "CANDIDATE", "Candidate generation completed; independent source review is still required.",
         nodes=len(reference['nodes']), edges=len(reference['edges']), queries=len(labels),
         excluded=len(reference['excluded']), status=meta['status'])
    return reference, artifacts


def review_rows(reference: dict, digest: str) -> list[dict]:
    """Create a PENDING checklist bound to the candidate digest."""
    items = [('scope', 'scope', reference['closure'], [])]
    items.extend(('node:'+n['id'], 'node', canonical({'id':n['id'], 'type':n['type']}), n.get('support', []))
                 for n in reference['nodes'])
    items.extend(('edge:'+canonical(edge_key(e)), 'edge', canonical(edge_key(e)), e['support'])
                 for e in reference['edges'])
    for q in reference['queries']:
        for condition in ('full', 'masked'):
            items.append((f'query:{condition}:{q["id"]}', 'query',
                          canonical({k:q[k] for k in ('id','kind','source','target',condition)}), []))
    for i, excluded in enumerate(reference.get('excluded', [])):
        items.append((f'excluded:{i}', 'exclusion', canonical({k:v for k,v in excluded.items() if k!='support'}),
                      excluded.get('support', [])))
    return [{'record_id':ident,'record_type':typ,'item':item,'source_locations':canonical(locations),
             'candidate_sha256':digest,'decision':'PENDING','reviewer':'','notes':''}
            for ident, typ, item, locations in items]


def safe_destination(destination: Path, inputs: list[Path]) -> None:
    """Reject overwrites and outputs placed inside frozen input directories."""
    dest = destination.resolve()
    for p in inputs:
        p = p.resolve()
        if p == dest or p.is_relative_to(dest):
            raise ValueError('Output must not contain or overwrite an input file')
        for ancestor in p.parents:
            if (ancestor/'input_manifest.json').is_file() and (dest==ancestor or dest.is_relative_to(ancestor)):
                raise ValueError('Keep generated references outside the frozen input data directory')
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError('Output directory is not empty; choose a fresh --out directory')
    dest.mkdir(parents=True, exist_ok=True)


def write_candidate(source: Path, profile: Path, output: Path) -> dict:
    # Calculate before creating output; never overwrite the frozen benchmark reference.
    """Persist a candidate reference, source witnesses and review requirements."""
    ref, products = build_candidate(source, profile)
    safe_destination(output, [source, profile])
    checkpoint("REFERENCE", "Write the candidate, evidence records and a pending review checklist.", output=output)
    path = output/'reference.json' 
    write_json(path, ref)
    digest = sha256(path)
    for name, data in products.items():
        write_json(output/f'{name}.json', data)
    write_csv(output/'review.csv', review_rows(ref, digest), REVIEW_FIELDS)
    (output/'reference.sha256').write_text(digest+'  reference.json\n', encoding='utf-8')
    (output/'REVIEW_INSTRUCTIONS.md').write_text(
        '# Candidate reference: review required\n\n'+BOUNDARY+'\n\n'
        'Inspect the original YAML, each node/edge source locator, query_evidence.json, '
        'the finite-scope completeness assumption, exclusions, and mask.json.\n\n'
        'Only edit decision, reviewer and notes in review.csv. Use APPROVE after actually '
        'checking a record; use REJECT or leave PENDING otherwise. Do not edit record IDs, '
        'items, source locations, or candidate hashes. Every row, including scope and query '
        'negatives, needs review. Negative answers require inspecting the complete scoped input.\n\n'
        'The finalize command records the supplied review; it cannot verify reviewer identity '
        'or independence. Do not open participant predictions before conducting a blinded review. '
        'Source consistency is not a substitute for independent review.\n\n'
        'Corrections require a new candidate, rechecking affected claims and a new review. '
        'The default paper workflow continues to use its unchanged historical reference.\n', encoding='utf-8')
    result = {'producer':'archgraphbench.reference_builder','status':'BUILT_CANDIDATE','created':stamp(),
              'nodes':len(ref['nodes']), 'edges':len(ref['edges']), 'queries':len(ref['queries']),
              'excluded':len(ref['excluded']), 'reference_sha256':digest,
              'source_sha256':ref['reference_metadata']['source_sha256'],
              'review_status':'PENDING', 'boundary':BOUNDARY}
    write_json(output/'build.json', result)
    return result


def verify_reference(source_path: Path, reference_path: Path, *, allow_unreviewed: bool = False) -> dict:
    """Mechanical consistency and source binding, never an independent truth check."""
    checkpoint("REFERENCE", "Verify candidate/source binding and rule consistency, not independent correctness.",
               source=source_path, reference=reference_path)
    ref = read_json(reference_path)
    meta = ref.get('reference_metadata', {})
    if meta.get('builder') != 'archgraphbench.reference_builder':
        raise ValueError('Explicit overrides require a reference from this builder with source binding')
    profile = meta.get('profile_snapshot', {})
    validate_profile(profile)
    status = meta.get('status')
    if status == 'candidate_pending_review' and not allow_unreviewed:
        raise ValueError('Reference is an unreviewed candidate. Review/finalize it, or explicitly use --allow-unreviewed-reference for a demonstration.')
    if status not in {'candidate_pending_review','review_recorded'}:
        raise ValueError('Unrecognized reference review status')
    if status == 'review_recorded':
        review = meta.get('review', {})
        for k in ('reviewer','review_csv_sha256','original_candidate_sha256','recorded_at','note'):
            if not review.get(k):
                raise ValueError('Incomplete recorded review metadata')
    source = YamlSource(source_path, source_path.name)
    if source.digest != meta.get('source_sha256'):
        raise ValueError('Source SHA-256 does not match the reference. Regenerate/review the reference for this YAML.')
    if meta.get('mask') != profile['mask']:
        raise ValueError('Reference mask differs from its recorded profile')
    if ref.get('closure') != CLOSURE:
        raise ValueError('Unexpected scope/closure; cannot apply this adapter')
    node_ids = {n['id'] for n in ref['nodes']}
    if len(node_ids) != len(ref['nodes']):
        raise ValueError('Duplicate reference node IDs')
    edges = [edge_key(e) for e in ref['edges']]
    if len(set(edges)) != len(edges):
        raise ValueError('Duplicate reference edges')
    for u,r,v in edges:
        if r not in RELATIONS or not {u,v} <= node_ids:
            raise ValueError('Invalid reference edge type or endpoint')
    recorded_defs = [{k:v for k,v in q.items() if k not in ('full','masked')} for q in ref['queries']]
    expected_defs = [dict(q, weight=q.get('weight',1)) for q in profile['queries']]
    if recorded_defs != expected_defs:
        raise ValueError('Reference questions differ from the answer-free profile')
    locator_count = 0
    for record in ref['nodes']+ref['edges']+ref.get('excluded', []):
        if not record.get('support'):
            raise ValueError('Reference record lacks source witnesses')
        for loc in record['support']:
            current = source.locate(loc['kind'],loc['name'],loc['field'],loc.get('namespace','default'))
            if current != loc:
                raise ValueError('Source location or hash does not resolve to the bound YAML')
            locator_count += 1
    for q in ref['queries']:
        if not {q['source'],q['target']} <= node_ids:
            raise ValueError('Reference query endpoint absent')
        full = 'T' if witness(set(edges),q) is not None else 'F'
        if q['full'] != full or q['masked'] not in {'T','F','U','C'}:
            raise ValueError('Reference query labels violate the typed-graph contract')
    # Recheck own derivations for corruption; explicitly not independent annotation.
    projected = declared_projection(source, source.objects)
    if projected['unresolved']:
        raise ValueError('Unresolved full input cannot establish this architectural reference')
    if {(n['id'],n['type']) for n in projected['nodes']} != {(n['id'],n['type']) for n in ref['nodes']}:
        raise ValueError('Reference nodes differ from the declared projection')
    if {edge_key(e) for e in projected['edges']} != set(edges):
        raise ValueError('Reference edges differ from the declared projection')
    if projected['nodes'] != ref['nodes'] or projected['edges'] != ref['edges'] or projected['excluded'] != ref.get('excluded'):
        raise ValueError('Reference derivations/exclusions differ from the declared projection')
    masked_objects, changes = apply_mask(source.objects,profile['mask'])
    masked = declared_projection(source,masked_objects)
    if any(answer(masked,q)['state'] != q['masked'] for q in ref['queries']):
        raise ValueError('Masked support labels differ from the recorded perturbation and rules')
    return {'status':'MECHANICAL_CHECKS_PASSED','reference_sha256':sha256(reference_path),
            'source_sha256':source.digest,'reference_status':status,'resolved_locators':locator_count,
            'mask_changes':len(changes),'independent_validation':False,'boundary':BOUNDARY}


def compare_references(candidate_path: Path, historical_path: Path, output: Path) -> dict:
    """A separate, after-generation semantic comparison; never feeds the builder."""
    cand, hist = read_json(candidate_path), read_json(historical_path)
    rows = []
    for name, a, b in [
        ('typed_nodes', sorted((n['id'],n['type']) for n in cand['nodes']), sorted((n['id'],n['type']) for n in hist['nodes'])),
        ('typed_edges', sorted(edge_key(e) for e in cand['edges']), sorted(edge_key(e) for e in hist['edges'])),
        ('query_definitions_and_labels', sorted((q['id'],q['kind'],q['source'],q['target'],q.get('weight',1),q['full'],q['masked']) for q in cand['queries']),
         sorted((q['id'],q['kind'],q['source'],q['target'],q.get('weight',1),q['full'],q['masked']) for q in hist['queries'])),
        ('excluded_endpoints', sorted((r.get('source'),r.get('field'),r.get('value')) for r in cand.get('excluded',[])),
         sorted((r.get('source'),r.get('field'),r.get('value')) for r in hist.get('excluded',[])))]:
        rows.append({'check':name,'status':'MATCH' if a==b else 'MISMATCH',
                     'candidate_count':len(a),'historical_count':len(b),
                     'candidate_only':[r for r in a if r not in b], 'historical_only':[r for r in b if r not in a]})
    result = {'all_match':all(r['status']=='MATCH' for r in rows), 'checks':rows,
              'candidate_sha256':sha256(candidate_path),'historical_sha256':sha256(historical_path),
              'comparison_scope':'Typed nodes/edges, query definitions/labels and excluded endpoints, not identical JSON bytes or complete metadata.',
              'boundary':'Agreement demonstrates consistency with the retained reference, not independent ground-truth validation.'}
    safe_destination(output,[candidate_path,historical_path])
    write_json(output/'reference_comparison.json',result)
    write_csv(output/'reference_comparison.csv',rows)
    return result


def finalize(candidate_path: Path, review_path: Path, output: Path, reviewer: str, note: str,
             attest_independent: bool = False) -> dict:
    """Record supplied completed review decisions without inventing approval."""
    ref = read_json(candidate_path)
    meta = ref.get('reference_metadata', {})
    if meta.get('status') != 'candidate_pending_review':
        raise ValueError('Finalize requires an unchanged pending candidate')
    digest = sha256(candidate_path)
    expected = {r['record_id']:r for r in review_rows(ref,digest)}
    with review_path.open(newline='',encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if set(reader.fieldnames or []) != set(REVIEW_FIELDS):
            raise ValueError('Review CSV columns were altered')
        rows = list(reader)
    if len(rows) != len(expected) or len({r['record_id'] for r in rows}) != len(rows):
        raise ValueError('Review must contain each generated record exactly once')
    for row in rows:
        original = expected.get(row['record_id'])
        if not original or any(row[k] != original[k] for k in REVIEW_FIELDS if k not in ('decision','reviewer','notes')):
            raise ValueError('Review record/hash differs from the unchanged candidate')
        if row['decision'].strip().upper() != 'APPROVE' or not row['reviewer'].strip() or not row['notes'].strip():
            raise ValueError(f'Record {row["record_id"]} needs APPROVE, reviewer and substantive review notes')
    _plain(reviewer,'Reviewer'); _plain(note,'Review note')
    meta['status'] = 'review_recorded'
    meta['independent_validation'] = False
    meta['review'] = {'reviewer':reviewer,'note':note,'recorded_at':stamp(),
                      'original_candidate_sha256':digest,'review_csv_sha256':sha256(review_path),
                      'records_reviewed':len(rows),'independence_attested_by_submitter':attest_independent,
                      'identity_or_independence_verified_by_software':False}
    ref['reference_status'] = 'Human review recorded as supplied; reviewer identity, correctness and independence not verified by software.'
    safe_destination(output,[candidate_path,review_path])
    write_json(output/'reference.json',ref)
    (output/'review.csv').write_bytes(review_path.read_bytes())
    (output/'candidate.json').write_bytes(candidate_path.read_bytes())
    (output/'reference.sha256').write_text(sha256(output/'reference.json')+'  reference.json\n',encoding='utf-8')
    return {'status':'REVIEW_RECORDED','reference':str(output/'reference.json'), 'records':len(rows),
            'reference_sha256':sha256(output/'reference.json'),'independent_validation':False}
