# Final Error Analysis

> Baseline: official Real E2E Top3/Gate, 43 claims.
> Accuracy 0.5116 (22/43), Macro-F1 0.5787, Coverage 0.6512.
> Analysis sources: baseline output, gold evidence, top10/top50 ranks, fact alignment, and production trace.

## 1. Classification summary

| Class | Count | Definition |
|---|---:|---|
| A. Retrieval failure | 10 | Correct gold block/fact absent from the available retrieval pool |
| B. Ranking failure | 4 | Correct block/fact exists in the wider pool but is outside Top10 |
| C. Evidence pipeline failure | 0 primary cases | Official adapter drops facts globally, but enabling them was not sufficient to make an individual baseline error correct |
| D. Verification/sufficiency failure | 6 | Relevant evidence exists in Top10 or unrelated numeric evidence receives a non-abstaining verdict |
| E. Benchmark capability boundary | 1 | Future-quarter threshold cannot be determined from the available reports |

Retrieval plus ranking accounts for 14/21 baseline errors. Financial expansion had already been tested repeatedly without stable gains. The business cohort offered a bounded, independently verifiable five-case gain without modifying financial retrieval.

## 2. All baseline wrong cases

| Claim | Gold -> Pred | Class | Evidence finding / root cause | Final sprint result |
|---|---|---|---|---|
| CLM-002 | REFUTED -> SUPPORTED | D | Gold block and aligned fact are Top10; compound equality claim is over-supported | Unchanged |
| CLM-003 | SUPPORTED -> INSUFFICIENT | B | Gold block is around rank 24; not selected into Top10 | Unchanged |
| CLM-005 | SUPPORTED -> INSUFFICIENT | B | Correct derived-margin fact exists in Top50 but not Top10 | Unchanged |
| CLM-007 | SUPPORTED -> REFUTED | D | Correct quarterly fact is Top10; block verifier selects a mismatched metric row | Unchanged |
| CLM-009 | REFUTED -> INSUFFICIENT | D | Correct fact is Top10 but outside selected evidence; quarter subtraction remains unresolved | Unchanged |
| CLM-010 | REFUTED -> INSUFFICIENT | A | Required Q2 and Q1 attributable-profit components are not reconstructed | Unchanged |
| CLM-011 | SUPPORTED -> INSUFFICIENT | A | Correct Q1 attributable-profit fact is absent | Unchanged |
| CLM-014 | SUPPORTED -> INSUFFICIENT | B | Correct cash-flow gold block exists in Top50 but not Top10 | Unchanged |
| CLM-015 | REFUTED -> INSUFFICIENT | D | Relevant growth fact is present, but period/decomposition verification has no usable growth pair | Unchanged |
| CLM-018 | REFUTED -> INSUFFICIENT | B | Correct cash-flow block exists in Top50 but not Top10 | Unchanged |
| CLM-019 | SUPPORTED -> INSUFFICIENT | A | OBM strategy disclosure exists in MD&A but financial candidates occupy Top10 | **Fixed: SUPPORTED** |
| CLM-022 | INSUFFICIENT -> SUPPORTED | D | Unrelated “20%” air-conditioner evidence is mistaken for robot-margin industry comparison | **Fixed: INSUFFICIENT** |
| CLM-025 | UNABLE -> PARTIALLY_SUPPORTED | E | Q4 standalone threshold is not derivable from the supplied reporting periods | Unchanged |
| CLM-026 | SUPPORTED -> REFUTED | A | Correct H1 deducted-profit disclosure is absent from selected evidence | Unchanged |
| CLM-H02 | SUPPORTED -> INSUFFICIENT | A | Correct attributable-profit fact is absent | Unchanged |
| CLM-H05 | REFUTED -> INSUFFICIENT | A | OCF growth components are absent | Unchanged |
| CLM-H09 | REFUTED -> INSUFFICIENT | A | Net-assets growth components are absent | Unchanged |
| CLM-H10 | REFUTED -> INSUFFICIENT | A | Cover date and report title are split and never reconstructed together | **Fixed: REFUTED** |
| CLM-H11 | SUPPORTED -> INSUFFICIENT | A | Correct deducted-profit fact is absent | Unchanged |
| CLM-H12 | SUPPORTED -> PARTIALLY_SUPPORTED | A | Stock code and exchange are adjacent blocks but only partial listing evidence reaches verification | **Fixed: SUPPORTED** |
| CLM-H17 | INSUFFICIENT -> SUPPORTED | D | Unrelated large “元” values satisfy a threshold without product-price semantics | **Fixed: INSUFFICIENT** |

## 3. Highest-impact fix decision

The Business Evidence Layer was selected because one isolated routing policy addresses both sides of the same defect:

1. Promote complete business disclosures that already exist in the document store.
2. Suppress numeric coincidences that lack the required business concepts.
3. Leave the financial claim path byte-for-byte on its existing retrieval pipeline.

It fixes five baseline errors, exceeding the 5% improvement threshold, without changing gold, evaluation, reranker weights, Gate, Selector, or verdict policy.

## 4. Before / after

| Metric | Before | After run 1 | After run 2 | Delta |
|---|---:|---:|---:|---:|
| Accuracy | 0.5116 | **0.6279** | **0.6279** | **+0.1163** |
| Macro-F1 | 0.5787 | **0.6743** | **0.6743** | **+0.0956** |
| Coverage | 0.6512 | **0.6512** | **0.6512** | 0.0000 |
| Correct | 22/43 | **27/43** | **27/43** | +5 |

The two after-runs produced identical verdicts for all 43 cases. Sixteen errors remain. They are dominated by quarterly/growth financial evidence coverage, fact ranking, and compound-claim verification; none is addressed by this single recovery fix.
