"""Paper Section III: typed graphs, dual references, T/F/U/C, Eq. 4 and Eq. 5.

Source polarity/admissibility are supplied judgments, not an NLP entailment model.
Absence of a judgment is not a negative judgment. All results are scope-relative.
"""
from __future__ import annotations
from .execution_log import checkpoint, debug, context
from collections import deque, Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from fractions import Fraction
import math
from typing import Any, Iterable, Sequence

STATES = ("T", "F", "U", "C")
EPISTEMIC = ("observed", "inferred", "assumed", "unknown", "conflicting")
Edge = tuple[str, str, str]
FLOW = frozenset({"configured_dependency", "declared_entry"})


def finite_number(value: Any, label: str = "number") -> float:
    """Validate a numerical input; reject booleans and non-finite values."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric, not a boolean")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


@dataclass(frozen=True)
class Assertion:
    """Eq. 2: eight semantic fields; missing confidence does not imply certainty."""
    s: str
    p: str
    o: str
    tau: str
    locator: Any
    epistemic: str
    confidence: float | None
    validity: tuple[Any, Any]

    def __post_init__(self):
        if self.epistemic not in EPISTEMIC:
            raise ValueError(f"Unknown assertion status: {self.epistemic}")
        if not all(isinstance(x, str) and x for x in (self.s, self.p, self.o, self.tau)):
            raise ValueError("Assertion entity, predicate and semantic type must be nonempty strings")
        if self.confidence is not None and not 0 <= finite_number(self.confidence) <= 1:
            raise ValueError("Confidence must be in [0,1] or null")
        if len(self.validity) != 2:
            raise ValueError("A half-open interval requires two bounds")
        lo, hi = self.validity
        if lo is not None and hi is not None and _time(lo) >= _time(hi):
            raise ValueError("Empty/reversed assertion validity interval")

    def record(self):
        """Export the eight-field assertion without inventing missing metadata."""
        return asdict(self)


@dataclass
class EvidenceBundle:
    """Eq. 1: artifacts, versions/checksums, time validity and licenses."""
    artifacts: list[dict]
    versions: dict
    validity: dict
    licenses: dict


def support_state(positive: bool, negative: bool) -> str:
    """Map positive/negative support to T, F, U or C (paper Section III-C)."""
    return {(False, False): "U", (True, False): "T", (False, True): "F", (True, True): "C"}[bool(positive), bool(negative)]


def set_metrics(reference: Iterable, prediction: Iterable) -> dict:
    # Compare typed records, not merely their count. Equal edge counts can
    # conceal a missing true edge and an invented edge.
    """Compute TP/FP/FN and precision/recall/F1 for typed node or edge sets.

    Empty-denominator scores remain None. An exact fraction is retained for
    structural diagnostics; no expected score enters this function.
    """
    gold, pred = set(reference), set(prediction)
    tp, fp, fn = len(gold & pred), len(pred - gold), len(gold - pred)
    den = 2 * tp + fp + fn
    exact = Fraction(2 * tp, den) if den else None
    debug("CORE", "SET_METRICS", "Calculate F1 from true/false/missing records.",
          tp=tp, fp=fp, fn=fn, numerator=2*tp, denominator=den,
          f1_exact=str(exact) if exact is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "reference_count": len(gold), "predicted_count": len(pred),
            "precision": tp / len(pred) if pred else None, "recall": tp / len(gold) if gold else None,
            "f1": float(exact) if exact is not None else None, "f1_exact": str(exact) if exact is not None else None}


def weighted_divergence(reference: Sequence, prediction: Sequence, weights: Sequence) -> float:
    """Eq. 4. Fraction arithmetic preserves exact integer/rational diagnostics."""
    if not reference or len(reference) != len(prediction) or len(reference) != len(weights):
        raise ValueError("Divergence requires a nonempty, aligned population and weights")
    rational = []
    for w in weights:
        if finite_number(w, "query weight") <= 0:
            raise ValueError("Query weights must be strictly positive")
        rational.append(Fraction(str(w)))
    numerator = sum((w for a, b, w in zip(reference, prediction, rational) if a != b), Fraction())
    denominator = sum(rational)
    debug("CORE", "DIVERGENCE", "Sum the weights of mismatches, then divide by all query weights.",
          mismatches=sum(a != b for a, b in zip(reference, prediction)),
          queries=len(reference), numerator=str(numerator), denominator=str(denominator))
    return float(numerator / denominator)


def query_weights(queries: list[dict], family_weights: dict | None = None) -> list[float]:
    """Assign positive query weights; optionally divide each family total equally.

    Duplicate query identifiers are rejected so repeated questions cannot
    silently acquire extra weight (paper Section IV-B).
    """
    if not queries:
        raise ValueError("No applicable queries: divergence is undefined")
    ids = [q["id"] for q in queries]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate query IDs")
    if family_weights is None:
        weights = [q.get("weight", 1.0) for q in queries]
    else:
        counts = Counter(q["family"] for q in queries)
        if set(family_weights) != set(counts):
            raise ValueError("Family weights must identify exactly the nonempty query families")
        if any("weight" in q for q in queries):
            raise ValueError("Use individual weights or family weights, not both")
        weights = [finite_number(family_weights[q["family"]]) / counts[q["family"]] for q in queries]
    if any(finite_number(w) <= 0 for w in weights):
        raise ValueError("Query weights must be strictly positive")
    return weights


def path_witness(edges: Iterable[Edge], source: str, target: str,
                 permitted: set[str] | frozenset[str] = FLOW) -> list[Edge] | None:
    """Deterministic shortest directed positive-length path, with typed traversal."""
    # Sorted adjacency makes tied shortest-path witnesses deterministic.
    # Only permitted edge types enter the search: identity assignments must
    # never create an application communication path.
    debug("CORE", "BFS_START", "Search a typed, directed, positive-length path.",
          source=source, target=target, permitted=sorted(permitted))
    adjacent = {}
    for edge in sorted(set(edges)):
        if edge[1] in permitted:
            adjacent.setdefault(edge[0], []).append(edge)
    seen = {source}
    queue = deque([(source, [])])
    while queue:
        node, path = queue.popleft()
        for edge in adjacent.get(node, []):
            if edge[2] == target:
                debug("CORE", "BFS_FOUND", "A supported path reaches the requested target.",
                      source=source, target=target, path_length=len(path)+1)
                return path + [edge]
            if edge[2] not in seen:
                seen.add(edge[2]); queue.append((edge[2], path + [edge]))
    debug("CORE", "BFS_ABSENT", "No path found in this graph; evidence interpretation happens separately.",
          source=source, target=target, visited_nodes=len(seen))
    return None


def query_witness(edges: Iterable[Edge], query: dict) -> list[Edge] | None:
    """Evaluate a typed path, identity, direct-entry or generic-edge predicate."""
    edges = set(edges)
    kind, a, b = query["kind"], query["source"], query["target"]
    if kind == "path":
        return path_witness(edges, a, b, set(query.get("relations", FLOW)))
    relation = {"identity": "assigned_service_account", "direct_entry": "declared_entry"}.get(kind)
    if kind == "edge":
        relation = query["relation"]
    if relation is None:
        raise ValueError(f"Unsupported predicate kind: {kind}")
    edge = (a, relation, b)
    return [edge] if edge in edges else None


def graph_answer(lower: set[Edge], possible: set[Edge], query: dict, *, complete: bool,
                 closed_world: bool = False) -> dict:
    # The lower graph contains supported edges; the upper graph admits
    # unresolved possibilities. F is justified only under finite-scope
    # completeness. The closed-world ablation intentionally ignores that U.
    """Evaluate lower/upper graphs while separating architectural and support answers.

    The closed-world ablation deliberately maps unresolved answers to F; the
    evaluator, not this function, later decides whether that claim is justified.
    """
    with context(graph="lower"):
        lower_path = query_witness(lower, query)
    with context(graph="upper"):
        upper_path = query_witness(lower | possible, query)
    if lower_path is not None:
        state, reason = "T", "A lower-graph witness supports the declared predicate."
    elif closed_world:
        state, reason = "F", "Closed-world policy emits a denial without resolving remaining uncertainty."
    elif upper_path is not None:
        state, reason = "U", "A path/edge is possible only through unresolved upper-graph alternatives."
    elif not complete:
        state, reason = "U", "No witness found, but scope is not complete enough for a negative."
    else:
        state, reason = "F", "No lower/upper witness within the explicitly complete declared scope."
    debug("CORE", "GRAPH_ANSWER", "Keep structural and evidential answers separate.",
          query=query.get("id"), kind=query["kind"], lower_witness=lower_path is not None,
          upper_witness=upper_path is not None, complete=complete, closed_world=closed_world,
          semantic="T" if lower_path is not None else "F", evidence=state, reason=reason)
    return {"semantic": "T" if lower_path is not None else "F", "evidence": state,
            "witness": lower_path, "possible_witness": upper_path if lower_path is None else None,
            "bounded_negative": state == "F" and complete and upper_path is None,
            "reason": reason}


def selection_metrics(reference: Sequence[str], prediction: Sequence[str],
                      confidences: Sequence[float | None] | None = None,
                      threshold: float | None = None,
                      justification: Sequence[bool | None] | None = None) -> dict:
    """Query UCR if justification omitted; full J_d supplied explicitly otherwise.

