"use client";

import { useState } from "react";

type AttackCase = {
  case_id: string;
  original_claim: string;
  attacked_claim: string;
  attack_type: string;
  expected_risk: number;
  company: string;
  stock_code: string;
};

type DetectionResult = {
  case_id: string;
  detected: boolean;
  error_type: string;
  evidence_count: number;
  evidence: { type?: string; explanation?: string; original_value?: number; attacked_value?: number }[];
  risk_score: number;
  verification_status: string;
  confidence: number;
};

type ReliabilityDimension = { name: string; score: number; weight: number };
type ReliabilityScore = {
  finproof_score: number;
  dimensions: ReliabilityDimension[];
  grade: string;
  summary: string;
};
type StressMetrics = {
  total_cases: number;
  detected_cases: number;
  detection_accuracy: number;
  recall: number;
  precision: number;
  category_recall: Record<string, number>;
};
type Run = {
  run_id: string;
  total_cases: number;
  metrics: StressMetrics;
  reliability_score: ReliabilityScore;
  attack_distribution: Record<string, number>;
  created_at: string;
};

const LEVEL_COLOR: Record<string, string> = { HIGH: "#f87171", MEDIUM: "#fbbf24", LOW: "#4ade80" };
const ATTACK_LABEL: Record<string, string> = {
  NUMERIC_HALLUCINATION: "数字幻觉",
  PERIOD_CONFUSION: "期间混淆",
  GROWTH_ERROR: "增长错误",
  UNSUPPORTED_STRATEGIC: "无证据战略主张",
  FORECAST_AS_FACT: "预测当事实",
};

