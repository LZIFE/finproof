"use client";

import { useCallback, useEffect, useState } from "react";

type Preset = {
  key: string;
  name: string;
  base_url: string;
  models: string[];
  default_model: string;
  docs?: string;
  model_hint?: string;
};

type Settings = {
  mode: string;
  mode_label: string;
  provider: string;
  model: string;
  base_url: string;
  has_api_key: boolean;
  api_key_preview: string;
  timeout_seconds: number;
  max_retries: number;
  temperature: number;
  preset: string;
  llm_ready: boolean;
  modes: { key: string; label: string }[];
};

export default function LLMSettingsPage() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [cfg, setCfg] = useState<Settings | null>(null);
  const [preset, setPreset] = useState("custom");
  const [mode, setMode] = useState("mock");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeoutSec, setTimeoutSec] = useState(60);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    fetch("/api/v1/llm-settings")
      .then((r) => r.json())
      .then((d: Settings) => {
        setCfg(d);
        setPreset(d.preset || "custom");
        setMode(d.mode);
        setBaseUrl(d.base_url);
        setModel(d.model);
        setTimeoutSec(d.timeout_seconds);
      });
    fetch("/api/v1/llm-settings/presets")
      .then((r) => r.json())
      .then((d) => setPresets(d.presets || []));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const currentPreset = presets.find((p) => p.key === preset);
  const modelOptions = currentPreset?.models ?? [];

  const applyPreset = (key: string) => {
    setPreset(key);
    const p = presets.find((x) => x.key === key);
    if (p) {
      if (p.base_url) setBaseUrl(p.base_url);
      if (p.default_model) setModel(p.default_model);
    }
  };

  const payload = () => ({
    preset,
    claim_extraction_mode: mode,
    claim_extraction_provider: "openai_compatible",
    claim_extraction_base_url: baseUrl.trim(),
    claim_extraction_model: model.trim(),
    claim_extraction_api_key: apiKey.trim(),
    claim_extraction_timeout_seconds: timeoutSec,
  });

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const resp = await fetch("/api/v1/llm-settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      const d = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(d));
      setApiKey("");
      setCfg(d);
      setMsg({
        ok: true,
        text: d.llm_ready
          ? "已保存，真实大模型已就绪，去文档页提取主张时选择 llm/hybrid 模式即可。"
          : "已保存（当前为离线模式或信息未填全）。",
      });
    } catch (e) {
      setMsg({ ok: false, text: `保存失败：${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setMsg(null);
    try {
      const resp = await fetch("/api/v1/llm-settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      const d = await resp.json();
      if (d.ok) {
        setMsg({
          ok: true,
          text: `连接成功（${d.latency_ms}ms）· 模型 ${d.model} · 回复「${d.reply}」`,
        });
      } else {
        setMsg({ ok: false, text: d.error || "连接失败" });
      }
    } catch (e) {
      setMsg({ ok: false, text: `测试失败：${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setTesting(false);
    }
  };

  return (
    <main className="page">
      <h1>大模型接口设置</h1>
      <p className="desc">
        配置一家支持 OpenAI 兼容接口的大模型，主张提取即可用真实 AI（替代离线 Mock）。
        API Key 只保存在本机，不入库、不上传 Git。
      </p>

      {cfg && (
        <p className={cfg.llm_ready ? "good" : "pending"}>
          当前状态：{cfg.llm_ready ? "✅ 真实模型已就绪" : "⚪ 离线 Mock 模式"}
          {cfg.has_api_key && !apiKey ? `（Key：${cfg.api_key_preview}）` : ""}
        </p>
      )}

      <section className="card">
        <h2>第一步：选择服务商</h2>
        <div className="form-row">
          <label>
            大模型厂商
            <select value={preset} onChange={(e) => applyPreset(e.target.value)} style={{ width: 360 }}>
              {presets.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {currentPreset?.docs && (
          <p className="muted">
            需要先在服务商处申请 API Key：
            <a href={currentPreset.docs} target="_blank" rel="noreferrer">
              {currentPreset.docs}
            </a>
          </p>
        )}

        <h2>第二步：填写参数</h2>
        <div className="form-row">
          <label>
            接口地址 Base URL
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} style={{ width: 420 }} placeholder="https://api.xxx.com/v1" />
          </label>
        </div>
        <div className="form-row">
          <label>
            API Key
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              style={{ width: 420 }}
              placeholder={cfg?.has_api_key ? "已配置，留空表示不修改" : "sk-..."}
              autoComplete="off"
            />
          </label>
        </div>
        <div className="form-row">
          <label>
            模型名称 Model
            <input value={model} onChange={(e) => setModel(e.target.value)} style={{ width: 300 }} list="model-options" placeholder="模型名 / 接入点ID" />
            <datalist id="model-options">
              {modelOptions.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </label>
          {currentPreset?.model_hint && <span className="muted"> {currentPreset.model_hint}</span>}
        </div>
        <div className="form-row">
          <label>
            超时（秒）
            <input
              type="number"
              value={timeoutSec}
              onChange={(e) => setTimeoutSec(Number(e.target.value))}
              style={{ width: 90 }}
              min={5}
              max={300}
            />
          </label>
        </div>

        <h2>第三步：选择提取方式</h2>
        <div className="form-row">
          <label>
            主张提取模式
            <select value={mode} onChange={(e) => setMode(e.target.value)} style={{ width: 360 }}>
              {(cfg?.modes || []).map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="form-row" style={{ marginTop: 12 }}>
          <button onClick={test} disabled={testing || saving}>
            {testing ? "测试中…" : "测试连接"}
          </button>
          <button onClick={save} disabled={saving || testing} style={{ marginLeft: 10 }}>
            {saving ? "保存中…" : "保存配置"}
          </button>
        </div>
        {msg && <p className={msg.ok ? "good" : "bad"}>{msg.text}</p>}
      </section>

      <section className="card">
        <h2>怎么用</h2>
        <ol className="muted" style={{ lineHeight: 1.8 }}>
          <li>选厂商 → 填 Key 和模型 → 点「测试连接」确认能通；</li>
          <li>点「保存配置」，状态变成「真实模型已就绪」；</li>
          <li>去「文档接入」上传研报（角色选待核验报告）→ 文档页提取主张时选择 <b>llm</b> 或 <b>hybrid</b> 模式；</li>
          <li>提取出的主张再去「核验」页逐条核验、查看来源链。</li>
        </ol>
      </section>

      <p>
        <a href="/documents">← 去文档接入</a> · <a href="/">返回首页</a>
      </p>
    </main>
  );
}
