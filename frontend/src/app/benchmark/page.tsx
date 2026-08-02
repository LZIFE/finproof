"use client";

import { useState } from "react";

type ErrorDistribution = Record<string, number>;

type Metrics = {
  total_cases: number;
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  evidence_coverage: number;
  risk_detection_rate: number;
  recall_by_category: Record<string, number>;
};

type ModelResult = {
  model: string;
  metrics: Metrics;
  case_results: {
    case_id: string;
    model: string;
    predicted_result: string;
    predicted_risk_score: number;
    predicted_risk_type: string;
    detected_error: boolean;
    evidence_coverage: number;
    response_text: string;
    error: string;
  }[];
};

type Report = {
  id: number;
  run_id: string;
  dataset_name: string;
  total_cases: number;
  models: string[];
  model_results: ModelResult[];
  error_distribution: ErrorDistribution;
  comparison: {
    finproof: Metrics;
    baseline: Metrics;
    accuracy_gain: number;
    precision_gain: number;
    recall_gain: number;
    f1_gain: number;
    evidence_coverage_gain: number;
    risk_detection_rate_gain: number;
  };
  created_at: string;
};

const ERROR_LABEL: Record<string, string> = {
  FINANCIAL_ERROR: "财务数据错误",
  PERIOD_ERROR: "期间错误",
  GROWTH_ERROR: "增长逻辑错误",
  SEMANTIC_OVERSTATEMENT: "语义夸大",
  COMPETITIVE_CLAIM: "竞争优势主张",
  CAUSAL_ERROR: "因果归因错误",
};

const METRIC_LABEL: Record<string, string> = {
  accuracy: "Accuracy 准确率",
  precision: "Precision 精确率",
  recall: "Recall 召回率",
  f1: "F1",
  evidence_coverage: "Evidence Coverage 证据覆盖率",
  risk_detection_rate: "Risk Detection Rate 风险检测率",
};

const METRIC_KEYS = ["accuracy", "precision", "recall", "f1", "evidence_coverage", "risk_detection_rate"];

