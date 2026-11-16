# ArchGraphBench — Method and Run Guide

**Release:** 4.0.0-submission-demo  
**Paper:** `ArchGraphBench_Proofread_Submission_Candidate(1).pdf`  
**Purpose:** Generate the experimental records, tables and numerical figures for the supplied manuscript.

## 1. What ArchGraphBench is

**ArchGraphBench checks whether a computer-generated map of an application is reliable enough for the questions being asked of it.** It checks the components and connections, the answers obtained from that map, and whether the available configuration evidence supports those answers.

A *graph* is a set of components (nodes) and relationships (edges). A *reconstructed graph* is recovered from configuration or other technical records rather than accepted as correct merely because a tool drew it.

For example, configuration can declare:

```text
External entry → Frontend → Checkout → Payment
```

Missing the first relationship can hide the declared path to payment even when most other edges are correct. Removing the payment endpoint from the available evidence should produce uncertainty, not automatically prove that the path does not exist.

The paper's contribution is the evaluation method. M1, MP and M2 are experimental reconstruction baselines. The reference builder is supporting infrastructure, not an independent truth oracle.

## 2. The two references

| Reference | Meaning | When evidence is withheld |
|---|---|---|
| Architectural reference, `G_ref` | The expected graph within the declared full-evidence scope. | Remains fixed. |
| Support reference, `H` | The answers justified by the evidence available in this condition. | Changes according to the documented evidence rules. |

The extractor receives source evidence, not reference answers. The evaluator reads the reference after prediction.

T means supported true; F means supported false within an explicit scope; U means unknown; C means admissible positive and negative evidence conflict. The generic structured contract supports all four states. The manifest path experiment primarily uses T/F/U; it is not a natural-language contradiction detector.

## 3. Inputs and programs

| Input | Meaning | Used by |
|---|---|---|
| `data/public_case/source/kubernetes-manifests.yaml` | Retained Online Boutique deployment configuration. | Boutique reconstruction and optional reference builder. |
| `data/public_case/reference.json` | Historical graph, eight queries, and full/masked support labels. | Boutique evaluator only. |
| `profiles/online_boutique.json` | Answer-free scope, question definitions and one-field mask. | Reference builder. |
| `data/study/data/<application>/manifest.yaml` | Bookinfo, Sock Shop, Voting App and Guestbook configurations. | M1, MP, M2 membership reconstruction. |
| `data/study/reference*.json` | Frozen Service/workload backend memberships. | Membership evaluation and other-application fitting labels. |
| `data/replay/annotated_connections.json` | Source-study TP/FN annotations and identified FP edges, with source text and locations. | Primary archived replay. |
| `data/replay/tool_comparison/` | External reference DFDs, retained raw outputs and component mappings. | Replay and raw-direction sensitivity. |
| `data/experiment_config.json` | Graph sizes, policies, thresholds, project lists and weighting settings. | Study controllers. |

A Kubernetes manifest describes configuration; the program does not deploy it. The Boutique file is the historical retained transcription, not a byte-identical upstream claim. The replay annotation file is an explicitly documented browser transcription of source-study records.

## 4. Core evaluation algorithm

```text
ALGORITHM EvaluateArchitecture
INPUT: source bundle B, scope, rules, fixed reference G_ref,
       query set Q, reconstruction method M, evidence conditions
OUTPUT: predicted graphs, answers, witnesses and scores

Check input versions, checksums, schema and scope.
FOR each evidence condition:
    B_current = apply the declared condition to a copy of B
    H = determine justified answers from B_current and the rules
        without using M's predictions
    predicted = M(B_current)  // never give G_ref or H to the extractor
    Compare typed nodes/edges against G_ref.
    FOR each query:
        Compute the architectural answer on G_ref.
        Compute the semantic answer on the predicted supported graph.
        Compute the evidence-aware answer using supported/possible edges.
        Retain the path, source records or bounded-negative explanation.
    Calculate Ds and De on the declared query population.
    Select definite commitments under the experiment's acceptance rule.
    Calculate accepted count, coverage and unsupported certainty.
    Save intermediate records and final scores.
```

