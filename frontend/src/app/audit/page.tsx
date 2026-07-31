"use client";

import { useCallback, useEffect, useState } from "react";

type DocItem = {
  id: number;
  original_filename: string;
  document_role: string;
  company_name: string | null;
  report_period: string | null;
  parse_status: string;
};

type Summary = {
  total_claims: number;
  supported_count: number;
  refuted_count: number;
  partially_supported_count: number;
  insufficient_count: number;
  unknown_count: number;
};

type Finding = {
  claim_id: string;
  claim: string;
  evidence: { page_number: number; block_id: number; text: string; evidence_type: string }[];
  calculation: string;
  conclusion: string;
  reason: string;
};

type ChainItem = {
  claim_id: string;
  claim: string;
  evidence: string[];
  verification: string;
  conclusion: string;
};

type PlanStep = { name: string; status: string; detail: string };

type AuditDetail = {
  audit_id: number;
  document_id: number;
  summary: Summary;
  findings: Finding[];
  evidence_chain: ChainItem[];
  verification_results: unknown[];
  plan: { log: PlanStep[] } | null;
};

const STEP_LABEL: Record<string, string> = {
  extract_claims: "Extracting claims",
  retrieve_evidence: "Retrieving evidence",
  verify_claims: "Running verification",
  generate_report: "Generating audit report",
};

const CONCLUSION_STYLE: Record<string, string> = {
  REFUTED: "verdict-refuted",
  PARTIALLY_SUPPORTED: "verdict-partial",
  INSUFFICIENT_EVIDENCE: "verdict-insufficient",
  SUPPORTED: "verdict-supported",
  UNABLE_TO_DETERMINE: "verdict-unable",
};

export default function AuditPage() {
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [auditing, setAuditing] = useState(false);
  const [detail, setDetail] = useState<AuditDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDocs = useCallback(() => {
    fetch("/api/v1/documents?document_role=REPORT_TO_VERIFY")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((rows) => {
        setDocs(Array.isArray(rows) ? rows : []);
        if (rows?.length && selectedDoc === null) setSelectedDoc(rows[0].id);
      })
      .catch(() => undefined);
  }, [selectedDoc]);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const uploadAndAudit = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("document_role", "REPORT_TO_VERIFY");
      const resp = await fetch("/api/v1/documents", { method: "POST", body: fd });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      const docId = body.id ?? body.document?.id;
      await runAudit(docId);
      loadDocs();
    } catch (e) {
      setError(`上传失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
  };

  const runAudit = async (docId: number) => {
    setAuditing(true);
    setError(null);
    setDetail(null);
    try {
      const resp = await fetch("/api/v1/audits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: docId }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      const resp2 = await fetch(`/api/v1/audits/${body.audit_id}`);
      const detailBody = await resp2.json();
      if (!resp2.ok) throw new Error(JSON.stringify(detailBody));
      setDetail(detailBody);
    } catch (e) {
      setError(`审计失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setAuditing(false);
    }
  };

  return (
    <main className="page">
      <h1>金融审计智能体（Phase 5 · Audit Agent）</h1>
      <p>
        上传 AI 生成的金融研报 → 自动拆解主张 → 财报证据检索 → 确定性核验 → 生成审计报告。
        <b> Evidence First</b>：不凭空判断、不编造证据、不输出投资建议。
      </p>

      <section>
        <h2>上传 AI 研报</h2>
        <div className="form-row">
          <input type="file" accept=".md,.txt,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button onClick={uploadAndAudit} disabled={!file || uploading}>
            {uploading ? "上传中…" : "上传并审计"}
          </button>
        </div>
      </section>

      <section>
        <h2>或选择已有研报</h2>
        <div className="form-row">
          <select
            value={selectedDoc ?? ""}
            onChange={(e) => setSelectedDoc(Number(e.target.value))}
          >
            {docs.map((d) => (
              <option key={d.id} value={d.id}>
                #{d.id} {d.original_filename}（{d.company_name ?? "-"} / {d.report_period ?? "-"}）
              </option>
            ))}
          </select>
          <button
            onClick={() => selectedDoc && runAudit(selectedDoc)}
            disabled={!selectedDoc || auditing}
          >
            {auditing ? "审计中…" : "创建审计任务"}
          </button>
        </div>
      </section>

      {error && <p className="bad">{error}</p>}

      {detail && (
        <section>
          <h2>Agent 执行过程</h2>
          <ul>
            {(detail.plan?.log ?? []).map((s) => (
              <li key={s.name}>
                ✓ {STEP_LABEL[s.name] ?? s.name} — {s.detail}
              </li>
            ))}
          </ul>

          <h2>审计结果（审计 #{detail.audit_id} · 文档 #{detail.document_id}）</h2>
          <table>
            <thead>
              <tr>
                <th>总主张</th>
                <th className="verdict-supported">支持</th>
                <th className="verdict-refuted">反驳</th>
                <th className="verdict-partial">部分支持</th>
                <th className="verdict-insufficient">证据不足</th>
                <th>无法判定</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{detail.summary.total_claims}</td>
                <td>{detail.summary.supported_count}</td>
                <td>{detail.summary.refuted_count}</td>
                <td>{detail.summary.partially_supported_count}</td>
                <td>{detail.summary.insufficient_count}</td>
                <td>{detail.summary.unknown_count}</td>
              </tr>
            </tbody>
          </table>

          <h2>风险详情（Risk Findings）</h2>
          {detail.findings.map((f) => (
            <div key={f.claim_id} className={`verdict-card ${CONCLUSION_STYLE[f.conclusion] ?? ""}`}>
              <h3>
                {f.claim_id} — <strong>{f.conclusion}</strong>
              </h3>
              <p>
                <b>Claim：</b>
                {f.claim}
              </p>
              <p>
                <b>Evidence：</b>
                {(f.evidence ?? [])
                  .map((e) => `p${e.page_number} blk${e.block_id}（${e.evidence_type}）`)
                  .join("；") || "无"}
              </p>
              {f.calculation && (
                <p>
                  <b>Calculation：</b>
                  <code>{f.calculation}</code>
                </p>
              )}
              <p>
                <b>Reason：</b>
                {f.reason}
              </p>
            </div>
          ))}

          <h2>证据链（Evidence Chain）</h2>
          {detail.evidence_chain.slice(0, 10).map((c) => (
            <div key={c.claim_id} className="semantic-card">
              <p>
                <b>{c.claim_id}</b>：{c.claim}
              </p>
              <p>
                ↓ 证据：{c.evidence.join("；") || "无"}
              </p>
              <p>
                ↓ 核验：<strong>{c.verification}</strong> — {c.conclusion}
              </p>
            </div>
          ))}
        </section>
      )}

      {!detail && !auditing && <p>上传 AI 研报或选择已有研报开始审计。</p>}
    </main>
  );
}
