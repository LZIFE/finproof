"""运行时大模型配置（可在前端设置页修改，无需改代码/重启/写 .env）。

设计：
- 用户在前端填写的配置持久化到 ``data/llm_config.json``（已 gitignore，不入库、不进 git）。
- ``get_effective_settings()`` 返回一份"环境默认值 + 前端覆盖值"合并后的 Settings，
  供 LLM Provider 使用；未配置时自动回落到 mock，不报错。
- API Key 只在本机文件与请求内存中出现；对外读取时脱敏。
"""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path

from app.core.config import BASE_DIR, Settings, get_settings

CONFIG_PATH = BASE_DIR / "data" / "llm_config.json"
_LOCK = threading.Lock()

# 可被前端覆盖的字段（白名单，避免任意写入）
_OVERRIDABLE = {
    "claim_extraction_mode",
    "claim_extraction_provider",
    "claim_extraction_model",
    "claim_extraction_base_url",
    "claim_extraction_api_key",
    "claim_extraction_timeout_seconds",
    "claim_extraction_max_retries",
    "llm_temperature",
}

# 各家大模型的 OpenAI 兼容端点预设（选厂商后自动带出地址与推荐模型）
PROVIDER_PRESETS: list[dict] = [
    {
        "key": "deepseek",
        "name": "DeepSeek（深度求索）",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "docs": "https://platform.deepseek.com/api_keys",
    },
    {
        "key": "qwen",
        "name": "通义千问 Qwen（阿里云百炼）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"],
        "default_model": "qwen-plus",
        "docs": "https://bailian.console.aliyun.com/",
    },
    {
        "key": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4-flash", "glm-4.5", "glm-4-air"],
        "default_model": "glm-4-plus",
        "docs": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    {
        "key": "kimi",
        "name": "Kimi 月之暗面",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "default_model": "moonshot-v1-32k",
        "docs": "https://platform.moonshot.cn/console/api-keys",
    },
    {
        "key": "doubao",
        "name": "豆包 / 火山方舟",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": [],
        "default_model": "",
        "docs": "https://console.volcengine.com/ark/region:ark+cn-beijing/endpoint",
        "model_hint": "火山方舟用「接入点 ID」(ep-xxx) 作为模型名",
    },
    {
        "key": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"],
        "default_model": "deepseek-ai/DeepSeek-V3",
        "docs": "https://cloud.siliconflow.cn/account/ak",
    },
    {
        "key": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"],
        "default_model": "gpt-4o-mini",
        "docs": "https://platform.openai.com/api-keys",
    },
    {
        "key": "ollama",
        "name": "本地 Ollama（免费/本机）",
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen2.5:7b", "llama3.1:8b"],
        "default_model": "qwen2.5:7b",
        "docs": "https://ollama.com/",
        "model_hint": "需先在本机 ollama pull 对应模型；API Key 随意填",
    },
    {
        "key": "custom",
        "name": "自定义（任意 OpenAI 兼容接口）",
        "base_url": "",
        "models": [],
        "default_model": "",
        "docs": "",
    },
]

PRESET_BY_KEY = {p["key"]: p for p in PROVIDER_PRESETS}

_EXTRACTION_MODES = {
    "mock": "Mock 规则（离线，无需 Key）",
    "rules": "纯规则（离线）",
    "llm": "大模型直接提取（需配置 Key）",
    "hybrid": "规则 + 大模型混合（省 Token，推荐）",
}