Structural F1 is `2*TP / (2*TP + FP + FN)`. `Ds` is weighted disagreement of architectural query answers. `De` is weighted disagreement with the condition-specific support answers. Coverage is accepted commitments divided by the fixed proposition population. UCR is unsupported accepted commitments divided by all accepted commitments; an empty accepted set has undefined UCR.

A threshold changes selection, coverage and UCR, not the already calculated `De`. A graph-path claim does not imply a working network connection, authentication or authorization.

## 5. Reference construction

`build_reference.py` calls `archgraphbench/reference_builder.py`.

```text
Read full Boutique YAML and the answer-free profile.
Enumerate admitted workloads, explicit accounts and entry nodes.
Resolve selectors, labels, declared ports and literal *_ADDR fields.
Record included edges, source locations and excluded endpoints.
Apply the one-field mask to an in-memory copy.
Compute full and masked support answers without M1/M2 predictions.
Write candidate reference.json, query_evidence.json and review.csv.
```

The candidate remains `candidate_pending_review`. Its rules share assumptions with M2 even though the builder is a separate code path. The builder only covers the specified Boutique scope; it does not reconstruct all Kubernetes or enterprise architecture formats.

## 6. Study algorithms

### A. Diagnostics — Tables II, V, VI and Figure 6

Generate chains of 10, 100 and 1,000 edges and remove their middle bridge. Evaluate four selected source-to-target paths. Separately construct the Table V single-edge/attribute cases.

Enumerate four proposition slots, each in T/F/U/C, giving 256 configurations. Apply evidence preserving, positive precedence, closed world and always unknown. Evaluate thresholds 0.5, 0.8 and 0.95 with assigned singleton confidence 0.9, using equal and `[4,4,3,2]` query weights.

Enumerate 81 weight vectors from `{1,2,4}^4`; compare the two fixed error profiles using exact rational arithmetic. These are constructed diagnostics, not samples of independent deployments.

### B. Online Boutique — Table VII

M1 resolves endpoint/entry resources by name. M2 resolves selectors, workload labels and the experiment's declared port rules. Both recover explicit service-account assignments.

```text
lower_graph = supported edges
upper_graph = supported edges + possible in-scope edges

IF the query has a witness in lower_graph: answer T
ELSE IF it has a witness only in upper_graph: answer U
ELSE IF the relevant declared scope is complete: answer F
ELSE: answer U
```

Flow queries use only configured-dependency and declared-entry edges, not identity edges. The mask withholds checkout's `PAYMENT_SERVICE_ADDR`. M2-CW uses M2's same supported graph but returns F for unresolved paths. All emitted T/F query answers are accepted in this case; UCR is query-level support evaluation, not full source entailment.

### C. Cross-system membership — Table VIII

For each application, enumerate every same-namespace Service/workload-template pair. M1 requires an exact name; MP accepts exact or hyphen-delimited prefix names; M2 requires every selector key/value to match and selects no templates for an empty selector.

Ask whether each Service has at least one and at least two distinct workload templates. These are backend-cardinality queries, not path queries or replica counts.

```text
FOR each held-out application:
    Training pairs = all pairs from the other three applications
    Fit p=(k+1)/(n+2) within exact-name, prefix and other-name strata
    Apply those probabilities to test features WITHOUT their labels
    Predict T above .5, F below .5, abstain at equality
    Confidence = max(p, 1-p)
    Attach held-out labels only for evaluation
    Calculate Brier scores and threshold decisions
```

Comparators are hard exact-name decisions, .9 for exact names/.1 otherwise, and training prevalence. Report both pair-weighted and equal-application means.

### D. Annotated archived replay — Table IX

For every available tool/application record, form predictions from the source study's TP and identified FP connections. Keep FN annotations in the audit but do not insert their edges. Retain extra endpoints and self-loops. Use the supplied external reference graph for evaluation.

Evaluate every ordered pair of distinct reference nodes. Calculate connection F1 and path disagreement, with deterministic path witnesses. Compare the two tools on their ten common systems. Seven missing MicroDepGraph records are not treated as empty predictions.

