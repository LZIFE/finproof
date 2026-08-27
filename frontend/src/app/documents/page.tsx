"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type DocumentRow = {
  id: number;
  original_filename: string;
  document_type: string;
  document_role: string;
  page_count: number;
  parse_status: string;
  parse_error: string | null;
  sha256: string;
  created_at: string;
};

const ROLES = ["SOURCE_DOCUMENT", "REPORT_TO_VERIFY", "REFERENCE_REPORT"];

const ROLE_LABELS: Record<string, string> = {
  SOURCE_DOCUMENT: "官方披露原件（年报/公告 PDF，作为核验证据）",
  REPORT_TO_VERIFY: "待核验报告（研报/资料，需要被检查的文件）",
  REFERENCE_REPORT: "第三方参考资料（行业报告/媒体报道）",
};

const STATUS_LABEL: Record<string, string> = {
  PENDING: "待解析",
  PARSING: "解析中",
  COMPLETED: "已完成",
  FAILED: "失败",
  UNSUPPORTED: "不支持",
};

export default function DocumentsPage() {
  const [file, setFile] = useState<File | null>(null);
  const [role, setRole] = useState<string>("REPORT_TO_VERIFY");
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetch("/api/v1/documents?page=1&page_size=50")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => setDocuments(data.documents))
      .catch((e: Error) => setListError(e.message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("document_role", role);
      const resp = await fetch("/api/v1/documents", { method: "POST", body: form });
      const body = await resp.json();
      if (!resp.ok) {
        throw new Error(
          body?.error ? `${body.error.code}: ${body.error.message}` : `HTTP ${resp.status}`
        );
      }
      const d = body.document;
      setUploadResult(
        `${body.duplicate ? "重复文件（已存在）" : "上传成功"}：${d.original_filename} ` +
          `→ 状态 ${STATUS_LABEL[d.parse_status] ?? d.parse_status}，页数 ${d.page_count}`
      );
      refresh();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <main>
      <h1>文档接入</h1>
      <p className="desc">上传 PDF 研究报告 / 财报证据或 Markdown 报告，系统按页解析并保留页码。</p>

      <section className="card">
        <h2>上传文档</h2>
        <form onSubmit={handleUpload}>
          <div className="form-row">
            <label>
              文件（.pdf / .md / .markdown）
              <input
                type="file"
                accept=".pdf,.md,.markdown"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              文档角色
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r] ?? r}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button type="submit" disabled={!file || uploading}>
            {uploading ? "上传中…" : "上传"}
          </button>
          {uploadResult && <p className="good">{uploadResult}</p>}
          {uploadError && <p className="bad">上传失败：{uploadError}</p>}
        </form>
      </section>

      <section className="card">
        <h2>文档列表</h2>
        {listError && <p className="bad">加载失败：{listError}</p>}
        {documents.length === 0 ? (
          <p className="pending">暂无文档</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>文件名</th>
                <th>角色</th>
                <th>类型</th>
                <th>页数</th>
                <th>状态</th>
                <th>上传时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.id}>
                  <td>{d.original_filename}</td>
                  <td>{ROLE_LABELS[d.document_role] ?? d.document_role}</td>
                  <td>{d.document_type}</td>
                  <td>{d.page_count}</td>
                  <td>
                    {STATUS_LABEL[d.parse_status] ?? d.parse_status}
                    {d.parse_error && <span className="bad">（{d.parse_error}）</span>}
                  </td>
                  <td>{new Date(d.created_at).toLocaleString()}</td>
                  <td>
                    <Link href={`/documents/${d.id}`}>查看</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <p>
        <Link href="/settings/llm">⚙ 大模型接口设置</Link> ·{" "}
        <Link href="/generic-verify">⚡ 通用 PDF 内容核验（任意文档）</Link> ·{" "}
        <Link href="/">返回首页</Link>
      </p>
    </main>
  );
}
