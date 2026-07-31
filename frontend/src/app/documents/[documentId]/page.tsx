"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

type PageListItem = {
  page_number: number;
  character_count: number;
  is_empty: boolean;
  text_preview: string;
};

type Block = {
  block_index: number;
  block_type: string;
  text: string | null;
  x0: number | null;
  y0: number | null;
  x1: number | null;
  y1: number | null;
  reading_order: number;
  heading_level: number | null;
  start_line: number | null;
  end_line: number | null;
};

type PageDetail = {
  page_index: number;
  page_number: number;
  printed_page_label: string | null;
  character_count: number;
  text: string;
  blocks: Block[];
};

export default function DocumentViewPage() {
  const params = useParams<{ documentId: string }>();
  const documentId = params.documentId;

  const [pages, setPages] = useState<PageListItem[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<PageDetail | null>(null);
  const [showBlocks, setShowBlocks] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPages = useCallback(() => {
    fetch(`/api/v1/documents/${documentId}/pages`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: { pages: PageListItem[] }) => {
        setPages(data.pages);
        if (data.pages.length > 0) setSelected(data.pages[0].page_number);
      })
      .catch((e: Error) => setError(e.message));
  }, [documentId]);

  useEffect(() => {
    loadPages();
  }, [loadPages]);

  useEffect(() => {
    if (selected === null) return;
    fetch(`/api/v1/documents/${documentId}/pages/${selected}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [documentId, selected]);

  return (
    <main>
      <h1>文档查看</h1>
      <p className="desc">
        文档 ID：{documentId} ｜ 页码体系：PDF 物理页码 page_number（1 基）
      </p>
      {error && <p className="bad">加载失败：{error}</p>}

      <section className="card">
        <h2>选择页面（共 {pages.length} 页）</h2>
        <div className="page-picker">
          {pages.map((p) => (
            <button
              key={p.page_number}
              className={selected === p.page_number ? "active" : ""}
              onClick={() => setSelected(p.page_number)}
              title={`字符数 ${p.character_count}`}
            >
              {p.page_number}
            </button>
          ))}
        </div>
      </section>

      {detail && (
        <section className="card">
          <h2>
            第 {detail.page_number} 页
            <span className="muted">
              ｜ 物理页码 page_number={detail.page_number}（page_index={detail.page_index}）
              ｜ 字符数 {detail.character_count}
              ｜ printed_page_label={detail.printed_page_label ?? "null"}
            </span>
          </h2>
          <label className="inline-check">
            <input
              type="checkbox"
              checked={showBlocks}
              onChange={(e) => setShowBlocks(e.target.checked)}
            />
            显示文本块边界信息
          </label>
          <pre className="page-text">{detail.text || "（本页无文本）"}</pre>
          {showBlocks && (
            <table>
              <thead>
                <tr>
                  <th>index</th>
                  <th>类型</th>
                  <th>坐标 (x0,y0)-(x1,y1)</th>
                  <th>阅读顺序</th>
                  <th>行号</th>
                  <th>文本</th>
                </tr>
              </thead>
              <tbody>
                {detail.blocks.map((b) => (
                  <tr key={b.block_index}>
                    <td>{b.block_index}</td>
                    <td>{b.block_type}</td>
                    <td>
                      {b.x0 !== null && b.y0 !== null && b.x1 !== null && b.y1 !== null
                        ? `(${b.x0.toFixed(1)},${b.y0.toFixed(1)})-(${b.x1.toFixed(1)},${b.y1.toFixed(1)})`
                        : "—"}
                    </td>
                    <td>{b.reading_order}</td>
                    <td>{b.start_line !== null ? `${b.start_line}-${b.end_line}` : "—"}</td>
                    <td className="block-text">{(b.text ?? "").slice(0, 60)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <p>
        <Link href="/documents">← 返回文档列表</Link>
      </p>
    </main>
  );
}
