"use client";

import { useState } from "react";

type AuditLog = {
  log_id: string;
  user: string;
  action: string;
  target_type: string | null;
  target_id: number | null;
  timestamp: string;
  model_version: string;
  rule_version: string;
  evidence_used: { source?: string; page?: number; text?: string }[];
  detail: Record<string, unknown>;
};

const LEVEL_COLOR: Record<string, string> = {
  HIGH: "#f87171",
  MEDIUM: "#fbbf24",
  LOW: "#4ade80",
};

export default function GovernancePage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [trace, setTrace] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 过滤条件
  const [userFilter, setUserFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [targetTypeFilter, setTargetTypeFilter] = useState("");

  // 证据溯源查询
  const [traceTargetType, setTraceTargetType] = useState("committee_report");
  const [traceTargetId, setTraceTargetId] = useState("1");

  const buildQuery = () => {
    const params = new URLSearchParams();
    if (userFilter) params.set("user", userFilter);
    if (actionFilter) params.set("action", actionFilter);
    if (targetTypeFilter) params.set("target_type", targetTypeFilter);
    return params.toString();
  };

  const fetchLogs = async () => {
    setError(null);
    try {
      const resp = await fetch(`/api/v1/governance/logs?${buildQuery()}`);
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setLogs(body.logs || []);
    } catch (e) {
      setError(`查询审计日志失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const fetchTrace = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(
        `/api/v1/governance/evidence-trace/${encodeURIComponent(traceTargetType)}/${encodeURIComponent(traceTargetId)}`
      );
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setTrace(body.trace || []);
    } catch (e) {
      setError(`证据溯源失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <h1>企业治理视图（Phase 12 · Audit Trail & Evidence Trace）</h1>
      <p className="muted">
        审计日志（user / action / timestamp / model_version / rule_version / evidence_used）+ 证据溯源。
      </p>

      {/* ① 审计日志查询 */}
      <h2>① 审计日志查询</h2>
      <div className="card">
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label style={{ flex: "1 1 120px" }}>
            用户
            <input value={userFilter} onChange={(e) => setUserFilter(e.target.value)} placeholder="analyst_zhang" />
          </label>
          <label style={{ flex: "1 1 140px" }}>
            动作
            <input value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} placeholder="RUN_COMMITTEE" />
          </label>
          <label style={{ flex: "1 1 140px" }}>
            目标类型
            <input
              value={targetTypeFilter}
              onChange={(e) => setTargetTypeFilter(e.target.value)}
              placeholder="committee_report"
            />
          </label>
        </div>
        <button onClick={fetchLogs} style={{ marginTop: 8 }}>
          查询审计日志
        </button>
      </div>

      {error && <p className="bad">{error}</p>}

      {logs.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>日志ID</th>
              <th>用户</th>
              <th>动作</th>
              <th>目标</th>
              <th>时间</th>
              <th>模型版本</th>
              <th>规则版本</th>
              <th>证据数</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l.log_id}>
                <td>{l.log_id}</td>
                <td>{l.user}</td>
                <td>{l.action}</td>
                <td>
                  {l.target_type || "-"}
                  {l.target_id ? `#${l.target_id}` : ""}
                </td>
                <td className="muted">{l.timestamp}</td>
                <td className="muted">{l.model_version || "-"}</td>
                <td className="muted">{l.rule_version || "-"}</td>
                <td>{l.evidence_used?.length || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">暂无日志。设置过滤条件后点击"查询审计日志"。</p>
      )}

      {/* ② 单条日志详情（首条展开） */}
      {logs.length > 0 && (
        <>
          <h2>② 日志详情（首条）</h2>
          <div className="semantic-card">
            <p>
              <strong>{logs[0].log_id}</strong> · {logs[0].action} · {logs[0].user}
            </p>
            <p className="muted">时间：{logs[0].timestamp}</p>
            <p className="muted">
              模型版本：{logs[0].model_version || "-"} · 规则版本：{logs[0].rule_version || "-"}
            </p>
            <h4>使用的证据（evidence_used）</h4>
            {logs[0].evidence_used && logs[0].evidence_used.length > 0 ? (
              <ul>
                {logs[0].evidence_used.map((ev, i) => (
                  <li key={i}>
                    {ev.source || "未知来源"}
                    {ev.page ? ` 第${ev.page}页` : ""}
                    {ev.text ? `：${ev.text}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">无证据记录。</p>
            )}
            {Object.keys(logs[0].detail || {}).length > 0 && (
              <>
                <h4>其他上下文（detail）</h4>
                <pre className="muted" style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(logs[0].detail, null, 2)}
                </pre>
              </>
            )}
          </div>
        </>
      )}

      {/* ③ 证据溯源 */}
      <h2>③ 证据溯源（Evidence Trace）</h2>
      <div className="card">
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label style={{ flex: "1 1 160px" }}>
            目标类型
            <input value={traceTargetType} onChange={(e) => setTraceTargetType(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px" }}>
            目标ID
            <input value={traceTargetId} onChange={(e) => setTraceTargetId(e.target.value)} />
          </label>
        </div>
        <button onClick={fetchTrace} disabled={loading} style={{ marginTop: 8 }}>
          {loading ? "查询中…" : "查询证据溯源"}
        </button>
      </div>

      {trace.length > 0 ? (
        <div>
          <p className="muted">共 {trace.length} 条相关审计日志：</p>
          {trace.map((l) => (
            <div key={l.log_id} className="verdict-card" style={{ borderLeftColor: "#38bdf8" }}>
              <h4>
                {l.log_id} · {l.action}
              </h4>
              <p className="muted">
                {l.user} · {l.timestamp} · 模型 {l.model_version || "-"} · 规则 {l.rule_version || "-"}
              </p>
              {l.evidence_used && l.evidence_used.length > 0 && (
                <ul className="muted" style={{ margin: "4px 0", paddingLeft: 18 }}>
                  {l.evidence_used.map((ev, i) => (
                    <li key={i}>
                      {ev.source || "未知"}
                      {ev.page ? ` p${ev.page}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">输入目标类型与 ID，点击"查询证据溯源"。</p>
      )}
    </main>
  );
}
