# ArchGraphBench

An evaluation method for checking whether a reconstructed architecture graph preserves the declared relationships, answers the selected architecture questions correctly, and makes claims supported by the available evidence.

**Release 4.0.0 — proofread submission candidate.** The manuscript binding is in `PAPER_VERSION.json`. This release covers diagnostics, Online Boutique, the four-application membership study, annotated archived-tool replay, and held-out edge-proposal calibration.

## Run on Windows

Extract into a new folder, for example `C:\AGB_Submission`. Open PowerShell there.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-plots.txt
.\.venv\Scripts\python.exe run_all_evidence.py --data data --out run_01 --demo --checks
```

Use Python 3.11 or newer. Do not merge this package with older releases. Choose a new output directory for each execution.

Open `run_01/results/EVIDENCE_README.md`, then the calculated `table_VII_boutique.csv`, `table_VIII_membership.csv`, `table_IX_replay.csv`, and `calibration/annotated/results.json`.

## Reference builder

```powershell
.\.venv\Scripts\python.exe build_reference.py --input data/public_case/source/kubernetes-manifests.yaml --out candidate_reference
```

To generate a Boutique reference candidate and use it in the complete workflow:

```powershell
.\.venv\Scripts\python.exe run_all_evidence.py --data data --reference-mode generated --out run_candidate --demo --checks
```

Automatic reference construction remains pending independent review. The other reference datasets stay unchanged.

## Read next

- `ArchGraphBench_End_to_End_Method_and_Run_Guide.md`: method, algorithms and run steps.
- `AGB_File_Reference.md`: input and output meanings.
- `DEMO_GUIDE.md`: live comments, tracing and pause controls.
- `PROVENANCE.md`: source origins and retained/transcribed-input qualifications.
- `validation/VERIFICATION.md`: actual execution checks and one unresolved manuscript sensitivity statement.

## Interpretation boundary

The annotated replay inherits source-study connection labels; it does not rerun Code2DFD/MicroDepGraph. No live LLM inference is part of the submission workflow. Manifest references share selector assumptions. None of these calculations establishes runtime-security enforcement.

The manuscript's raw-direction statement about accepting nothing at threshold 0.95 is **not reproduced** by the explicit raw-alignment variants in this release. Their actual results and conventions are retained; no labels or probabilities are adjusted to force agreement.