An unadjudicated accepted J_d yields full UCR=None, not a fabricated zero.
Confidence selection never changes the pre-threshold predictions or D_e.
"""
    if not reference or len(reference) != len(prediction):
        raise ValueError("Fixed nonempty aligned proposition population required")
    if any(s not in STATES for s in list(reference) + list(prediction)):
        raise ValueError("Support outcomes must be T/F/U/C")
    n = len(reference)
    if confidences is None:
        confidences = [None] * n
    if len(confidences) != n or (justification is not None and len(justification) != n):
        raise ValueError("Unaligned confidence or justification vector")
    if threshold is not None and not 0 <= finite_number(threshold) <= 1:
        raise ValueError("Threshold must be in [0,1]")
    for c in confidences:
        if c is not None and not 0 <= finite_number(c) <= 1:
            raise ValueError("Confidence must be in [0,1] or null")
    # Acceptance is a selection step, not a change to the predictions used
    # for D_e. U/C answers are never accepted as definite T/F commitments.
    accepted = [i for i, state in enumerate(prediction) if state in ("T", "F") and
                (threshold is None or (confidences[i] is not None and confidences[i] >= threshold))]
    judges = list(justification) if justification is not None else [a == b for a, b in zip(reference, prediction)]
    if any(v is not None and not isinstance(v, bool) for v in judges):
        raise ValueError("J_d judgments must be true, false, or null")
    unknown = sum(judges[i] is None for i in accepted)
    unsupported = sum(judges[i] is False for i in accepted)
    debug("CORE", "SELECTION", "Count accepted commitments and their justified support.",
          threshold=threshold, accepted=len(accepted), population=n, unsupported=unsupported,
          unadjudicated=unknown, ucr=unsupported/len(accepted) if accepted and unknown == 0 else None)
    return {"accepted": len(accepted), "accepted_indices": accepted, "population": n,
            "coverage": len(accepted) / n, "unsupported": unsupported,
            "unadjudicated_accepted": unknown,
            "ucr": unsupported / len(accepted) if accepted and unknown == 0 else None,
            "ucr_target": "supplied_full_justification" if justification is not None else "query_state_support",
            "missing_confidence": sum(c is None for c in confidences), "threshold": threshold}


def _time(value):
    """Normalize numeric or timezone-qualified ISO time for validity filtering."""
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return finite_number(value, "time")
        if stamp.tzinfo is None:
            raise ValueError("ISO timestamps require an explicit timezone")
        return stamp.timestamp()
    return finite_number(value, "time")


def support_reference(propositions: list[str], records: list[dict], *, target_time: Any,
                      release: str, eligible_sources: set[str] | None = None,
                      admitted_derivations: set[str] | None = None,
                      precedence: list[str] | None = None,
                      removed_sources: set[str] | None = None) -> tuple[dict, list[dict]]:
    """Eq. 3 for already adjudicated structured support records.