function fmtPct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export default function BenchmarkPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [datasetOverview, setDatasetOverview] = useState<{ count: number; error_distribution: ErrorDistribution; dataset_name: string; models: string[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDataset = async () => {
    setError(null);
    try {
      const resp = await fetch("/api/v1/benchmark/dataset");
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setDatasetOverview(body);
    } catch (e) {
      setError(`查询 Dataset 失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const run = async () => {
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const resp = await fetch("/api/v1/benchmark/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset_name: null, models: null, use_seed: true }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setReport(body);
    } catch (e) {
      setError(`评测失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const finproof = report?.model_results.find((m) => m.model === "FINPROOF");
  const baseline = report?.model_results.find((m) => m.model === "BASELINE_LLM");

  return (
    <main className="page">
      <h1>金融 AI 可信度评测基准（Phase 11 · Financial AIBenchmark System）</h1>
      <p>
        评估 AI 生成金融内容的错误检测能力：FinProof vs Baseline LLM。
        <b> 不修改已有核心模块；Benchmark 作为新增层。</b>
      </p>

      <div className="form-row">
        <button onClick={fetchDataset}>查询 Dataset</button>
        <button onClick={run} disabled={loading}>
          {loading ? "评测中…" : "运行评测（50 条案例）"}
        </button>
      </div>
      {error && <p className="bad">{error}</p>}

      {/* ① Dataset 数量 + 错误分布 */}
      <h2>① Dataset 数量与错误分布</h2>
      {datasetOverview ? (
        <div className="semantic-card">
          <p>
            <b>Dataset:</b> {datasetOverview.dataset_name} · <b>案例数:</b> {datasetOverview.count} ·{" "}
            <b>模型:</b> {datasetOverview.models.join(" vs ")}
          </p>
          <h4>Error Distribution（错误类型分布）</h4>
          <ul>
            {Object.entries(datasetOverview.error_distribution).map(([cat, n]) => (
              <li key={cat}>
                <b>{ERROR_LABEL[cat] || cat}</b>：{n} 条
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted">点击"查询 Dataset"查看预置案例概况。</p>
      )}

      {/* ② Evaluation Metrics（FinProof vs Baseline） */}
      <h2>② Evaluation Metrics（评测指标）</h2>
      {report && finproof && baseline ? (
        <div>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>指标</th>
                <th style={{ textAlign: "right", borderBottom: "1px solid #ccc" }}>FinProof</th>
                <th style={{ textAlign: "right", borderBottom: "1px solid #ccc" }}>Baseline LLM</th>
                <th style={{ textAlign: "right", borderBottom: "1px solid #ccc" }}>增益</th>
              </tr>
            </thead>
            <tbody>
              {METRIC_KEYS.map((k) => {
                const fv = finproof.metrics[k as keyof Metrics] as number;
                const bv = baseline.metrics[k as keyof Metrics] as number;
                const gain = report.comparison[`${k}_gain` as keyof typeof report.comparison] as number;
                return (
                  <tr key={k}>
                    <td style={{ borderBottom: "1px solid #eee" }}>{METRIC_LABEL[k]}</td>
                    <td style={{ textAlign: "right", borderBottom: "1px solid #eee" }}>
                      <strong>{fmtPct(fv)}</strong>
                    </td>
                    <td style={{ textAlign: "right", borderBottom: "1px solid #eee" }}>{fmtPct(bv)}</td>
                    <td style={{ textAlign: "right", borderBottom: "1px solid #eee", color: gain > 0 ? "green" : gain < 0 ? "red" : "#666" }}>
                      {gain > 0 ? "+" : ""}
                      {fmtPct(gain)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted">Total cases: {report.total_cases}</p>

          <h4>分错误类别召回率（Recall by Category）</h4>
          <div className="semantic-card">
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>错误类型</th>
                  <th style={{ textAlign: "right", borderBottom: "1px solid #ccc" }}>FinProof Recall</th>
                  <th style={{ textAlign: "right", borderBottom: "1px solid #ccc" }}>Baseline Recall</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(finproof.metrics.recall_by_category).map((cat) => {
                  const fr = finproof.metrics.recall_by_category[cat] ?? 0;
                  const br = baseline.metrics.recall_by_category[cat] ?? 0;
                  return (
                    <tr key={cat}>
                      <td style={{ borderBottom: "1px solid #eee" }}>{ERROR_LABEL[cat] || cat}</td>
                      <td style={{ textAlign: "right", borderBottom: "1px solid #eee" }}>
                        <strong>{fmtPct(fr)}</strong>
                      </td>
                      <td style={{ textAlign: "right", borderBottom: "1px solid #eee" }}>{fmtPct(br)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <p className="muted">点击"运行评测"查看指标对比。</p>
      )}

      {/* ③ Model Comparison（模型对比摘要） */}
      <h2>③ Model Comparison（模型对比摘要）</h2>
      {report && report.comparison ? (
        <div className={`verdict-card ${report.comparison.f1_gain >= 0 ? "verdict-refuted" : "verdict-supported"}`}>
          <h3>
            FinProof vs Baseline LLM — F1 增益 <strong>{fmtPct(report.comparison.f1_gain)}</strong>
          </h3>
          <p>
            FinProof 在错误检测上召回率 <strong>{fmtPct(finproof?.metrics.recall ?? 0)}</strong>，对比 Baseline{" "}
            {fmtPct(baseline?.metrics.recall ?? 0)}，增益{" "}
            <strong>{fmtPct(report.comparison.recall_gain)}</strong>。
          </p>
          <p>
            风险检测率：FinProof <strong>{fmtPct(finproof?.metrics.risk_detection_rate ?? 0)}</strong> vs Baseline{" "}
            {fmtPct(baseline?.metrics.risk_detection_rate ?? 0)}。
          </p>
          <p className="muted">
            结论：FinProof 通过证据覆盖 + 风险口径 + 语义/增长/竞争/期间/因果多维检测，发现 AI 金融内容幻觉能力显著优于 Baseline。
          </p>
        </div>
      ) : (
        <p className="muted">运行评测后查看对比摘要。</p>
      )}

      {/* ④ 逐案例结果摘录 */}
      <h2>④ 逐案例结果摘录（FinProof 检测 AI 幻觉）</h2>
      {report && finproof ? (
        <div>
          {finproof.case_results
            .filter((c) => c.detected_error)
            .slice(0, 10)
            .map((c) => (
              <div key={c.case_id} className="verdict-card verdict-refuted">
                <h4>
                  {c.case_id} — <strong>{c.predicted_risk_type}</strong> {c.predicted_risk_score}
                </h4>
                <p>预测结论：{c.predicted_result}</p>
                <p className="muted">证据覆盖：{(c.evidence_coverage * 100).toFixed(0)}%</p>
                <p className="muted" style={{ fontSize: "0.85em" }}>
                  {c.response_text}
                </p>
              </div>
            ))}
          {finproof.case_results.filter((c) => c.detected_error).length === 0 && (
            <p className="muted">无检测到的错误案例。</p>
          )}
        </div>
      ) : (
        <p className="muted">运行评测后查看逐案例结果。</p>
      )}
    </main>
  );
}
