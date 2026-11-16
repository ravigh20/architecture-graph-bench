# ArchGraphBench — File Reference

Paths below are relative to the package root or to the current run's `results/` directory, as indicated. Use the method guide for the run sequence.

## Programs

| File | Responsibility |
|---|---|
| `run_all_evidence.py` | Optional reference generation, processing, figures, evidence index and optional checks. |
| `process.py` | Executes selected studies; supports `all`, `diagnostics`, `boutique`, `membership`, `replay`, `calibration`, `contract`, and legacy `bookinfo`. |
| `build_reference.py` | Builds/verifies a Boutique reference candidate and records completed review. |
| `archgraphbench/core.py` | Typed graphs, support rules, path witnesses and metrics. |
| `archgraphbench/boutique.py` | Boutique M1/M2 and masking evaluation. |
| `archgraphbench/backends.py` | Source-only exact-name, optional prefix and selector membership. |
| `archgraphbench/membership.py` | Table VIII, four-application leave-one-out fitting and evaluation. |
| `archgraphbench/replay.py` | Table IX, annotated TP/FP graph assembly, raw sensitivity and path evaluation. |
| `archgraphbench/calibration.py` | Held-out positive-proposal correctness, ECE bins and selection. |
| `archgraphbench/diagnostics.py` | Constructed graph, state, threshold and weighting experiments. |
| `archgraphbench/evidence.py` | Paper-aligned tables, ledger, source excerpts and artifact index. |
| `archgraphbench/paper_figures.py` | Figures 1–6; method illustrations are separate from measured plots. |
| `archgraphbench/execution_log.py` | Live comments, tracing, pause controls and structured log events. |
| `tools/verify_replay_sources.py` | Optional full-source acquisition/projection verification. No changes to `data/`. |
| `run_checks.py` | Current implementation tests with actual logs and counts. |
| `verify_evidence.py` | Local output-integrity check, not a correctness oracle. |

The legacy `bookinfo_case/run_bookinfo.py` and saved-response data remain for backward compatibility. They are not part of the default submission-candidate workflow or new LLM experiment claims.

## Experimental inputs

| Path | Meaning |
|---|---|
| `data/input_manifest.json` | Frozen local file inventory and checksums. |
| `data/experiment_config.json` | Experiment parameters and application/threshold choices. |
| `data/public_case/source/kubernetes-manifests.yaml` | Retained Boutique configuration. |
| `data/public_case/source/upstream-commit.yaml` | Retained comparison copy; not downloaded during normal execution. |
| `data/public_case/source/source_registry.json` | Source version, attribution and acquisition qualifications. |
| `data/public_case/reference.json` | Frozen Boutique graph, questions and support labels. |
| `profiles/online_boutique.json` | Builder's answer-free scope and questions. |
| `data/study/data/<app>/manifest.yaml` | Source manifests for bookinfo, sockshop, voting and guestbook. |
| `data/study/reference.json` and `reference_guestbook.json` | Frozen backend labels. |
| `data/study/provenance/` | Original source records, licenses and field ledgers. |
| `data/replay/annotated_connections.json` | Browser-transcribed source-study TP/FN/FP connection records, not aggregate scores. |
| `data/replay/tool_comparison/groundtruth_textual/` | Seventeen retained external reference DFDs. |
| `data/replay/tool_comparison/results/recovery_correctness/raw_results/` | Retained tool JSON/SVG outputs for raw sensitivity. |
| `data/replay/tool_comparison/results/recovery_correctness/processed_results/` | Component-only alignment sections from the earlier input projection. |
| `data/replay/inputs_manifest.json`, `offline_inputs.json` | Original raw-projection inventory and acquisition qualifications. |

## Optional reference output

`<run>/generated_reference/` contains `reference.json`, `full_graph.json`, `masked_graph.json`, `query_evidence.json`, `mask.json`, `source_manifest.json`, `reference.sha256`, `review.csv`, `REVIEW_INSTRUCTIONS.md`, and `build.json`.

These are the candidate graph, support answers, source witnesses, hashes and pending review records. They are not M1/M2 predictions or independent human ground truth.

## Calculated output: `results/`

