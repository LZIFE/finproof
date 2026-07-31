"use client";

import { useEffect, useState } from "react";

type HealthStatus = { status: string; service: string; database?: string } | null;

export default function Home() {
  const [health, setHealth] = useState<HealthStatus>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((resp) => (resp.ok ? resp.json() : Promise.reject(new Error(`HTTP ${resp.status}`))))
      .then(setHealth)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main>
      <h1>FinProof 鉴融</h1>
      <p className="tagline">核验每一项主张 · 重算每一个数字 · 追溯每一个结论</p>
      <p className="desc">金融研究报告事实核验与证据链智能体（黑客松 MVP）</p>

      <section className="status">
        {error ? (
          <p className="bad">后端状态：异常（{error}）</p>
        ) : health ? (
          <p className="good">
            后端状态：正常（{health.service} · SQLite {health.database}）
          </p>
        ) : (
          <p className="pending">后端状态：检测中…</p>
        )}
      </section>

      <p className="links">
        <a href="/documents">文档接入（上传 / 查看逐页文本）</a>
      </p>
    </main>
  );
}
