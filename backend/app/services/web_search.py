"""联网搜索 provider（可插拔）。

统一签名：search(query) -> [{"title","snippet","url"}]

支持：
- tavily : 专为 LLM 设计，免费额度，全球/英文强   https://tavily.com
- bocha  : 博查 AI 搜索，国内直连、中文好          https://open.bochaai.com
- serper : Google 结果 API                        https://serper.dev
- ddg    : DuckDuckGo，免费无 key（网络可达时兜底）
- none   : 关闭

配置从 runtime_config（前端设置页）读取，缺省回落到环境变量：
- SEARCH_PROVIDER / TAVILY_API_KEY / BOCHA_API_KEY / SERPER_API_KEY
"""

from __future__ import annotations

import logging
import os
import re
from html import unescape

import httpx

logger = logging.getLogger(__name__)

SEARCH_PRESETS = [
    {"key": "none", "name": "关闭联网搜索", "need_key": False, "docs": ""},
    {"key": "bocha", "name": "博查 Bocha（国内直连·中文好·有免费额度）", "need_key": True,
     "docs": "https://open.bochaai.com"},
    {"key": "tavily", "name": "Tavily（LLM 专用·免费 1000 次/月）", "need_key": True,
     "docs": "https://tavily.com"},
    {"key": "serper", "name": "Serper（Google 结果·2500 次免费）", "need_key": True,
     "docs": "https://serper.dev"},
    {"key": "ddg", "name": "DuckDuckGo（免费无 Key·稳定性一般）", "need_key": False, "docs": ""},
]


def _runtime() -> dict:
    try:
        from app.core.runtime_config import _read_raw

        return _read_raw()
    except Exception:  # noqa: BLE001
        return {}


def get_search_config() -> dict:
    """合并运行时配置与环境变量。"""
    rt = _runtime()
    provider = (rt.get("search_provider") or os.getenv("SEARCH_PROVIDER") or "none").strip().lower()
    api_key = rt.get("search_api_key") or ""
    if "*" in str(api_key):  # 掩码值不可用
        api_key = ""
    api_key = api_key or (
        os.getenv("BOCHA_API_KEY") if provider == "bocha"
        else os.getenv("TAVILY_API_KEY") if provider == "tavily"
        else os.getenv("SERPER_API_KEY") if provider == "serper"
        else ""
    ) or ""
    enabled = bool(rt.get("search_enabled", provider != "none"))
    max_results = int(rt.get("search_max_results") or 5)
    return {
        "provider": provider,
        "api_key": api_key,
        "enabled": enabled,
        "max_results": max_results,
    }


def is_search_ready(cfg: dict | None = None) -> bool:
    cfg = cfg or get_search_config()
    if not cfg.get("enabled") or cfg.get("provider") in ("", "none"):
        return False
    if cfg["provider"] in ("bocha", "tavily", "serper") and not cfg.get("api_key"):
        return False
    return True


def _tavily(query: str, key: str, n: int) -> list[dict]:
    resp = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": query, "max_results": n, "search_depth": "basic"},
        timeout=20, trust_env=False,
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "snippet": r.get("content", ""), "url": r.get("url", "")}
        for r in resp.json().get("results", [])
    ]


def _bocha(query: str, key: str, n: int) -> list[dict]:
    resp = httpx.post(
        "https://api.bochaai.com/v1/web-search",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": query, "count": n, "summary": True},
        timeout=20, trust_env=False,
    )
    resp.raise_for_status()
    pages = (resp.json().get("data") or {}).get("webPages") or {}
    vals = pages.get("value") or []
    return [
        {"title": r.get("name", ""), "snippet": r.get("summary") or r.get("snippet", ""),
         "url": r.get("url", "")}
        for r in vals[:n]
    ]


def _serper(query: str, key: str, n: int) -> list[dict]:
    resp = httpx.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": n},
        timeout=20, trust_env=False,
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "snippet": r.get("snippet", ""), "url": r.get("link", "")}
        for r in resp.json().get("organic", [])[:n]
    ]


def _ddg(query: str, _key: str, n: int) -> list[dict]:
    resp = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (compatible; FinProofBot/1.0)"},
        timeout=20,
        follow_redirects=True,
        trust_env=False,
    )
    resp.raise_for_status()
    html = resp.text
    out: list[dict] = []
    # 结果块：<a class="result__a" href="...">标题</a> ... <a class="result__snippet">摘要</a>
    blocks = re.findall(r'result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)result__snippet[^>]*>(.*?)</a>',
                        html, flags=re.S)
    for url, title, _mid, snippet in blocks[:n]:
        url = unescape(url)
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            from urllib.parse import unquote

            url = unquote(m.group(1))
        out.append({
            "title": unescape(re.sub(r"<[^>]+>", "", title)).strip(),
            "snippet": unescape(re.sub(r"<[^>]+>", "", snippet)).strip(),
            "url": url,
        })
    return out


_PROVIDERS = {"tavily": _tavily, "bocha": _bocha, "serper": _serper, "ddg": _ddg}


def web_search(query: str, cfg: dict | None = None) -> list[dict]:
    """统一搜索入口。失败返回 []，不抛异常（核验流程不能被搜索拖垮）。"""
    cfg = cfg or get_search_config()
    provider = cfg.get("provider", "none")
    if not query.strip() or not is_search_ready(cfg):
        return []
    fn = _PROVIDERS.get(provider)
    if fn is None:
        return []
    try:
        results = fn(query, cfg.get("api_key", ""), cfg.get("max_results", 5))
        logger.info("web_search[%s] '%s' -> %d 条", provider, query[:30], len(results))
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_search[%s] 失败: %s", provider, exc)
        return []


def get_configured_web_search():
    """返回供核验器注入的函数；未配置好时返回 None。"""
    cfg = get_search_config()
    if not is_search_ready(cfg):
        return None
    return lambda q: web_search(q, cfg)