| Path | Meaning |
|---|---|
| `table_I_related_work.csv` | Descriptive comparison of approaches. |
| `table_II_support_transitions.csv` | Calculated structured-support transitions. |
| `table_III_tasks.csv` | Descriptive reconstruction tasks. |
| `table_IV_conventions.csv` | Descriptive scoring conventions. |
| `table_V_structural_arithmetic.csv` | Edge/attribute perturbation calculations. |
| `table_VI_support_controls.csv` | Four policy summaries at .8. |
| `table_VII_boutique.csv` | Full/masked reconstruction results. |
| `table_VIII_membership.csv` | Four-system reconstruction and held-out membership Brier values. |
| `table_IX_replay.csv` | Paired archived connection/path scores and ranking flags. |
| `tables/` | JSON and Markdown renderings of the calculated/descriptive tables. |
| `figures/` | Six PNG/SVG figures, figure-role labels and calculated Figure 6 coordinates. |

### Boutique and diagnostics

`boutique/graphs.json` contains supported and possible edges. `queries.json` and `queries.csv` contain both references, both predicted answer types, acceptance, unsupported flags, witnesses and explanations. `metrics.json` includes denominators. `reference_used.json`, `reference_provenance.json`, `mask.json`, and `source_comparison.json` identify the actual selected source/reference condition.

`diagnostics/` contains constructed chain graphs, query witnesses, single-edge arithmetic, structured support records, policy/threshold decisions, and all 81 weight settings. These are constructed populations, not real deployed systems.

### Cross-system membership

| Path under `membership/` | Meaning |
|---|---|
| `predictions.json` | M1, MP and M2 backend sets for all four applications. |
| `method_scores.csv` | Actual per-application/method TP/FP/FN, F1 and query counts. |
| `queries.json`, `queries.csv` | Cardinality questions, reference answers, predictions and backend sets. |
| `candidates.csv` | All 249 same-namespace pairs with source-derived name strata and evaluation labels. |
| `source_field_records.json` | 25 selector and 28 template-label source records. |
| `reference_edge_witnesses.json` | Evidence for 27 positive memberships; not independent human approval. |
| `confidence_folds.json` | Other-application fitting populations, strata and prevalence. |
| `confidence_predictions.csv` | Frozen held-out probabilities followed by scoring labels and Brier contributions. |
| `confidence_decisions.csv` | Per-pair threshold selection. |
| `summary.json` | Populations, per-application findings, pooled and equal-system Brier summaries. |

### Replay

Each of `annotated`, `raw_normalized`, and `raw_published_aliases` has `*_graphs.json`, `*_scores.csv`, `*_path_answers.csv`, and `*_paired.csv`.

The annotated mode is the main method in the paper. The raw modes are explicit alternatives for source-direction sensitivity. `annotation_records.json` retains upstream labels, text and line locations; `raw_records.json` retains JSON pointers/SVG titles. `direction_differences.json` lists edge-set differences, and `missing_records.json` lists the seven unavailable exports without scoring them as empty graphs.

### Edge-proposal calibration

Under `calibration/<mode>/`, `folds.json` records other-application training; `proposals.csv` records every proposed edge, stratum, confidence and correctness; `bins.json`/`.csv` record all bins, including empty ones; `thresholds.csv` and `selection_decisions.csv` retain acceptance decisions; `results.json` contains Brier, ECE, coverage, precision and reference-edge recall. `calibration/summary.json` combines the modes without merging their interpretations.

A probability here estimates a **positive proposal's correctness**. It is not confidence in a negative edge and not probability of source entailment.

### Evidence and execution

`evidence/evidence_index.csv` maps each manuscript item to inputs, algorithm and files. `calculated_findings.json` records current outcomes. `source_locator_ledger.json` contains retained YAML text excerpts. `review_footprint.json` counts review records without inventing reviewer hours. `coverage.json` lists generated artifacts and unmeasured activities.

`run.json` records the processor arguments and input-preservation checks. `logs/algorithm.log` and `.jsonl` hold execution events. The outer workflow creates `workflow.json`, `logs/`, `evidence_manifest.json`, and, when requested, `checks/`.

## Interpretation and exceptions

Undefined metrics stay null/N/A. Missing source files cause explicit failures. New data or labels define a new experiment. Source authenticity, human annotation independence and runtime security are not established by a checksum or a successful run.

One raw-direction .95 threshold statement in the manuscript is not reproduced under the recorded raw-alignment alternatives. Use their actual generated values and the release verification note rather than treating a passing test suite as proof of that statement.