export default function RedTeamPage() {
  const [claimText, setClaimText] = useState("2024年净利润438亿");
  const [attackType, setAttackType] = useState("NUMERIC_HALLUCINATION");
  const [company, setCompany] = useState("美的集团");
  const [stockCode, setStockCode] = useState("000333");

  const [lastAttack, setLastAttack] = useState<AttackCase | null>(null);
  const [lastDetection, setLastDetection] = useState<{ case: AttackCase; detection: DetectionResult } | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // ① Attack Dashboard：生成攻击
  const generateAttack = async () => {
    setError(null);
    try {
      const resp = await fetch("/api/v1/red-team/attacks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          original_claim: claimText,
          attack_type: attackType,
          company,
          stock_code: stockCode,
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setLastAttack(body);
    } catch (e) {
      setError(`生成攻击失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // ② Detection：检测攻击
  const detectAttack = async () => {
    if (!lastAttack) return;
    setError(null);
    setLoading(true);
    try {
      const resp = await fetch("/api/v1/red-team/detection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          original_claim: lastAttack.original_claim,
          attacked_claim: lastAttack.attacked_claim,
          attack_type: lastAttack.attack_type,
          expected_risk: lastAttack.expected_risk,
          company: lastAttack.company,
          stock_code: lastAttack.stock_code,
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setLastDetection(body);
    } catch (e) {
      setError(`检测失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  // ③ 列出 Red Team runs
  const listRuns = async () => {
    setError(null);
    try {
      const resp = await fetch("/api/v1/red-team/runs?limit=10");
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setRuns(body.runs || []);
    } catch (e) {
      setError(`查询 runs 失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <main className="page">
      <h1>FinProof Red Team & Financial AI Reliability Lab（Phase 14）</h1>
      <p className="muted">
        从"检测 AI 错误"升级为"主动测试金融 AI 系统可靠性"。保持 Evidence First；不修改已有核心验证模块。
      </p>

      {/* ① Attack Dashboard */}
      <h2>① Attack Dashboard — 攻击生成</h2>
      <div className="card">
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label style={{ flex: "2 1 240px" }}>
            原始主张
            <input value={claimText} onChange={(e) => setClaimText(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 160px" }}>
            攻击类型
            <select value={attackType} onChange={(e) => setAttackType(e.target.value)}>
              <option value="NUMERIC_HALLUCINATION">NUMERIC_HALLUCINATION 数字幻觉</option>
              <option value="PERIOD_CONFUSION">PERIOD_CONFUSION 期间混淆</option>
              <option value="GROWTH_ERROR">GROWTH_ERROR 增长错误</option>
              <option value="UNSUPPORTED_STRATEGIC">UNSUPPORTED_STRATEGIC 无证据战略主张</option>
              <option value="FORECAST_AS_FACT">FORECAST_AS_FACT 预测当事实</option>
            </select>
          </label>
        </div>
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          <label style={{ flex: "1 1 120px" }}>
            公司
            <input value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px" }}>
            股票代码
            <input value={stockCode} onChange={(e) => setStockCode(e.target.value)} />
          </label>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button onClick={generateAttack}>生成攻击</button>
          <button onClick={detectAttack} disabled={loading || !lastAttack}>
            {loading ? "检测中…" : "检测攻击"}
          </button>
          <button onClick={listRuns}>查询 Red Team Runs</button>
        </div>
      </div>

      {error && <p className="bad">{error}</p>}

      {/* 攻击结果 */}
      {lastAttack && (
        <div className="semantic-card" style={{ marginTop: 12 }}>
          <h4>攻击案例 {lastAttack.case_id}</h4>
          <p>
            <strong>攻击类型：</strong>
            {ATTACK_LABEL[lastAttack.attack_type] || lastAttack.attack_type}（{lastAttack.attack_type}）
          </p>
          <p>
            <strong>原始主张：</strong>
            <span className="source-quote" style={{ display: "inline-block", marginLeft: 8 }}>
              {lastAttack.original_claim}
            </span>
          </p>
          <p>
            <strong>攻击后主张：</strong>
            <span className="source-quote" style={{ display: "inline-block", marginLeft: 8, borderColor: "#f87171" }}>
              {lastAttack.attacked_claim}
            </span>
          </p>
          <p className="muted">预期风险分：{lastAttack.expected_risk}</p>
        </div>
      )}

      {/* ② Detection 结果 */}
      {lastDetection && (
        <>
          <h2>② Hallucination Detection — 检测结果</h2>
          <div
            className="verdict-card"
            style={{
              borderLeftColor: lastDetection.detection.detected ? "#f87171" : "#4ade80",
            }}
          >
            <h3>
              {lastDetection.detection.detected ? "⚠ 检测到幻觉" : "✓ 未检测到幻觉"}
            </h3>
            <p>
              <strong>错误类型：</strong>
              {lastDetection.detection.error_type}
            </p>
            <p>
              <strong>风险分：</strong>
              {lastDetection.detection.risk_score} ·{" "}
              <strong>核验结论：</strong>
              {lastDetection.detection.verification_status} ·{" "}
              <strong>置信度：</strong>
              {lastDetection.detection.confidence}
            </p>
            <p className="muted">引用证据数：{lastDetection.detection.evidence_count}</p>
            {lastDetection.detection.evidence.length > 0 && (
              <div className="semantic-card">
                <h4>证据</h4>
                <ul className="muted" style={{ margin: "4px 0", paddingLeft: 18 }}>
                  {lastDetection.detection.evidence.map((ev, i) => (
                    <li key={i}>
                      <strong>{ev.type}</strong>：{ev.explanation}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </>
      )}

      {/* ③ Red Team Runs（Reliability Score + Attack Distribution） */}
      {runs.length > 0 && (
        <>
          <h2>③ Red Team Runs — Reliability Score</h2>
          {runs.map((r) => (
            <div key={r.run_id} className="verdict-card" style={{ borderLeftColor: LEVEL_COLOR.HIGH }}>
              <h3>
                {r.run_id} · {r.total_cases} 条攻击案例
              </h3>
              <p>
                <strong>FinProof Reliability Score：</strong>
                <span style={{ color: LEVEL_COLOR.LOW, fontWeight: 700, fontSize: "1.2em" }}>
                  {r.reliability_score.finproof_score}/100
                </span>{" "}
                （等级 {r.reliability_score.grade}）
              </p>
              <div className="semantic-card">
                <h4>维度得分</h4>
                <table>
                  <thead>
                    <tr>
                      <th>维度</th>
                      <th>得分</th>
                      <th>权重</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.reliability_score.dimensions.map((d) => (
                      <tr key={d.name}>
                        <td>{d.name}</td>
                        <td>{d.score}</td>
                        <td>{d.weight}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ marginTop: 8 }}>
                {r.reliability_score.summary}
              </p>
              <h4>检测指标</h4>
              <table>
                <tbody>
                  <tr>
                    <td>Detection Accuracy</td>
                    <td>{r.metrics.detection_accuracy}</td>
                  </tr>
                  <tr>
                    <td>Recall</td>
                    <td>{r.metrics.recall}</td>
                  </tr>
                  <tr>
                    <td>Precision</td>
                    <td>{r.metrics.precision}</td>
                  </tr>
                </tbody>
              </table>
              <h4>攻击类型分布</h4>
              <ul className="muted" style={{ margin: "4px 0", paddingLeft: 18 }}>
                {Object.entries(r.attack_distribution).map(([k, v]) => (
                  <li key={k}>
                    {ATTACK_LABEL[k] || k}：{v} 条
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}

      {/* ④ Case Replay 提示 */}
      <h2>④ Case Replay — 攻击回放流程</h2>
      <div className="semantic-card">
        <p className="muted">
          完整回放流程：<strong>AI 输出（原始主张）</strong> → <strong>攻击类型</strong>（数字幻觉/期间混淆/增长错误/无证据战略/预测当事实） →{" "}
          <strong>证据</strong>（数值/期间/增长率对比） → <strong>核验结果</strong>（detected / error_type / risk_score）。
        </p>
        <p className="muted">
          在上方 ① 生成攻击、② 检测攻击，即可看到完整 Case Replay。
        </p>
      </div>
    </main>
  );
}
