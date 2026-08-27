"""大模型配置 API（前端设置页）。

- GET  /api/v1/llm-settings           当前有效配置（脱敏）+ 可选模式
- GET  /api/v1/llm-settings/presets   各家大模型端点预设
- PUT  /api/v1/llm-settings           保存配置（api_key 留空表示不改）
- POST /api/v1/llm-settings/test      用当前/提交配置发一次极简请求，验证连通性
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.runtime_config import (
    PROVIDER_PRESETS,
    get_effective_settings,
    is_llm_ready,
    load_runtime_config,
    public_settings,
    save_runtime_config,
)

router = APIRouter(tags=["llm-settings"])


class LLMSettingsPayload(BaseModel):
    preset: str | None = None
    claim_extraction_mode: str | None = None
    claim_extraction_provider: str | None = None
    claim_extraction_model: str | None = None
    claim_extraction_base_url: str | None = None
    claim_extraction_api_key: str | None = None
    claim_extraction_timeout_seconds: int | None = None
    claim_extraction_max_retries: int | None = None
    llm_temperature: float | None = None


@router.get("/api/v1/llm-settings")
def get_llm_settings() -> dict:
    """返回当前生效配置（api_key 脱敏）与可选模式。"""
    return public_settings()


@router.get("/api/v1/llm-settings/presets")
def get_presets() -> dict:
    """各家 OpenAI 兼容大模型的地址与推荐模型预设。"""
    return {"presets": PROVIDER_PRESETS}


@router.put("/api/v1/llm-settings")
def put_llm_settings(payload: LLMSettingsPayload) -> dict:
    """保存配置；返回保存后的脱敏状态。"""
    save_runtime_config(payload.model_dump(exclude_none=True))
    return public_settings()


@router.post("/api/v1/llm-settings/test")
def test_llm_settings(payload: LLMSettingsPayload | None = None) -> dict:
    """发一次最小请求验证配置是否可用。

    若请求体带了配置，先用它临时测试（不保存）；否则用已保存配置。
    """
    if payload is not None and payload.model_dump(exclude_none=True):
        # 临时合并：保存一份再读回有效配置，测完恢复原文件
        import json

        from app.core import runtime_config as rc

        original = rc._read_raw()  # noqa: SLF001
        try:
            merged = {**original, **payload.model_dump(exclude_none=True)}
            # 测试时 api_key 若为掩码则沿用原值
            if merged.get("claim_extraction_api_key") and "*" in str(merged["claim_extraction_api_key"]):
                merged["claim_extraction_api_key"] = original.get("claim_extraction_api_key", "")
            rc.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            rc.CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
            cfg = get_effective_settings()
            return _do_test(cfg)
        finally:
            rc.CONFIG_PATH.write_text(
                json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return _do_test(get_effective_settings())


def _do_test(cfg) -> dict:
    missing = []
    if not cfg.claim_extraction_base_url:
        missing.append("接口地址 base_url")
    if not cfg.claim_extraction_api_key:
        missing.append("API Key")
    if not cfg.claim_extraction_model:
        missing.append("模型名称 model")
    if missing:
        return {"ok": False, "error": f"缺少必填项：{'、'.join(missing)}"}

    url = f"{cfg.claim_extraction_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg.claim_extraction_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": cfg.claim_extraction_model,
        "messages": [
            {"role": "system", "content": "You are a connectivity test. Reply with: ok"},
            {"role": "user", "content": "ping"},
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    started = time.monotonic()
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=20)
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code != 200:
            snippet = resp.text[:300]
            return {
                "ok": False,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "error": f"接口返回 {resp.status_code}：{snippet}",
            }
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "model": data.get("model", cfg.claim_extraction_model),
            "reply": str(reply)[:80],
            "llm_ready": is_llm_ready(cfg),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"连接失败：{exc}"}