Run raw-direction sensitivity separately. `raw_normalized` uses lowercase and hyphen-to-underscore normalization. `raw_published_aliases` additionally uses archived component mappings. Neither mode changes raw directions according to TP connection labels. The explicit alternatives matter because raw alignment is not fully specified in the paper.

### E. Held-out positive-edge calibration — Section VII-G

```text
For each common application, union the tools' positive-edge proposals.
Assign each proposal to both tools, Code2DFD alone or MicroDepGraph alone.
FOR each held-out application:
    Fit c=(k+1)/(n+2) per group using the other nine applications
    Apply c to held-out proposal features, then attach correctness labels
    Accept a positive-edge proposal only when c >= threshold
Calculate Brier, fixed-.9 comparison, precision, coverage and recall.
Calculate ECE in fixed equal-width 10-bin and 5-bin partitions.
```

Unlike membership prediction, this does **not** turn low c into a negative-edge answer. Coverage is over proposed edges; recall is over all paired-system reference edges. All folds, bins and decisions are saved.

## 7. Install and run

Extract into a new folder such as `C:\AGB_Submission`. Use Python 3.11 or newer.

```powershell
cd C:\AGB_Submission
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-plots.txt
.\.venv\Scripts\python.exe run_all_evidence.py --data data --out run_01 --demo --checks
```

The default uses the retained reference. To build and use a new Boutique reference candidate:

```powershell
.\.venv\Scripts\python.exe run_all_evidence.py --data data --reference-mode generated --out run_candidate --demo --checks
```

To pause during a Boutique demonstration:

```powershell
.\.venv\Scripts\python.exe process.py --data data --study boutique --out demo_boutique --demo --pause
```

For detailed execution decisions, add `--trace`. Use `--trace-limit 0` to remove trace limits. Pauses require an interactive terminal; `--step-delay 1` provides automatic pacing. Normal runs use local data; installing dependencies may require internet access.

On macOS/Linux, use `python3 -m venv .venv`, then `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

## 8. Open the outputs

| File under `run_01/results/` | Meaning |
|---|---|
| `table_V_structural_arithmetic.csv` | Computed single-edge/attribute F1 results. |
| `table_VI_support_controls.csv` | Four support-state policies at threshold 0.8. |
| `table_VII_boutique.csv` | Five Boutique full/masked cases. |
| `table_VIII_membership.csv` | Four-application M1/MP/M2 and held-out Brier results. |
| `table_IX_replay.csv` | Annotated connection/path scores on ten paired applications. |
| `boutique/queries.json` | Q2/Q4 answers, uncertainty and paths with source evidence. |
| `membership/confidence_predictions.csv` | Every held-out pair's fitted probability and later correctness label. |
| `replay/annotation_records.json` | Source labels, source excerpts, URLs and edge inclusion decisions. |
| `replay/annotated_path_answers.csv` | All 3,150 directed-path evaluations and witnesses. |
| `calibration/annotated/results.json` | Main proposal counts, Brier, ECE and threshold results. |
| `calibration/annotated/folds.json` | Training/test application separation and fitted group counts. |
| `evidence/evidence_index.csv` | Paper-item to input/algorithm/output mapping. |
| `logs/algorithm.log` | Human-readable live execution history. |

Figures 1–5 and Tables I/III/IV describe the method; they are not new experimental observations. Figure 6 is plotted from the calculated weight settings. Alternate table formats are in `tables/`.

## 9. Source and validation boundaries

Frozen YAML and reference datasets are retained unchanged. New replay annotations are a browser-transcribed projection of the cited source archive, with all original labels and locators retained; local hashes do not prove upstream byte identity. `tools/verify_replay_sources.py` can verify the projection against a locally extracted source archive or newly acquired upstream text without modifying `data/`.

The main calculations reproduce the checked manuscript values. One statement in Section VII-G remains unresolved: the manuscript says raw-direction sensitivity accepts nothing at .95, whereas the explicit raw-alignment variants here produce nonempty accepted sets. See `validation/VERIFICATION.md`. This is not hidden by altering inputs or probabilities.

Tests, input integrity, numerical agreement and independent scientific validation are different checks. Runtime security, independent human adjudication, source entailment and reviewer timing are not established by this program. The test counts in a new release describe its current suite, not a replay of the manuscript's historical test session.
