"use client";

import { useState } from "react";

type FailureCase = {
  case_id: string;
  source: string;
  pattern: string;
  company?: string;
  claim: string;
  error_detail?: string;
  evidence_count?: number;
  confidence?: number;
};

type FailurePattern = {
  pattern: string;
  label?: string;
  failure_count: number;
  failure_rate: number;
  affected_category: string;
  example_cases: FailureCase[];
  root_cause: string;
  suggested_improvement: string;
};

type TrendPoint = {
  label: string;
  score: number;
  samples: number;
  timestamp?: string;
};

type ReliabilityTrend = {
  points: TrendPoint[];
  direction: string; // improving / declining / stable
  delta: number;
};

type ReliabilityReport = {
  report_id: string;
  total_cases: number;
  total_failures: number;
  overall_failure_rate: number;
  patterns: FailurePattern[];
  trend: ReliabilityTrend;
  sources_analyzed: string[];
  summary: string;
  suggested_improvements: string[];
  created_at?: string;
  pattern_labels?: Record<string, string>;
  source_labels?: Record<string, string>;
};

const PATTERN_COLOR: Record<string, string> = {
  NUMERIC_ERROR: "#f87171",
  PERIOD_CONFUSION: "#fbbf24",
  UNSUPPORTED_CLAIM: "#a78bfa",
  EVIDENCE_MISSING: "#38bdf8",
  LOGICAL_GAP: "#4ade80",
};

const DIRECTION_LABEL: Record<string, string> = {
  improving: "改善中 ↑",
  declining: "下降中 ↓",
  stable: "稳定 →",
};

const DIRECTION_COLOR: Record<string, string> = {
  improving: "#4ade80",
  declining: "#f87171",
  stable: "#fbbf24",
};

