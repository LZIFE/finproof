"use client";

import { useState } from "react";

type Project = {
  project_id: number;
  portfolio_id: string;
  company: string;
  stock_code: string;
  weight: number;
  audit_id: number | null;
  committee_report_id: number | null;
  latest_risk_score: number;
  latest_risk_level: string;
};

type CompanyRanking = {
  rank: number;
  company: string;
  stock_code: string;
  risk_score: number;
  risk_level: string;
};

type RiskDistribution = {
  risk_level: string;
  count: number;
  share: number;
};

type HighestRiskFinding = {
  company: string;
  finding: string;
  risk_score: number;
  risk_level: string;
  evidence: string;
};

type Snapshot = {
  id: number;
  portfolio_id: string;
  portfolio_risk_score: number;
  portfolio_risk_level: string;
  company_ranking: CompanyRanking[];
  risk_distribution: RiskDistribution[];
  highest_risk_findings: HighestRiskFinding[];
  projects: Project[];
  created_at: string;
};

const LEVEL_COLOR: Record<string, string> = {
  HIGH: "#f87171",
  MEDIUM: "#fbbf24",
  LOW: "#4ade80",
};

function fmtPct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export default function PortfolioPage() {
  const [portfolioId, setPortfolioId] = useState("PF-DEMO");
  const [projects, setProjects] = useState<Project[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 新增项目表单
  const [company, setCompany] = useState("美的集团");
  const [stockCode, setStockCode] = useState("000333");
  const [weight, setWeight] = useState("0.34");
  const [riskScore, setRiskScore] = useState("42.0");

  const fetchProjects = async () => {
    setError(null);
    try {
      const resp = await fetch(
        `/api/v1/portfolio/projects?portfolio_id=${encodeURIComponent(portfolioId)}`
      );
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setProjects(body.projects || []);
    } catch (e) {
      setError(`查询项目失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const addProject = async () => {
    setError(null);
    try {
      const resp = await fetch("/api/v1/portfolio/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          portfolio_id: portfolioId,
          company,
          stock_code: stockCode,
          weight: parseFloat(weight),
          latest_risk_score: parseFloat(riskScore),
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setProjects((prev) => [...prev, body]);
    } catch (e) {
      setError(`添加项目失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const buildSnapshot = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/portfolio/snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ portfolio_id: portfolioId }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setSnapshot(body);
      fetchSnapshots();
    } catch (e) {
      setError(`构建快照失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchSnapshots = async () => {
    try {
      const resp = await fetch(
        `/api/v1/portfolio/snapshots?portfolio_id=${encodeURIComponent(portfolioId)}`
      );
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setSnapshots(body.snapshots || []);
    } catch {
      // 忽略
    }
  };

  return (
    <main className="page">
      <h1>投资组合风险看板（Phase 12 · Portfolio Risk Dashboard）</h1>
      <p className="muted">
        多个投资项目风险汇总：组合风险评分 · 公司风险排名 · 风险分布 · 最高风险 Findings。
      </p>

      <div className="form-row" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label>
          组合 ID
          <input value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)} />
        </label>
        <button onClick={fetchProjects}>查询项目</button>
        <button onClick={buildSnapshot} disabled={loading}>
          {loading ? "构建中…" : "构建风险快照"}
        </button>
        <button onClick={fetchSnapshots}>查询历史快照</button>
      </div>

      {error && <p className="bad">{error}</p>}

      {/* 新增项目 */}
      <h2>① 新增投资项目</h2>
      <div className="card">
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label style={{ flex: "1 1 120px" }}>
            公司
            <input value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px" }}>
            股票代码
            <input value={stockCode} onChange={(e) => setStockCode(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 80px" }}>
            权重
            <input value={weight} onChange={(e) => setWeight(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px" }}>
            风险分
            <input value={riskScore} onChange={(e) => setRiskScore(e.target.value)} />
          </label>
        </div>
        <button onClick={addProject} style={{ marginTop: 8 }}>
          添加到组合
        </button>
      </div>

      {/* 组合项目列表 */}
      <h2>② 组合内项目（{projects.length}）</h2>
      {projects.length === 0 ? (
        <p className="muted">暂无项目。先添加项目或点击"查询项目"。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>项目ID</th>
              <th>公司</th>
              <th>代码</th>
              <th>权重</th>
              <th>风险分</th>
              <th>风险等级</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.project_id}>
                <td>{p.project_id}</td>
                <td>{p.company}</td>
                <td>{p.stock_code}</td>
                <td>{fmtPct(p.weight)}</td>
                <td>{p.latest_risk_score}</td>
                <td style={{ color: LEVEL_COLOR[p.latest_risk_level] || "#94a3b8", fontWeight: 600 }}>
                  {p.latest_risk_level}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* 风险快照 */}
      <h2>③ 组合风险快照</h2>
      {snapshot ? (
        <div>
          <div className="verdict-card" style={{ borderLeftColor: LEVEL_COLOR[snapshot.portfolio_risk_level] || "#64748b" }}>
            <h3>
              组合风险评分 <strong style={{ color: LEVEL_COLOR[snapshot.portfolio_risk_level] || "#94a3b8" }}>
                {snapshot.portfolio_risk_score}
              </strong>{" "}
              · {snapshot.portfolio_risk_level}
            </h3>
            <p className="muted">快照 ID: {snapshot.id} · 创建于 {snapshot.created_at}</p>
          </div>

          <h4>公司风险排名</h4>
          <table>
            <thead>
              <tr>
                <th>排名</th>
                <th>公司</th>
                <th>代码</th>
                <th>风险分</th>
                <th>等级</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.company_ranking.map((c) => (
                <tr key={c.rank}>
                  <td>{c.rank}</td>
                  <td>{c.company}</td>
                  <td>{c.stock_code}</td>
                  <td>{c.risk_score}</td>
                  <td style={{ color: LEVEL_COLOR[c.risk_level] || "#94a3b8", fontWeight: 600 }}>
                    {c.risk_level}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h4>风险分布</h4>
          <div className="semantic-card">
            <ul>
              {snapshot.risk_distribution.map((d) => (
                <li key={d.risk_level}>
                  <strong style={{ color: LEVEL_COLOR[d.risk_level] || "#94a3b8" }}>{d.risk_level}</strong>
                  ：{d.count} 个项目 · 占比 {fmtPct(d.share)}
                </li>
              ))}
            </ul>
          </div>

          <h4>最高风险 Findings</h4>
          {snapshot.highest_risk_findings.map((f, i) => (
            <div key={i} className="verdict-card" style={{ borderLeftColor: LEVEL_COLOR[f.risk_level] || "#64748b" }}>
              <h4>{f.company} — {f.risk_level}</h4>
              <p>{f.finding}</p>
              <p className="muted">{f.evidence}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">点击"构建风险快照"查看聚合结果。</p>
      )}

      {/* 历史快照趋势 */}
      <h2>④ 风险趋势（历史快照）</h2>
      {snapshots.length === 0 ? (
        <p className="muted">暂无历史快照。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>快照ID</th>
              <th>创建时间</th>
              <th>组合风险分</th>
              <th>等级</th>
            </tr>
          </thead>
          <tbody>
            {snapshots.map((s) => (
              <tr key={s.id}>
                <td>{s.id}</td>
                <td>{s.created_at}</td>
                <td>{s.portfolio_risk_score}</td>
                <td style={{ color: LEVEL_COLOR[s.portfolio_risk_level] || "#94a3b8", fontWeight: 600 }}>
                  {s.portfolio_risk_level}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
