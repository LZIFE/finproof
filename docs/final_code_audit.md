# Final Code Audit

> Audit date: 2026-08-07
> Scope: `backend/app` retrieval, evidence pipeline, gate, selector, verification, and official 43-case evaluation.

## 1. Current call chains

### Production path

```text
Claim (dict / CanonicalClaim)
  -> route_claim() -> ClaimRoutingResult
  -> verify_claim_production()
  -> verify_real_e2e()
  -> fetch_evidence()
  -> retrieve_for_claim()
       -> Business Evidence Layer, for strict narrative/business claims
       OR
       -> Hybrid Retrieval + Evidence Window + Financial Evidence Index
          + Fact First Retrieval + Reranker, for financial claims
  -> verify_evidence_set()
  -> attach_fact_verifications()
  -> Evidence Gate -> list[EvidenceQualityResult]
  -> Evidence Selector -> EvidenceBundle (list[dict])
  -> core_verify()
  -> VerificationResult / Verdict
```

### Official Real E2E path

`backend/scripts/phase23_11_development_e2e.py` loads the same 43 canonical claims and calls `retrieve_for_claim(top_k=10)`, then manually adapts candidates before `verify_evidence_set`.

```text
CanonicalClaim
  -> route_claim()
  -> retrieve_for_claim(top_k=10)
  -> manual candidate adapter
  -> verify_evidence_set()
  -> Gate -> Selector(max 1/3) -> core_verify()
  -> metrics
```

The official adapter retains block text/page/document identifiers but does not retain `financial_fact`. Therefore official evaluator fact usage is 0 by construction. This audit does not change the evaluator or its metric definitions.

### Legacy verification path

`verify_claim() -> fetch_evidence() -> _select_verifier() -> core_verify()` remains for compatibility. `_select_verifier()` reconstructs a reduced evidence list and also omits `financial_fact`; production and official shared verification use `verify_evidence_set()` instead.

## 2. Data structure flow

| Stage | Structure | Important fields |
|---|---|---|
| Evaluation input | `CanonicalClaim` | claim/company/text/type/verdict/period/metric/value/unit/scope/gold evidence ids |
| Routing | `ClaimRoutingResult` | route, metric_code, value, period, unit, scope, required evidence fields |
| Financial retrieval | candidate `dict` | block/page/document, scores, block text, financial object/fact, retrieval method |
| Business retrieval | candidate `dict` | `evidence_text`, minimal `source_block_ids`, `business_match_score`, standard scores, no financial fact |
| Gate | `EvidenceQualityResult` | three-state entity/metric/period/unit/scope matches, quality, accepted, text, financial fact |
| Selector | EvidenceBundle `list[dict]` | evidence id, verification text, quality, financial fact |
| Verification | `VerificationResult` | status, confidence, type, evidence ids, rule id, reason, integration trace |

No typed `EvidenceBundle` class exists; it is a list of dictionaries built by `evidence_selector.select()`.

## 3. `financial_fact` lifecycle

### Generation

1. `fact_retrieve_candidates()` reconstructs cross-block financial evidence objects.
2. `merge_evidence_index_candidates()` unions Financial Evidence Index source blocks into the candidate pool.
3. `attach_financial_facts()` validates block/fact metric compatibility and adds the normalized `financial_fact` object.

The fact schema contains metric/code, current and previous values, growth, unit, period(s), table type, and source blocks.

### Transmission

```text
retrieve_for_claim
  -> fetch_evidence
  -> attach_fact_verifications
  -> EvidenceQualityResult.financial_fact
  -> Selector evidence_bundle[].financial_fact
  -> core_verify
```

The production path preserves this chain. The official evaluation adapter and legacy `_select_verifier()` are the two observed field-loss boundaries.

### Consumption

- `fact_verification_path` attaches metric/value/previous-value/growth/period diagnostics.
- `financial_fact_decision_policy.best_fact_authority()` consumes the fact in `core_verify()`.
- Only high-quality, matching facts can issue a SUPPORTED/REFUTED authority decision; otherwise verification falls back to block text.

## 4. Final recovery change

The dominant remaining business failures were not missing documents. Their correct disclosures existed in source blocks but competed against financially biased candidates:

- OBM strategy disclosure existed on the management-discussion page.
- Publication date existed on the annual-report cover, split from the report title.
- Listing code and exchange existed in adjacent company-information blocks.
- Unsupported robot-margin and selling-price claims were incorrectly driven by unrelated matching numbers.

`business_evidence.retrieve_business_evidence()` now handles only narrative business claims and non-financial comparisons. It reconstructs the smallest complete disclosure window and returns no candidate when required business concepts/value/unit are not jointly grounded. Candidates still pass through the unchanged Gate, Selector, and verifier.

Financial claims never enter this branch, so Financial Evidence Index, fact extraction, reranking, and verification behavior remain unchanged.

## 5. Reproduced metrics

| Path | Accuracy | Macro-F1 | Coverage | Fact authority usage |
|---|---:|---:|---:|---:|
| Official baseline, Top3/Gate | 0.5116 | 0.5787 | 0.6512 | 0/43 (adapter omits facts) |
| Production baseline, top10 | 0.4884 | 0.4787 | 0.7907 | 15/43 (34.9%) |
| Official after Business Evidence Layer, run 1 | **0.6279** | **0.6743** | **0.6512** | 0/43 by unchanged evaluator contract |
| Official after Business Evidence Layer, run 2 | **0.6279** | **0.6743** | **0.6512** | 0/43 by unchanged evaluator contract |
| Production after Business Evidence Layer, top10 | **0.6047** | **0.5651** | **0.7907** | 15/43 (34.9%) |

The official improvement is +0.1163 Accuracy, +0.0956 Macro-F1, with unchanged Coverage. Both official runs produced the same verdict for every one of the 43 claims. Production accuracy improved by +0.1163 and Macro-F1 by +0.0864; coverage and fact-authority consumption were unchanged. After routing six business claims away from the financial path, 37/43 production selector bundles still contain a `financial_fact`, and 15/43 reach the fact-authority decision policy.

## 6. Verification record

- Focused retrieval, Gate, Selector, verification, and Phase 23.11 integration suite: 89 passed.
- Full backend suite: 909 passed.
- Official snapshots: `backend/artifacts/e2e/final_recovery_baseline.json`, `final_recovery_after_run1.json`, and `final_recovery_after_run2.json`.
- Production trace snapshot: `backend/artifacts/e2e/final_recovery_production_after.json`.
- The two after snapshots are byte-identical after adding the same audit metadata.