def _read_raw() -> dict:
    """读取前端保存的原始配置；文件不存在/损坏时返回空 dict。"""
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_runtime_config() -> dict:
    """读取已保存的配置（api_key 脱敏后返回，供前端展示）。"""
    raw = _read_raw()
    out = {k: raw.get(k) for k in _OVERRIDABLE if k in raw}
    key = out.get("claim_extraction_api_key") or ""
    out["claim_extraction_api_key"] = _mask_key(key)
    out["has_api_key"] = bool(key)
    out["preset"] = raw.get("preset", "custom")
    return out


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def save_runtime_config(payload: dict) -> dict:
    """校验并保存配置。api_key 传空/脱敏值时保留原 Key（便于只改模型不改 Key）。"""
    with _LOCK:
        current = _read_raw()
        cleaned: dict = {}

        mode = payload.get("claim_extraction_mode", current.get("claim_extraction_mode", "mock"))
        if mode not in _EXTRACTION_MODES:
            mode = "mock"
        cleaned["claim_extraction_mode"] = mode

        provider = str(payload.get("claim_extraction_provider") or "openai_compatible")
        cleaned["claim_extraction_provider"] = provider

        model = str(payload.get("claim_extraction_model") or "").strip()
        base_url = str(payload.get("claim_extraction_base_url") or "").strip().rstrip("/")
        cleaned["claim_extraction_model"] = model
        cleaned["claim_extraction_base_url"] = base_url

        # api_key：空串或仍是掩码（含 *）表示不修改
        key = str(payload.get("claim_extraction_api_key") or "")
        if key and "*" not in key:
            cleaned["claim_extraction_api_key"] = key
        elif current.get("claim_extraction_api_key"):
            cleaned["claim_extraction_api_key"] = current["claim_extraction_api_key"]
        else:
            cleaned["claim_extraction_api_key"] = ""

        if "claim_extraction_timeout_seconds" in payload:
            try:
                cleaned["claim_extraction_timeout_seconds"] = max(
                    5, min(300, int(payload["claim_extraction_timeout_seconds"]))
                )
            except (TypeError, ValueError):
                pass
        if "claim_extraction_max_retries" in payload:
            try:
                cleaned["claim_extraction_max_retries"] = max(0, min(5, int(payload["claim_extraction_max_retries"])))
            except (TypeError, ValueError):
                pass

        cleaned["llm_temperature"] = payload.get("llm_temperature", current.get("llm_temperature", 0))
        cleaned["preset"] = str(payload.get("preset") or current.get("preset") or "custom")

        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return cleaned


def get_effective_settings() -> Settings:
    """环境默认值 + 前端覆盖值，合并出一份有效 Settings（不污染全局 lru_cache）。"""
    base = get_settings()
    raw = _read_raw()
    updates = {k: raw[k] for k in _OVERRIDABLE if k in raw and raw[k] not in (None, "")}
    if not updates:
        return base
    try:
        return base.model_copy(update=updates)
    except Exception:  # noqa: BLE001 —— 覆盖值异常时安全回落到环境配置
        return base


def is_llm_ready(settings: Settings | None = None) -> bool:
    """是否已具备真实调用大模型的三要素。"""
    cfg = settings or get_effective_settings()
    return bool(
        cfg.claim_extraction_base_url
        and cfg.claim_extraction_api_key
        and cfg.claim_extraction_model
        and cfg.claim_extraction_mode in ("llm", "hybrid")
    )


def public_settings() -> dict:
    """供前端展示的当前有效状态（脱敏）。"""
    cfg = get_effective_settings()
    raw = _read_raw()
    return {
        "mode": cfg.claim_extraction_mode,
        "mode_label": _EXTRACTION_MODES.get(cfg.claim_extraction_mode, cfg.claim_extraction_mode),
        "provider": cfg.claim_extraction_provider,
        "model": cfg.claim_extraction_model,
        "base_url": cfg.claim_extraction_base_url,
        "has_api_key": bool(cfg.claim_extraction_api_key),
        "api_key_preview": _mask_key(cfg.claim_extraction_api_key),
        "timeout_seconds": cfg.claim_extraction_timeout_seconds,
        "max_retries": cfg.claim_extraction_max_retries,
        "temperature": raw.get("llm_temperature", 0),
        "preset": raw.get("preset", "custom"),
        "llm_ready": is_llm_ready(cfg),
        "modes": [{"key": k, "label": v} for k, v in _EXTRACTION_MODES.items()],
    }
