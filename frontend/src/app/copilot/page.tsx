"use client";

import { useState } from "react";

type ToolStep = {
  step: number;
  tool: string;
  purpose: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  evidence_source: { block_id?: number; page_number?: number; text?: string; score?: number }[];
  timestamp: string;
};

type Evidence = { document: string; page: string | number; content: string; block_id?: number };

type Response = {
  answer: string;
  evidence: Evidence[];
  verification: string;
  risk_score: number;
  risk_level: string;
  risk_type: string;
  source: string;
  tool_trace: ToolStep[];
  intent: { intent_type: string; confidence: number; keywords: string[]; company: string; metric: string } | null;
  session_id?: string;
};

type HistoryMessage = {
  id?: number;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  intent_type?: string;
  tools_called?: string[];
  evidence?: Evidence[];
  risk_score?: number;
  timestamp: string;
};

const LEVEL_COLOR: Record<string, string> = { HIGH: "#f87171", MEDIUM: "#fbbf24", LOW: "#4ade80" };
const INTENT_LABEL: Record<string, string> = {
  FACT_QUERY: "事实查询",
  RISK_EXPLANATION: "风险解释",
  EVIDENCE_QUERY: "证据查询",
  COMPARISON_QUERY: "比较查询",
  INVESTIGATION_REQUEST: "调查请求",
  UNKNOWN: "未知意图",
};
const TOOL_LABEL: Record<string, string> = {
  evidence_retrieval: "证据检索",
  verification: "核验引擎",
  risk_engine: "风险引擎",
  knowledge_graph: "知识图谱",
  monitoring_memory: "监控记忆",
  autonomous_investigation: "自主调查",
};

const DEMO_QUESTIONS = [
  "美的海外业务是否真的成为增长核心？",
  "这份AI研报最大的风险是什么？",
  "这个数字可信吗？",
];

