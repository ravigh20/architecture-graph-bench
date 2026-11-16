# ArchGraphBench submission-candidate release — verification

## Scope and verdict

This release implements `ArchGraphBench_Proofread_Submission_Candidate(1).pdf` (SHA-256 `afa669b35ccb1e40b23d74c863ca7c72f4ac75838babfd80c504914323997f6a`). The deterministic diagnostics and Boutique calculations are preserved. The main workflow adds four-application membership, source-study-annotated replay, and held-out positive-proposal calibration.

**The main numerical tables V–IX and annotated-calibration quantities reproduce at the manuscript's displayed precision. One raw-direction threshold statement does not reproduce under the explicit input/alignment conventions tested here.** Successful workflow completion and unit tests do not certify that unresolved statement.

## Actual executions

- Environment: Linux, Python 3.13.5. Windows commands were not executed here.
- Complete generated-reference workflow: completed with plots, live demo logging and tests.
- Historical-reference workflow: completed with plots.
- Tests: **216 passed; zero failures, errors or skips**. The 176 previous implementation tests remain, with 40 new submission-method tests. These are newly executed current tests, not evidence that the paper's historical test executions were reconstructed.
- Clean-room execution: only current Python processing code, `archgraphbench/`, profiles and data were available. No PDF, old score files, documentation, test suite or prior outputs were present. **All 45 calculated CSV files were byte-identical to the corresponding historical-reference run.** Runtime timestamps, environment metadata and local paths are not part of that claim.
- Evidence generation: **27 output groups**, including descriptive tables and method illustrations, were written. All **202 distinct YAML source locators** resolved. Annotated replay records have their own source-URL/text/line audit.
- Input preservation: all 28 original source/reference/metadata files from the earlier demo data folder are unchanged. The experiment configuration and input inventory were intentionally updated. Seventy-four replay-related files were added, yielding 104 data files. No source configuration or reference label was edited to obtain a score. Experiment execution left all these inputs unchanged.

## Selected newly calculated values

| Quantity | Result |
|---|---:|
| Membership candidate pairs / reference edges / queries | 249 / 27 / 50 |
| Bookinfo M1 / MP / M2 wrong answers | 5 / 0 / 0 of 8 |
| Sock Shop MP false links / wrong answers | 8 / 8 |
| Membership pooled fitted / hard / fixed-.9 Brier | 0.0452853594 / 0.0240963855 / 0.0292771084 |
| Membership pooled empirical training-prevalence Brier | 0.1200863296 |
| External replay applications / records / path evaluations | 17 / 27 / 3,150 |
| Paired applications / queries per method | 10 / 1,164 |
| Records / applications with path errors | 23 / 15 |
| Annotated paired ranking reversals | 2 |
| Spring Cloud Netflix F1 tie | 0.9454545455 for both |
| Spring Cloud Netflix wrong path answers | 8 versus 16 of 90 |
| Annotated positive proposals / correct / reference edges | 244 / 225 / 245 |
| Fitted / fixed-.9 proposal Brier | 0.0727986137 / 0.0722950820 |
| Ten-bin fitted / fixed-.9 ECE | 0.0542753691 / 0.0221311475 |
| Five-bin fitted / fixed-.9 ECE | 0.0101908305 / 0.0221311475 |
| Fitted threshold .8: correct / accepted | 215 / 234 |
| Fitted threshold .95: correct / accepted | 113 / 113 across all ten applications |
| Threshold .95: proposal coverage / reference-edge recall | 46.3115% / 46.1224% |
| Diagnostic ranking counts A / B / tie | 66 / 9 / 6 |
| Distinct Figure 6 coordinates | 42 |

The full Boutique table retains F1 54/55 for full M1 and masked M2/M2-CW, and two unsupported masked negative answers for M2-CW. Full M2 retains 28 scoped edges. Numerical calculations use the input graphs and records; manuscript values are testing assertions, not production processing inputs.

## Unresolved manuscript statement: raw-direction selection

Section VII-G says: **“Raw-direction sensitivity accepts nothing at .95.”** With the retained raw outputs, a fresh leave-one-application-out refit produces:

| Raw interpretation | Proposal population | Accepted at .95 | Correct among accepted | Applications represented |
|---|---:|---:|---:|---:|
| Spelling normalization only (`raw_normalized`) | 313 | 38 | 22 | 1 |
| Published component aliases (`raw_published_aliases`) | 295 | 32 | 23 | 1 |

Both keep raw edge directions, self-loops and extra endpoints. The spelling-only mode differs from the annotated graph in 12 of 27 records, matching the manuscript's difference count; both raw modes produce zero paired ranking reversals. The fixed-.9 baseline accepts zero proposals at .95 in every mode, but that is not the fitted raw-sensitivity claim.

The discrepancy is retained in `calibration/<mode>/proposals.csv`, `folds.json`, `thresholds.csv`, and `results.json`. It may depend on the original raw snapshot, endpoint-alignment convention, proposal eligibility or exact sensitivity fitting procedure. Those choices cannot be inferred uniquely from the manuscript. This release does not alter records or truncate predictions to force zero acceptance. Clarify the original procedure or revise that statement after checking its original evidence.

## Source acquisition and independence

The primary connection projection contains 650 source annotation rows across 27 tool/application records. TP and identified FP connections enter predictions; FN records remain audit information and are not inserted as predicted edges. External reference files are used separately. Labels and directions inherit the source study's interpretation, as the manuscript specifies.

The connection sections were transcribed from browser-retrieved v1.1 source text because the full archive bytes could not be obtained in this execution environment. Each record preserves the source URL/version, original text, label and one-based line locator. This is a transparent source projection, **not a byte-authenticated archive download**. Retained raw predictions and component mappings come from the earlier package's source snapshot. The historical Boutique manifest also retains its documented transcription qualification.

`tools/verify_replay_sources.py` can compare this projection against the full, locally extracted source archive or freshly retrieved source files. A successful future source-file comparison would verify acquisition consistency, not the scientific correctness of the original annotations. This optional utility has not completed live upstream acquisition here.

No original Code2DFD/MicroDepGraph execution, new LLM inference, independent human adjudication, reviewer timing, source-entailment validation or runtime security evaluation was performed. Generated reference candidates retain pending-review status. The optional legacy Bookinfo response re-scoring is outside the submission's default workload.

## Inspection paths

- `tests.log` and `test_results.json`: actual current test results.
- `clean_room_repeatability.json`: per-file equality for all 45 CSV outputs.
- `example_algorithm.log` and `.jsonl`: actual live execution events from the completed run.
- `verification.json`: machine-readable environment, data-preservation, coverage and discrepancy records.
- In an evidence run, `results/evidence/evidence_index.csv`: mappings to the input, algorithm and output groups.