Source-priority order is used ONLY if explicitly supplied by the codebook;
otherwise concurrent positive and negative support remains C.
"""
    if not propositions or len(propositions) != len(set(propositions)):
        raise ValueError("Support reference requires unique nonempty proposition IDs")
    if precedence is not None and len(precedence) != len(set(precedence)):
        raise ValueError("Duplicate source in precedence rule")
    now = _time(target_time)
    active, audit = {p: [] for p in propositions}, []
    for index, r in enumerate(records):
        if r.get("polarity") not in ("+", "-"):
            raise ValueError("Structured support record requires +/- polarity")
        reason = None
        if r["proposition"] not in active:
            reason = "outside_scope_unadjudicated"
        elif r.get("admissible") is not True:
            reason = "admissibility_not_established"
        elif r["source"] in (removed_sources or set()):
            reason = "source_removed"
        elif eligible_sources is not None and r["source"] not in eligible_sources:
            reason = "ineligible_source"
        elif r.get("release") != release:
            reason = "different_release"
        else:
            lo, hi = r.get("start"), r.get("end")
            if lo is not None and hi is not None and _time(lo) >= _time(hi):
                raise ValueError("Support validity interval is empty/reversed")
            if (lo is not None and now < _time(lo)) or (hi is not None and now >= _time(hi)):
                reason = "outside_half_open_validity_interval"
            elif r.get("derivation") and (admitted_derivations is None or r["derivation"] not in admitted_derivations):
                reason = "inference_rule_not_admitted"
        audit.append({"record_index": index, "proposition": r["proposition"], "source": r["source"],
                      "admitted": reason is None, "reason": reason or "admissible_current_support"})
        debug("CORE", "SUPPORT_FILTER", "Apply source, release, time and derivation eligibility.",
              proposition=r["proposition"], source=r["source"], polarity=r["polarity"],
              admitted=reason is None, reason=reason or "admissible_current_support")
        if reason is None:
            active[r["proposition"]].append(r)
    labels = {}
    for p, evidence in active.items():
        selected = evidence
        if precedence and evidence:
            ranks = {s: i for i, s in enumerate(precedence)}
            best = min(ranks.get(r["source"], len(ranks)) for r in evidence)
            selected = [r for r in evidence if ranks.get(r["source"], len(ranks)) == best]
        labels[p] = support_state(any(r["polarity"] == "+" for r in selected), any(r["polarity"] == "-" for r in selected))
    debug("CORE", "SUPPORT_STATES", "Map admissible positive/negative evidence to T/F/U/C.", labels=labels)
    return labels, audit


def evaluate_contract(case: dict) -> dict:
    """Reusable core beyond paper-sized fixtures; accepts structured data only.

