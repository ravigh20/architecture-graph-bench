# ArchGraphBench — live demonstration

Run from the package root after installing `requirements-plots.txt`.

## Start with Boutique

```powershell
.\.venv\Scripts\python.exe process.py --data data --study boutique --out demo_boutique --demo --pause
```

Press Enter at the major checkpoints. Show the source-field join, the resulting payment-path witness, the mask, and the distinction between M2's unknown answers and M2-CW's unsupported negatives.

## Demonstrate the new cross-system study

```powershell
.\.venv\Scripts\python.exe process.py --data data --study membership --out demo_membership --demo --trace --trace-limit 5
```

Show M1's missed Bookinfo version suffixes, MP's extra Sock Shop links, and M2's selector join. The fitted model trains on the other applications. Open `demo_membership/membership/confidence_folds.json` and `demo_membership/membership/confidence_predictions.csv`.

## Demonstrate annotated replay and calibration

```powershell
.\.venv\Scripts\python.exe process.py --data data --study calibration --out demo_calibration --demo
```

The calibration study automatically runs its replay prerequisite. Show source TP/FP/FN handling, the two ordering reversals, and the Spring Cloud Netflix F1 tie. Then show `calibration/annotated/folds.json`, `proposals.csv`, `bins.csv` and `thresholds.csv`.

Say: "These are recalculated architectural-path results from published interpreted connection records. The original tools have not been rerun."

## Generate the complete evidence

```powershell
.\.venv\Scripts\python.exe run_all_evidence.py --data data --out demo_all --demo --checks
```

Add `--reference-mode generated` to demonstrate candidate reference construction first. Add `--trace` for detailed decision events; `--trace-limit 0` removes event limits. Add `--step-delay 1` for automatic pacing. Logging does not supply metric values or change the scoring.

## Files to show

| File | Explanation |
|---|---|
| `results/table_VII_boutique.csv` | Relationship accuracy versus query/support outcomes. |
| `results/table_VIII_membership.csv` | Cross-system baseline and confidence-transfer results. |
| `results/table_IX_replay.csv` | Connection F1 versus path disagreement. |
| `results/calibration/annotated/thresholds.csv` | Precision, proposal coverage and reference-edge recall. |
| `results/logs/algorithm.log` | Actual execution stages and calculated values. |
| `results/logs/algorithm.jsonl` | Structured events with unabridged decision fields. |

## Do not overstate the run

A passed test suite is not independent ground truth. Generated references remain pending review, and runtime security is unmeasured. The raw-direction .95 threshold statement remains unresolved; show its actual output rather than repeat an unsupported zero-acceptance claim.