export default function CopilotPage() {
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string>("");
  const [lastResponse, setLastResponse] = useState<Response | null>(null);
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendQuery = async (q?: string) => {
    const text = q ?? query;
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    // 先把用户问题追加到本地消息列表
    const userMsg: HistoryMessage = {
      session_id: sessionId,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const resp = await fetch("/api/v1/copilot/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text, session_id: sessionId || undefined, user_id: "web" }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setLastResponse(body);
      if (body.session_id) setSessionId(body.session_id);
      // 追加助手回答
      const assistantMsg: HistoryMessage = {
        session_id: body.session_id || sessionId,
        role: "assistant",
        content: body.answer,
        intent_type: body.intent?.intent_type,
        tools_called: body.tool_trace?.map((t: ToolStep) => t.tool),
        evidence: body.evidence,
        risk_score: body.risk_score,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      if (!q) setQuery("");
    } catch (e) {
      setError(`回答失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async () => {
    if (!sessionId) return;
    setError(null);
    try {
      const resp = await fetch(`/api/v1/copilot/history/${encodeURIComponent(sessionId)}`);
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setMessages(body.messages || []);
    } catch (e) {
      setError(`查询历史失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const newSession = () => {
    setSessionId("");
    setMessages([]);
    setLastResponse(null);
  };

  return (
    <main className="page">
      <h1>FinProof Copilot · Financial Audit Assistant（Phase 15）</h1>
      <p className="muted">
        基于已有 Evidence First 架构回答。不输出投资建议、不推荐股票、不买卖判断。
      </p>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {/* 左侧：对话区 */}
        <section style={{ flex: "1 1 380px", minWidth: 320 }}>
          {/* ① Chat Interface */}
          <h2>对话</h2>
          <div className="card">
            <div className="form-row" style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
              <label style={{ flex: "1 1 220px" }}>
                问题
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  rows={2}
                  placeholder="例如：美的2024年净利润是多少？"
                  style={{ width: "100%" }}
                />
              </label>
              <button onClick={() => sendQuery()} disabled={loading}>
                {loading ? "思考中…" : "提问"}
              </button>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <button onClick={newSession} style={{ fontSize: "0.85em" }}>
                新会话
              </button>
              <button onClick={loadHistory} disabled={!sessionId} style={{ fontSize: "0.85em" }}>
                加载历史
              </button>
              <span className="muted" style={{ fontSize: "0.85em", alignSelf: "center" }}>
                Session: {sessionId || "(新建)"}
              </span>
            </div>
            {/* Demo 问题快捷 */}
            <div style={{ marginTop: 8 }}>
              <span className="muted" style={{ fontSize: "0.85em" }}>Demo 问题：</span>
              {DEMO_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => sendQuery(q)}
                  disabled={loading}
                  style={{ fontSize: "0.8em", marginRight: 6, marginTop: 4 }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>

          {error && <p className="bad">{error}</p>}

          {/* 对话历史 */}
          <h3>对话历史</h3>
          {messages.length === 0 ? (
            <p className="muted">暂无对话。先提问或加载历史。</p>
          ) : (
            <div style={{ maxHeight: 480, overflowY: "auto" }}>
              {messages.map((m, i) => (
                <div
                  key={i}
                  className="semantic-card"
                  style={{
                    marginBottom: 8,
                    borderLeftColor: m.role === "user" ? "#38bdf8" : "#4ade80",
                  }}
                >
                  <strong>{m.role === "user" ? "🙋 用户" : "🤖 Copilot"}</strong>
                  <span className="muted" style={{ marginLeft: 8, fontSize: "0.8em" }}>
                    {m.intent_type ? `· ${INTENT_LABEL[m.intent_type] || m.intent_type}` : ""}
                  </span>
                  <p style={{ margin: "4px 0" }}>{m.content}</p>
                  {m.role === "assistant" && (
                    <div className="muted" style={{ fontSize: "0.85em" }}>
                      {m.tools_called && m.tools_called.length > 0 && (
                        <p>调用工具：{m.tools_called.map((t) => TOOL_LABEL[t] || t).join(" → ")}</p>
                      )}
                      {m.risk_score !== undefined && (
                        <p>
                          风险评分：<strong style={{ color: LEVEL_COLOR[lastResponse?.risk_level || "LOW"] || "#94a3b8" }}>
                            {m.risk_score}
                          </strong>
                        </p>
                      )}
                      {m.evidence && m.evidence.length > 0 && (
                        <p>证据数：{m.evidence.length}</p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 右侧：最新回答详情 */}
        <section style={{ flex: "1 1 320px", minWidth: 320 }}>
          <h2>最新回答详情</h2>
          {!lastResponse ? (
            <p className="muted">提问后展示：AI 回答 → 调用工具 → 证据来源 → 核验结果 → 风险评分。</p>
          ) : (
            <div>
              {/* ① AI 回答 */}
              <div className="verdict-card" style={{ borderLeftColor: LEVEL_COLOR[lastResponse.risk_level] || "#64748b" }}>
                <h3>① AI 回答（Summary）</h3>
                <p>{lastResponse.answer}</p>
                {lastResponse.intent && (
                  <p className="muted" style={{ fontSize: "0.85em" }}>
                    意图：{INTENT_LABEL[lastResponse.intent.intent_type] || lastResponse.intent.intent_type}
                    （置信度 {lastResponse.intent.confidence}）· 公司 {lastResponse.intent.company || "-"}
                  </p>
                )}
              </div>

              {/* ② 调用工具 */}
              <h3>② 调用工具（Tool Trace）</h3>
              {lastResponse.tool_trace.length === 0 ? (
                <p className="muted">无工具调用。</p>
              ) : (
                <div>
                  {lastResponse.tool_trace.map((s) => (
                    <div key={s.step} className="semantic-card" style={{ marginBottom: 6, fontSize: "0.85em" }}>
                      <strong>
                        Step {s.step} · {TOOL_LABEL[s.tool] || s.tool}
                      </strong>
                      <p className="muted" style={{ margin: "2px 0" }}>目的：{s.purpose}</p>
                      <p className="muted" style={{ margin: "2px 0" }}>
                        结果：证据 {String((s.output as Record<string, unknown>).evidence_count ?? 0)} 条
                        {(s.output as Record<string, unknown>).risk_assessment ? " · 已评估风险" : ""}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {/* ③ 证据来源 */}
              <h3>③ 证据来源（Evidence Chain）</h3>
              {lastResponse.evidence.length === 0 ? (
                <p className="muted">无证据。回答基于"未检索到证据"原则。</p>
              ) : (
                <div>
                  {lastResponse.evidence.map((e, i) => (
                    <div key={i} className="source-quote" style={{ fontSize: "0.85rem", marginBottom: 6 }}>
                      <strong>{e.document}</strong> · 第 {e.page} 页
                      <div className="muted" style={{ marginTop: 4 }}>{e.content.slice(0, 160)}…</div>
                    </div>
                  ))}
                </div>
              )}

              {/* ④ 核验结果 */}
              <h3>④ 核验结果（Verification）</h3>
              <div className="semantic-card">
                <p>
                  <strong>核验结论：</strong>
                  {lastResponse.verification || "待核验"}
                </p>
              </div>

              {/* ⑤ 风险评分 */}
              <h3>⑤ 风险评分（Risk）</h3>
              <div className="verdict-card" style={{ borderLeftColor: LEVEL_COLOR[lastResponse.risk_level] || "#64748b" }}>
                <p>
                  风险评分 <strong style={{ color: LEVEL_COLOR[lastResponse.risk_level] || "#94a3b8" }}>
                    {lastResponse.risk_score}
                  </strong>{" "}
                  · {lastResponse.risk_level} · 类型 {lastResponse.risk_type || "-"}
                </p>
                <p className="muted" style={{ fontSize: "0.85em" }}>来源：{lastResponse.source}</p>
              </div>

              {/* ⑥ 金融逻辑检查卡片 */}
              {(() => {
                const reasoningStep = lastResponse.tool_trace.find(
                  (s) => s.tool === "financial_reasoning"
                );
                if (!reasoningStep) return null;
                const out = reasoningStep.output as Record<string, unknown>;
                const results = (out.results as Array<Record<string, unknown>>) || [];
                return (
                  <>
                    <h3>⑥ 金融逻辑检查（Financial Reasoning）</h3>
                    <div className="semantic-card">
                      <p className="muted" style={{ fontSize: "0.85em" }}>
                        推理运行：{String(out.reasoning_run_id ?? "-")} · 结果 {String(out.results_count ?? 0)} 条
                      </p>
                      {results.length === 0 ? (
                        <p className="muted">未触发逻辑风险规则。</p>
                      ) : (
                        <div>
                          {results.slice(0, 3).map((r, i) => (
                            <div
                              key={i}
                              className="verdict-card"
                              style={{
                                borderLeftColor: "#fbbf24",
                                marginBottom: 8,
                                fontSize: "0.85em",
                              }}
                            >
                              <strong>
                                {String(r.reasoning_type ?? "")} · {String(r.status ?? "")}
                              </strong>
                              <p style={{ margin: "2px 0" }}>
                                <strong>逻辑缺口：</strong>
                                <span className="muted">{String(r.logical_gap ?? "")}</span>
                              </p>
                              {(r.assumptions as unknown[] | undefined)?.length ? (
                                <p style={{ margin: "2px 0" }}>
                                  <strong>隐含假设：</strong>
                                  <span className="muted">
                                    {(r.assumptions as string[]).join("；")}
                                  </span>
                                </p>
                              ) : null}
                              {String(r.suggested_safe_wording ?? "") ? (
                                <p style={{ borderLeft: "2px solid #4ade80", paddingLeft: 6, margin: "2px 0" }}>
                                  <strong>安全措辞：</strong>
                                  {String(r.suggested_safe_wording)}
                                </p>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                );
              })()}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