No references enter any extractor. Here prediction graphs are already supplied;
this function is the method-independent evaluator, not a new recovery method.
"""
    def edge_set(rows):
        return {(r["source"], r["relation"], r["target"]) if isinstance(r, dict) else tuple(r) for r in rows}
    checkpoint("CONTRACT", "Evaluate supplied structured graphs and support records.")
    queries = case["queries"]
    weights = query_weights(queries, case.get("family_weights"))
    ref_edges = edge_set(case["reference_edges"])
    lower = edge_set(case["prediction_edges"])
    possible = edge_set(case.get("possible_edges", [])) - lower
    book = case["codebook"]
    labels, audit = support_reference([q["id"] for q in queries], case["support_records"],
        target_time=book["target_time"], release=book["release"],
        eligible_sources=set(book["eligible_sources"]) if "eligible_sources" in book else None,
        admitted_derivations=set(book.get("admitted_derivations", [])),
        precedence=book.get("precedence"), removed_sources=set(case.get("removed_sources", [])))
    rows = []
    overrides = case.get("predicted_support", {})
    if set(overrides) - {q["id"] for q in queries}:
        raise ValueError("Predicted support contains an out-of-scope query")
    for q, weight in zip(queries, weights):
        a = graph_answer(lower, possible, q, complete=bool(book.get("complete", False)))
        supplied = overrides.get(q["id"])
        if supplied is not None:
            if supplied not in STATES:
                raise ValueError("Predicted support must be T/F/U/C")
            a["evidence"] = supplied
            a["reason"] = "Participant-supplied four-state answer; graph witness shown separately."
            a["bounded_negative"] = supplied == "F" and a["bounded_negative"]
        rows.append({"query": q["id"], "weight": weight,
                     "architectural_reference": "T" if query_witness(ref_edges, q) is not None else "F",
                     "support_reference": labels[q["id"]], **a})
    gold_s = [r["architectural_reference"] for r in rows]
    gold_e = [r["support_reference"] for r in rows]
    pred_e = [r["evidence"] for r in rows]
    selection = selection_metrics(gold_e, pred_e,
        [case.get("confidences", {}).get(q["id"]) for q in queries], case.get("threshold"))
    full_selection = selection_metrics(gold_e, pred_e,
        [case.get("confidences", {}).get(q["id"]) for q in queries], case.get("threshold"),
        [case.get("justification", {}).get(q["id"]) for q in queries])
    return {"edge_metrics": set_metrics(ref_edges, lower),
            "Ds": weighted_divergence(gold_s, [r["semantic"] for r in rows], weights),
            "De": weighted_divergence(gold_e, pred_e, weights), "query_selection": selection,
            "full_justification_selection": full_selection, "queries": rows, "support_audit": audit,
            "boundary": "Structured source judgments supplied as data; automatic natural-language entailment is not claimed."}
