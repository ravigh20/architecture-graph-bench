"""Sections VII-D/E: source-only backend reconstruction and source witnesses."""
from __future__ import annotations
from .execution_log import info, debug
from dataclasses import dataclass
from pathlib import Path
from .io import YamlSource, read_json, write_csv, write_json
from .core import set_metrics

WORKLOADS = {'Deployment', 'StatefulSet', 'DaemonSet'}

@dataclass
class Inputs:
    source: YamlSource
    services: dict
    workloads: dict
    excluded: list


def load_inputs(path: Path, file_id: str | None = None) -> Inputs:
    # Resource kind + namespace + name establish identity before any joins.
    # This adapter compares backend membership, not routed network paths.
    """Read the admitted Service and workload templates with source locations.

    References and stored model predictions are not inputs to this parser.
    """
    source = YamlSource(path, file_id)
    services, workloads, excluded = {}, {}, []
    for obj in source.objects:
        kind, meta = obj['kind'], obj['metadata']
        name = f"{meta.get('namespace','default')}/{meta['name']}"
        if kind not in WORKLOADS | {'Service'}:
            excluded.append({'resource': name, 'kind': kind, 'reason': 'Outside admitted controller/Service kinds'})
            continue
        spec = obj['spec']
        target = services if kind == 'Service' else workloads
        if name in target:
            raise ValueError(f'Duplicate scoped service/workload ID: {name}')
        if kind == 'Service':
            selector = spec.get('selector', {})
            if not selector:
                excluded.append({'resource': name, 'kind': kind, 'reason': 'Empty selector: retained Service; selector method selects no templates'})
            services[name] = {'selector': selector, 'type': spec.get('type','ClusterIP'), 'kind': kind}
        else:
            workloads[name] = {'labels': spec['template']['metadata'].get('labels', {}), 'kind': kind}
    info("BACKENDS", "INVENTORY", "Parse Services and workload templates in their namespace.",
         file=source.file_id, services=len(services), workload_templates=len(workloads), excluded=len(excluded))
    return Inputs(source, services, workloads, excluded)


def pairs(inp: Inputs) -> list[tuple[str,str]]:
    """Enumerate every Service/workload candidate sharing a namespace."""
    return [(s,w) for s in sorted(inp.services) for w in sorted(inp.workloads) if s.split('/')[0] == w.split('/')[0]]


def stratum(service: str, workload: str) -> str:
    """Assign an exact-name, hyphen-prefix or other-name feature without labels."""
    s,w = service.split('/')[-1], workload.split('/')[-1]
    if s == w: return 'exact'
    if s.startswith(w+'-') or w.startswith(s+'-'): return 'prefix'
    return 'other'


def extract(inp: Inputs, include_prefix: bool = False) -> dict:
    """Reads no reference, expected score, or stored LLM response."""
    result = {m:{s:[] for s in inp.services} for m in (('name','prefix','selector') if include_prefix else ('name','selector'))}
    # Every same-namespace pair is tested; multiple versions count as
    # distinct workload templates, whereas Deployment replicas do not.
    for s,w in pairs(inp):
        name_match = stratum(s,w) == 'exact'
        if name_match: result['name'][s].append(w)
        if include_prefix and stratum(s,w) in ('exact','prefix'): result['prefix'][s].append(w)
        selector = inp.services[s]['selector']
        selector_match = bool(selector) and all(inp.workloads[w]['labels'].get(k) == v for k,v in selector.items())
        if selector_match:
            result['selector'][s].append(w)
        debug("BACKENDS", "PAIR", "Calculate exact-name and selector membership for one candidate pair.",
              service=s, workload=w, name_match=name_match, prefix_match=stratum(s,w) in ('exact','prefix'), selector_match=selector_match,
              selector=selector, labels=inp.workloads[w]['labels'])
    return result


def edges(graph: dict) -> set:
    """Convert a backend-set mapping to a set of directed Service/workload pairs."""
    if not isinstance(graph, dict) or any(not isinstance(v,list) or any(not isinstance(x,str) for x in v) for v in graph.values()):
        raise ValueError('Backend prediction must map Service IDs to arrays of workload IDs')
    return {(s,w) for s,backends in graph.items() for w in backends}


def score(graph: dict, gold: dict, inp: Inputs) -> dict:
    """Evaluate frozen predictions after extraction using the supplied reference.

    The query families test at least one and at least two distinct templates;
    they do not count replicas or establish runtime network reachability.
    """
    metrics = set_metrics(edges(gold), edges(graph))
    rows = []
    for service in sorted(gold):
        expected, predicted = set(gold[service]), set(graph.get(service, []))
        rows.append({'service': service, 'reference': sorted(expected), 'prediction': sorted(predicted),
                     'same_set': expected == predicted, 'public_kind': inp.services[service]['type'] in ('NodePort','LoadBalancer'),
                     'ge1': {'gold': len(expected)>=1, 'pred':len(predicted)>=1},
                     'ge2': {'gold': len(expected)>=2, 'pred':len(predicted)>=2}})
    for n in (1,2):
        name = f'ge{n}'
        metrics[name] = {'fp':sum(r[name]['pred'] and not r[name]['gold'] for r in rows),
                         'fn':sum(r[name]['gold'] and not r[name]['pred'] for r in rows),
                         'gold_positive':sum(r[name]['gold'] for r in rows),'total':len(rows)}
    metrics.update(queries=rows, missing_service_ids=sorted(set(gold)-set(graph)), extra_service_ids=sorted(set(graph)-set(gold)),
                   query_mismatches=sum(metrics[k][d] for k in ('ge1','ge2') for d in ('fp','fn')),
                   query_total=2*len(rows), wrong_sets=sum(not r['same_set'] for r in rows),
                   public_wrong_sets=sum(r['public_kind'] and not r['same_set'] for r in rows),
                   public_total=sum(r['public_kind'] for r in rows))
    return metrics


def candidate_witness(inp: Inputs, s: str, w: str) -> dict:
    """Explain a candidate membership using actual selector and template fields.

    A mismatch is a bounded negative in the complete template inventory, not
    an assertion that network policies prevent communication.
    """
    ns, sn = s.split('/',1); wn = w.split('/',1)[1]
    selector, labels = inp.services[s]['selector'], inp.workloads[w]['labels']
    failures = [{'key':k, 'selector_value':v, 'template_value':labels.get(k), 'missing':k not in labels}
                for k,v in selector.items() if labels.get(k) != v]
    return {'service':s,'workload':w, 'selector':selector,'labels':labels,'mismatches':failures,
            'relation_supported_by_selector':bool(selector) and not failures,
            'selector_locator':inp.source.locate('Service',sn,'spec/selector',ns),
            'template_locator':inp.source.locate(inp.workloads[w]['kind'],wn,'spec/template/metadata/labels',ns),
            'negative_scope':'Complete same-namespace template inventory; not a NetworkPolicy verdict.'}

