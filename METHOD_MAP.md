# Method-to-code map — proofread submission candidate

| Paper location | Code | Inputs | Evidence |
|---|---|---|---|
| III–IV | `core.py` | Structured assertions, codebook, references and predictions | State judgments, graph metrics, divergence and acceptance decisions. |
| V–VI, Tables II/V/VI | `diagnostics.py` | Constructed-case parameters | Actual support records, perturbations, witnesses and metric calculations. |
| VII-A–C, Table VII | `boutique.py` | Retained Boutique YAML and selected reference | Full/masked graphs, eight-query records and scores. |
| VII-D/E, Table VIII | `backends.py`, `membership.py` | Four manifests and frozen membership lists | M1/MP/M2, 249 candidate pairs, 50 cardinality questions and held-out fitting. |
| VII-F, Table IX | `replay.py` | Source-study annotations, reference DFDs and raw projections | TP+FP primary graphs; FN excluded; directed closure, witnesses and raw sensitivity. |
| VII-G | `calibration.py` | Current paired-system positive proposals | LOAO group frequencies, probabilities, Brier, 10/5-bin ECE and acceptance. |
| VIII | `membership.py`, `evidence.py` | Current source inventories | Selector/label/witness review counts; no measured human time. |
| Figures 1–5 | `paper_figures.py` | Method layouts; computed populations for workflow illustration | Clearly labeled illustrations, not experimental observations. |
| Figure 6 | `diagnostics.py`, `paper_figures.py` | All 81 computed weight configurations | 42 unique points, category marker shapes and multiplicities. |

## Separate prediction targets

- Boutique compares supported-graph answers to a fixed graph and evidence-aware answers to a condition-specific support reference.
- Membership predicts presence/absence for **all** candidate Service/template pairs. Confidence is `max(p,1-p)` after a positive/negative decision.
- Proposal calibration estimates correctness of an edge **already proposed** by a tool. Accept when `c >= theta`; low c is not a negative-edge conclusion.
- Archived replay uses source-study connection annotations. It is not fresh recovery or independent validation of raw directions.

## Retained extensions

The Boutique reference builder remains separate from M1/M2 and outputs an unreviewed candidate. The structured-contract runner and legacy focused Bookinfo runner remain available, but are not additional experiments claimed by this manuscript.

## Known unresolved statement

The primary annotated replay and calibration reproduce the checked values. The raw-direction .95 acceptance statement does not reproduce under the recorded raw-name/alignment variants. See `validation/VERIFICATION.md`; do not silently change the interpretation to force a result.
