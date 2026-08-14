"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type VerdictStats = Record<string, number>;

type ErrorItem = {
  page_number: number;
  source_text: string;
  verdict: string;
  error_type: string;
  detail: string;
};

type ClaimRow = {
  claim_id: string;
  source_text: string;
  page_number: number;
  claim_kind: string;
  verdict: string;
  confidence: number;
  mode_used: string[];
  reason: string;
  error_type: string | null;
};

type VerifyResult = {
  run_id?: number;
  document_id?: number;
  total_claims: number;
  verdicts: VerdictStats;
  claims: ClaimRow[];
  error_report: ErrorItem[];
  is_mock: boolean;
  status?: string;
  filename?: string;
  error?: { code: string; message: string };
};

type RunRow = {
  id: number;
  filename: string;
  mode: string;
  total_claims: number;
  is_mock: boolean;
  status: string;
  created_at: string;
};

const MODES = ["auto", "internal", "cross_doc", "external"];

const VERDICT_LABEL: Record<string, string> = {
  SUPPORTED: "支持",
  REFUTED: "反驳",
  PARTIALLY_SUPPORTED: "部分支持",
  INSUFFICIENT_EVIDENCE: "证据不足",
  UNABLE_TO_DETERMINE: "无法判断",
  NOT_VERIFIABLE: "不可核验",
};

const KIND_LABEL: Record<string, string> = {
  FACT: "事实",
  NUMERIC: "数值",
  CAUSAL: "因果",
  PREDICTION: "预测",
  OPINION: "观点",
  REFERENCE: "引用",
};

function verdictClass(v: string): string {
  switch (v) {
    case "SUPPORTED":
      return "verdict-supported";
    case "REFUTED":
      return "verdict-refuted";
    case "PARTIALLY_SUPPORTED":
      return "verdict-partial";
    case "INSUFFICIENT_EVIDENCE":
      return "verdict-insufficient";
    default:
      return "verdict-unable";
  }
}

export default function GenericVerifyPage() {
  const [file, setFile] = useState<File | null>(null);
  const [evidenceFiles, setEvidenceFiles] = useState<File[]>([]);
  const [mode, setMode] = useState("auto");
  const [materials, setMaterials] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadHistory = useCallback(() => {
    fetch("/api/v1/generic-verify/runs?page=1&page_size=10")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => setRuns(data.runs ?? []))
      .catch((e: Error) => setHistoryError(e.message));
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      for (const ef of evidenceFiles) form.append("evidence_files", ef);
      form.append("mode", mode);
      if (materials.trim()) form.append("user_materials", materials.trim());
      const resp = await fetch("/api/v1/generic-verify", { method: "POST", body: form });
      const body = await resp.json();
      if (!resp.ok) {
        throw new Error(body?.error ? `${body.error.code}: ${body.error.message}` : `HTTP ${resp.status}`);
      }
      setResult(body as VerifyResult);
      loadHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const verdicts = result?.verdicts ?? {};
  const errs = result?.error_report ?? [];
  const claims = result?.claims ?? [];

  return (
    <main>
      <h1>通用 PDF 内容核验</h1>
      <p className="desc">
        核验任意 PDF 的内容正确性：内部自洽 / 跨文档 / 外部知识自动路由，输出五类判定与错误清单。
        <Link href="/documents"> ← 返回文档列表</Link>
      </p>

      <section className="card">
        <h2>上传并核验</h2>
        <form onSubmit={handleVerify}>
          <div className="form-row">
            <label>
              待核验 PDF（必填）
              <input type="file" accept=".pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
          </div>
          <div className="form-row">
            <label>
              证据 PDF（可选，多选，用于跨文档核验）
              <input
                type="file"
                accept=".pdf"
                multiple
                onChange={(e) => setEvidenceFiles(Array.from(e.target.files ?? []))}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              核验方式
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>
              参考资料（可选，用户提供的 ground truth 文本）
              <textarea
                value={materials}
                onChange={(e) => setMaterials(e.target.value)}
                rows={2}
                placeholder="例如：公司A 2024年营业收入 1.2 亿元…"
              />
            </label>
          </div>
          <button type="submit" disabled={!file || running}>
            {running ? "核验中…" : "开始核验"}
          </button>
          {error && <p className="bad">核验失败：{error}</p>}
        </form>
      </section>

      {result && (
        <>
          <section className="card">
            <h2>
              核验结果
              {result.run_id ? (
                <span>
                  {" "}
                  · <Link href={`/api/v1/generic-verify/runs/${result.run_id}/export`}>导出 Markdown</Link>
                </span>
              ) : null}
            </h2>
            {result.status === "FAILED" ? (
              <p className="bad">处理失败：{result.error?.message ?? "未知错误"}</p>
            ) : (
              <>
                <p className={result.is_mock ? "pending" : "good"}>
                  共 {result.total_claims} 条主张
                  {result.is_mock ? " · Mock 模式（规则拆解，无 LLM）" : " · 标准模式"}
                </p>
                <h3>判定统计</h3>
                <ul>
                  {Object.entries(verdicts).map(([k, v]) => (
                    <li key={k} className={verdictClass(k)}>
                      {VERDICT_LABEL[k] ?? k}: {v}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          {errs.length > 0 && (
            <section className="card">
              <h2>错误清单（{errs.length} 项）</h2>
              <table>
                <thead>
                  <tr>
                    <th>页码</th>
                    <th>类型</th>
                    <th>原文</th>
                    <th>详情</th>
                  </tr>
                </thead>
                <tbody>
                  {errs.map((e, i) => (
                    <tr key={i} className="verdict-refuted">
                      <td>{e.page_number}</td>
                      <td>{e.error_type}</td>
                      <td>{e.source_text.slice(0, 60)}</td>
                      <td>{e.detail.slice(0, 80)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {claims.length > 0 && (
            <section className="card">
              <h2>逐条主张（{claims.length}）</h2>
              <table>
                <thead>
                  <tr>
                    <th>页码</th>
                    <th>类型</th>
                    <th>判定</th>
                    <th>方式</th>
                    <th>原文</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  {claims.slice(0, 50).map((c) => (
                    <tr key={c.claim_id}>
                      <td>{c.page_number}</td>
                      <td>{KIND_LABEL[c.claim_kind] ?? c.claim_kind}</td>
                      <td className={verdictClass(c.verdict)}>
                        {VERDICT_LABEL[c.verdict] ?? c.verdict}
                      </td>
                      <td>{c.mode_used.join(" / ") || "-"}</td>
                      <td>{c.source_text.slice(0, 50)}</td>
                      <td>{c.reason.slice(0, 60)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {claims.length > 50 && <p className="pending">仅展示前 50 条，完整结果见导出的 Markdown。</p>}
            </section>
          )}
        </>
      )}

      <section className="card">
        <h2>核验历史</h2>
        {historyError && <p className="bad">加载失败：{historyError}</p>}
        {runs.length === 0 ? (
          <p className="pending">暂无核验记录</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>文件</th>
                <th>方式</th>
                <th>主张数</th>
                <th>状态</th>
                <th>时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{r.filename}</td>
                  <td>{r.mode}</td>
                  <td>{r.total_claims}</td>
                  <td>{r.status}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    <Link href={`/api/v1/generic-verify/runs/${r.id}/export`}>导出</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
