# Final 24h Opportunity Analysis

> Baseline commit: `9daaa0c`
> Official Real E2E: Accuracy 0.6279 (27/43), Macro-F1 0.6743.

## 1. Remaining-error classification

| Category | Count | Claims |
|---|---:|---|
| A. Business evidence missing | 0 | None after the Business Evidence Layer recovery |
| B. Financial evidence missing | 4 | CLM-010, CLM-H05, CLM-H09, CLM-H11 |
| C. Ranking issue | 4 | CLM-003, CLM-005, CLM-014, CLM-018 |
| D. Verification issue | 7 | CLM-002, CLM-007, CLM-009, CLM-011, CLM-015, CLM-026, CLM-H02 |
| E. Benchmark limitation | 1 | CLM-025 |

## 2. Case-by-case opportunities

| Claim | Gold -> current | Category | Current limiting stage | 24h opportunity |
|---|---|---|---|---|
| CLM-002 | REFUTED -> SUPPORTED | D | Compound equality is reduced to the matching revenue value | High-risk decomposition; do not select |
| CLM-003 | SUPPORTED -> INSUFFICIENT | C | Correct attributable-profit fact exists, but its complete summary row is not selected | Recover the primary summary row and its period/title context |
| CLM-005 | SUPPORTED -> INSUFFICIENT | C | Derived gross-margin components remain outside Top10 | Ranking experiments previously regressed; do not select |
| CLM-007 | SUPPORTED -> REFUTED | D | Quarterly revenue evidence is present but a mismatched metric row controls the verdict | Needs broader selector/verification changes |
| CLM-009 | REFUTED -> INSUFFICIENT | D | Q2 standalone derivation is not selected as a complete component set | Needs quarter decomposition |
| CLM-010 | REFUTED -> INSUFFICIENT | B | Q2/Q1 attributable-profit components are not reconstructed | Missing multi-period evidence |
| CLM-011 | SUPPORTED -> INSUFFICIENT | D | Gate treats the default `consolidated` placeholder as conflicting with attributable-profit evidence | Normalize effective scope from the metric before Gate evaluation |
| CLM-014 | SUPPORTED -> INSUFFICIENT | C | Correct cash-flow row exists outside Top10 | Ranking-only change is comparatively risky |
| CLM-015 | REFUTED -> INSUFFICIENT | D | H1/Q1 period decomposition is incomplete | Needs compound period reasoning |
| CLM-018 | REFUTED -> INSUFFICIENT | C | Correct cash-flow row exists outside Top10 | Ranking-only change is comparatively risky |
| CLM-025 | UNABLE -> PARTIALLY_SUPPORTED | E | Q4 standalone threshold is not derivable from supplied periods | Benchmark capability boundary |
| CLM-026 | SUPPORTED -> REFUTED | D | Gate/core use inconsistent scope semantics for deducted profit | Normalize effective adjusted scope and preserve the summary row |
| CLM-H02 | SUPPORTED -> INSUFFICIENT | D | Exact evidence is Top1, but Gate rejects its attributable scope | Normalize effective parent-attributable scope |
| CLM-H05 | REFUTED -> INSUFFICIENT | B | OCF growth components are not represented as a usable fact | Missing derived-growth evidence |
| CLM-H09 | REFUTED -> INSUFFICIENT | B | Net-assets growth components are not represented as a usable fact | Missing derived-growth evidence |
| CLM-H11 | SUPPORTED -> INSUFFICIENT | B | Metric label and value are split across adjacent summary-table blocks | Reconstruct the exact primary summary window |

## 3. Selected single direction

**Evidence Pipeline Bug: attributable-profit scope and summary-window alignment.**

The Gate currently reads the raw `scope=consolidated` placeholder, while the core verifier already infers `parent_attributable` for attributable-profit metrics and `adjusted` for deducted-profit metrics. Correct evidence containing “归属于上市公司股东” or “扣除非经常性损益” is therefore rejected before the verifier can apply its existing metric semantics.

The same metric family also loses information when a summary-table label and its numeric row are separate blocks. The selected fix will:

1. Use the same metric-derived effective scope in Gate and core verification.
2. Reconstruct a focused primary-summary window only for `net_profit_attributable` and `deducted_net_profit`.
3. Require an exact company period, an exact metric marker, and a current-value match after unit conversion and disclosed rounding.
4. Promote that complete candidate without changing reranker weights or removing existing candidates.

The change is expected to correct CLM-003, CLM-011, CLM-026, CLM-H02, and CLM-H11. It is bounded to two metric families, does not use claim IDs or block IDs, and leaves all business evidence and unrelated financial metrics unchanged.

## 4. Implemented result

| Metric | Before (`9daaa0c`) | After | Delta |
|---|---:|---:|---:|
| Accuracy | 0.6279 (27/43) | **0.7442 (32/43)** | **+0.1163** |
| Macro-F1 | 0.6743 | **0.7264** | **+0.0521** |
| Coverage | 0.6512 | **0.7442** | **+0.0930** |
| Abstentions | 15 | **11** | -4 |

Improved cases: CLM-003, CLM-011, CLM-026, CLM-H02, and CLM-H11. No previously correct case regressed.

Verification record:

- Focused scope/summary and Business Evidence regression suite: 19 passed.
- Full backend suite: 912 passed.
- Full official 43-case evaluation snapshot: `backend/artifacts/e2e/final_24h_after.json`.

## 5. Remaining limitations

Eleven errors remain:

- Compound verification: CLM-002 and CLM-007.
- Quarterly/period decomposition: CLM-009, CLM-010, and CLM-015.
- Financial ranking or derived-component coverage: CLM-005, CLM-014, CLM-018, CLM-H05, and CLM-H09.
- Benchmark capability boundary: CLM-025.