export default function ReliabilityPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReliabilityReport | null>(null);

  const analyze = async () => {
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const resp = await fetch("/api/v1/reliability/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 200 }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setReport(body);
    } catch (e) {
      setError(`分析失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const patternLabels = report?.pattern_labels || {};
  const sourceLabels = report?.source_labels || {};
  const sources = report?.sources_analyzed || [];
  const patterns = report?.patterns || [];
  const maxCount = Math.max(1, ...patterns.map((p) => p.failure_count));

  return (
    <main className="page">
      <h1>AI Reliability Improvement Center（Phase 23）</h1>
      <p className="muted">
        基于已有 Benchmark / Red Team / Arena 结果，分析失败模式并生成改进建议。
        <strong> 不修改模型、不训练模型</strong>，仅分析失败模式。保持 Evidence First；不输出投资建议。
      </p>

      {/* 启动分析 */}
      <h2>① 启动可靠性分析</h2>
      <div className="card">
        <button onClick={analyze} disabled={loading} style={{ fontSize: "1.05em", padding: "8px 24px" }}>
          {loading ? "分析中…" : "▶ Analyze Reliability"}
        </button>
        {error && <p className="bad" style={{ marginTop: 8 }}>{error}</p>}
        {report && (
          <p className="muted" style={{ marginTop: 8, fontSize: "0.85em" }}>
            report <strong>{report.report_id}</strong> · {report.total_cases} 案例 · {report.total_failures} 失败 · overall rate {(report.overall_failure_rate * 100).toFixed(1)}% · 生成于 {report.created_at}
          </p>
        )}
      </div>

      {report && (
        <>
          {/* 概要 */}
          <h2>② 分析概要</h2>
          <div className="semantic-card" style={{ marginBottom: 12 }}>
            <p style={{ margin: "2px 0" }}>{report.summary}</p>
          </div>

          {/* Failure Distribution */}
          <h2>③ Failure Distribution（5 类失败模式）</h2>
          <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.9em" }}>
            {patterns.length === 0 ? (
              <p className="muted">无失败模式。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {patterns.map((p) => {
                  const color = PATTERN_COLOR[p.pattern] || "#64748b";
                  const pct = (p.failure_count / maxCount) * 100;
                  return (
                    <div key={p.pattern} className="verdict-card" style={{ borderLeftColor: color, marginBottom: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <strong style={{ color }}>
                          {p.pattern} · {patternLabels[p.pattern] || p.pattern}
                        </strong>
                        <span style={{ fontSize: "0.85em" }}>
                          <strong>{p.failure_count}</strong> 次 · rate {(p.failure_rate * 100).toFixed(1)}% · 来源 {p.affected_category || "-"}
                        </span>
                      </div>
                      <div style={{ height: 8, background: "#1e293b", borderRadius: 4, overflow: "hidden", marginBottom: 6 }}>
                        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.4s" }} />
                      </div>
                      <p className="muted" style={{ fontSize: "0.85em", margin: "2px 0" }}>
                        <strong>根因：</strong>{p.root_cause}
                      </p>
                      <p style={{ fontSize: "0.85em", margin: "2px 0" }}>
                        <strong>改进建议：</strong>{p.suggested_improvement}
                      </p>
                      {p.example_cases.length > 0 && (
                        <details style={{ marginTop: 4 }}>
                          <summary className="muted" style={{ fontSize: "0.85em", cursor: "pointer" }}>
                            示例案例（{p.example_cases.length}）
                          </summary>
                          <ul style={{ margin: "4px 0", paddingLeft: 18, fontSize: "0.85em" }}>
                            {p.example_cases.map((c) => (
                              <li key={c.case_id} className="muted">
                                <strong>{c.case_id}</strong> [{c.source}] {c.claim.slice(0, 70)}
                                {c.claim.length > 70 ? "…" : ""}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* AI Weakness Map */}
          <h2>④ AI Weakness Map（来源 × 模式 矩阵）</h2>
          <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em", overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "6px 8px", borderBottom: "1px solid #1e293b" }}>来源 \ 模式</th>
                  {patterns.map((p) => (
                    <th key={p.pattern} style={{ textAlign: "center", padding: "6px 8px", borderBottom: "1px solid #1e293b", color: PATTERN_COLOR[p.pattern] || "#64748b" }}>
                      {patternLabels[p.pattern] || p.pattern}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sources.map((src) => (
                  <tr key={src}>
                    <td style={{ padding: "6px 8px", borderBottom: "1px solid #1e293b", fontWeight: 600 }}>
                      {sourceLabels[src] || src}
                    </td>
                    {patterns.map((p) => {
                      // 从 example_cases + 全 patterns 反推该 cell 计数（前端近似）
                      const cellCases = p.example_cases.filter((c) => c.source === src);
                      const count = cellCases.length;
                      const intensity = Math.min(1, count / 5);
                      const bg = count > 0 ? `rgba(${PATTERN_COLOR[p.pattern]?.replace("#", "")?.match(/.{2}/g)?.map((h) => parseInt(h, 16)).join(",") || "99,102,241"}, ${intensity})` : "transparent";
                      return (
                        <td key={p.pattern} style={{ textAlign: "center", padding: "6px 8px", borderBottom: "1px solid #1e293b", background: bg }}>
                          {count || "-"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: "0.8em", marginTop: 6 }}>
              单元格数字 = 该来源在该模式下的示例案例数（前端近似，后端 WeaknessMap 已含完整矩阵）
            </p>
          </div>

          {/* Improvement Suggestions */}
          <h2>⑤ Improvement Suggestions（去重建议）</h2>
          <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.9em" }}>
            {report.suggested_improvements.length === 0 ? (
              <p className="muted">无改进建议（无失败案例或建议均为空）。</p>
            ) : (
              <ol style={{ margin: "4px 0", paddingLeft: 20 }}>
                {report.suggested_improvements.map((s, i) => (
                  <li key={i} style={{ marginBottom: 6 }}>{s}</li>
                ))}
              </ol>
            )}
            <p className="muted" style={{ fontSize: "0.8em", marginTop: 6 }}>
              建议仅针对失败模式的工程改进方向，不涉及模型训练或投资建议。
            </p>
          </div>

          {/* Reliability Trend */}
          <h2>⑥ Reliability Trend（版本 / Agent 表现比较）</h2>
          <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.9em" }}>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
              <span>
                趋势：
                <strong style={{ color: DIRECTION_COLOR[report.trend.direction] || "#64748b" }}>
                  {DIRECTION_LABEL[report.trend.direction] || report.trend.direction}
                </strong>
              </span>
              <span className="muted">delta {report.trend.delta > 0 ? "+" : ""}{report.trend.delta.toFixed(1)}</span>
              <span className="muted">{report.trend.points.length} 个版本/Agent</span>
            </div>
            {report.trend.points.length === 0 ? (
              <p className="muted">无趋势数据。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {report.trend.points.map((tp, i) => {
                  const pct = Math.max(0, Math.min(100, tp.score));
                  const color = pct >= 70 ? "#4ade80" : pct >= 40 ? "#fbbf24" : "#f87171";
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ minWidth: 160, fontSize: "0.85em" }} title={tp.label}>{tp.label.length > 20 ? tp.label.slice(0, 20) + "…" : tp.label}</span>
                      <div style={{ flex: 1, height: 10, background: "#1e293b", borderRadius: 4, overflow: "hidden" }}>
                        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.4s" }} />
                      </div>
                      <span style={{ minWidth: 60, textAlign: "right", fontSize: "0.85em", color }}>{tp.score.toFixed(1)}</span>
                      <span className="muted" style={{ minWidth: 40, textAlign: "right", fontSize: "0.8em" }}>n={tp.samples}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 护栏声明 */}
          <p className="muted" style={{ fontSize: "0.8em", marginTop: 16 }}>
            本报告仅分析 AI 生成内容的失败模式与改进方向，不修改模型、不训练模型，不输出投资建议。
          </p>
        </>
      )}
    </main>
  );
}
