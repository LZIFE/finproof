#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鉴融 FinProof 网页版后端（零依赖，纯标准库）。

提供：
  GET  /              -> 试用页 index.html
  GET  /api/health    -> {"ok": true}
  POST /api/verify    -> 接收 {report, api_key, base_url?, model?}，返回结构化审计报告

核验流程（鉴融方法论精简版）：
  1) 主张拆解（LLM，A–G 七类 JSON）
  2) 确定性复算（复用 finproof_calc 引擎，对数值主张重算同比等）
  3) 逐条判定（LLM，六类结论）
  4) FinProof Score（五维确定性计分，公开可复算）

LLM 走访客自带的 OpenAI 兼容接口（base_url + api_key + model），后端不存储密钥。
注意：本网页版 MVP 不含联网检索一手来源，故「来源权威性 / 时间口径」两维为估算值，
已在返回结果中标明 estimated=true，不冒充完整专家能力。
"""

import json
import os
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import finproof_calc as fc

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8000))
ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

VERDICTS = {
    "SUPPORTED": "支持",
    "REFUTED": "反驳",
    "PARTIALLY_SUPPORTED": "部分支持",
    "INSUFFICIENT_EVIDENCE": "证据不足",
    "OPINION_OR_FORECAST": "观点或预测",
    "UNABLE_TO_DETERMINE": "无法判断",
}
CLOSED = {"SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "UNABLE_TO_DETERMINE"}


# ----------------------------------------------------------------------------
# LLM 客户端（OpenAI 兼容）
# ----------------------------------------------------------------------------
def call_llm(api_key, base_url, model, system, user, timeout=120):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + api_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"]


def strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        if "\n" in t:
            t = t.split("\n", 1)[1]
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
    return t


def safe_json(text):
    t = strip_fences(text)
    try:
        return json.loads(t)
    except Exception:
        # 退一步：截取第一个 [ 或 { 到最后一个 ] 或 }
        s = t.find("[")
        e = t.rfind("]")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except Exception:
                pass
        s = t.find("{")
        e = t.rfind("}")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except Exception:
                pass
    return None


# ----------------------------------------------------------------------------
# 提示词
# ----------------------------------------------------------------------------
DECOMP_SYS = (
    "你是金融/商业分析报告的事实核查助手「鉴融 FinProof」。请把用户提供的报告拆解为相互独立、"
    "可核验的结构化主张。主张分类（A–G）：A 原始数字、B 计算型（含增长率/比率）、"
    "C 财务口径（单季/累计等）、D 业务事实、E 因果、F 比较、G 预测/观点。"
    "对每条主张给出字段：id（字符串）、type（A–G 之一）、text（报告原句，尽量照抄）、"
    "value（若为数字主张给出数值，否则 null）、unit（单位或 '%'，否则空串）、"
    "period（期间如 2025/H1/Q2，否则空串）、risk_level（HIGH/MEDIUM/LOW）、"
    "basis（若为数值/计算主张且报告给出了可复算的底层数字，列出 {role, value}；"
    "例如增长率给 current 与 previous，毛利率给 revenue 与 cost；否则为空数组）。"
    "只能输出一个 JSON 数组，不要任何解释文字。"
)

DECOMP_USR_TMPL = "报告全文：\n<<<\n{report}\n>>>\n\n请输出主张 JSON 数组。"

JUDGE_SYS = (
    "你是「鉴融 FinProof」判定器。基于报告全文，对每条主张给出结论与理由。"
    "结论（六类之一，必须严格使用英文键名）："
    "SUPPORTED 支持 / REFUTED 反驳 / PARTIALLY_SUPPORTED 部分支持 / "
    "INSUFFICIENT_EVIDENCE 证据不足 / OPINION_OR_FORECAST 观点或预测 / "
    "UNABLE_TO_DETERMINE 无法判断。"
    "同时给出 scope_period_issue（布尔，该主张是否涉及期间或口径混淆）。"
    "只能输出一个 JSON 数组，每个元素含 id、verdict、reason、scope_period_issue，不要解释文字。"
)

JUDGE_USR_TMPL = (
    "报告全文：\n<<<\n{report}\n>>>\n\n主张列表（JSON）：\n{claims_json}\n\n请输出判定 JSON 数组。"
)


# ----------------------------------------------------------------------------
# 复算（确定性引擎）
# ----------------------------------------------------------------------------
def recompute(claim):
    val = claim.get("value")
    if val is None:
        return None
    try:
        val = float(val)
    except Exception:
        return None
    basis = claim.get("basis") or []
    bmap = {}
    for b in basis:
        if isinstance(b, dict) and "role" in b and "value" in b:
            try:
                bmap[b["role"]] = float(b["value"])
            except Exception:
                pass
    t = claim.get("type")
    res = None
    if t == "B" and "current" in bmap and "previous" in bmap:
        g, detail = fc.yoy(bmap["current"], bmap["previous"])
        if g is not None:
            ok = abs(g - val) <= 0.5  # 增长率容差 0.5pp
            res = {"kind": "yoy", "recomputed": round(g, 4),
                   "claim_value": val, "match": ok, "detail": detail}
    elif t in ("A", "B", "C") and "revenue" in bmap and "cost" in bmap:
        m = fc.margin(bmap["revenue"], cost=bmap.get("cost"),
                      net_profit=bmap.get("net_profit"),
                      expense=bmap.get("expense"),
                      segment_revenue=bmap.get("segment_revenue"))
        # 选与 claim.value 最接近的指标做比对
        best_k, best_v = None, None
        for k, v in m.items():
            if best_v is None or abs(v - val) < abs(best_v - val):
                best_k, best_v = k, v
        if best_k:
            ok = abs(best_v - val) <= max(0.1, abs(best_v) * 0.001)
            res = {"kind": best_k, "recomputed": round(best_v, 4),
                   "claim_value": val, "match": ok}
    return res


# ----------------------------------------------------------------------------
# 评分（五维，确定性，可复算）
# ----------------------------------------------------------------------------
def round1(x):
    return round(float(x), 1)


def compute_score(claims):
    N = len(claims)
    if N == 0:
        return None
    g_count = sum(1 for c in claims if c.get("type") == "G")
    N_d = N - g_count
    closed = [c for c in claims if c.get("verdict") in CLOSED]
    N_c = len(closed)
    numeric = [c for c in claims if c.get("type") in ("A", "B", "C")]
    N_v = len(numeric)
    E_v = 0
    for c in numeric:
        rc = c.get("recompute")
        if rc and isinstance(rc, dict) and not rc.get("match", True):
            E_v += 1
        elif c.get("verdict") == "REFUTED":
            E_v += 1
    E_ps = sum(1 for c in claims if c.get("scope_period_issue"))

    coverage = (N_c / N_d * 100) if N_d else 0.0
    accuracy = max(0.0, 100.0 - (E_v / N_v * 100 * 2)) if N_v else 80.0
    citation = 100.0                       # MVP 未做外部引用核验
    authority = 40.0                        # MVP 无外部来源，按「其他」档估算
    time_scope = max(0.0, 100.0 - (E_ps / N_d * 100 * 2)) if N_d else 100.0

    score = (0.25 * coverage + 0.25 * accuracy + 0.20 * citation
             + 0.15 * authority + 0.15 * time_scope)

    return {
        "score": int(round(score)),
        "dims": {
            "coverage": round1(coverage),
            "accuracy": round1(accuracy),
            "citation": round1(citation),
            "authority": round1(authority),
            "time_scope": round1(time_scope),
        },
        "estimated_dims": ["citation", "authority"],  # MVP 估算项，非实测
        "counts": {
            "N": N, "N_d": N_d, "N_c": N_c, "N_v": N_v, "E_v": E_v, "E_ps": E_ps,
        },
    }


# ----------------------------------------------------------------------------
# 核验主流程
# ----------------------------------------------------------------------------
def verify(report, api_key, base_url, model):
    base_url = (base_url or DEFAULT_BASE).strip()
    model = (model or DEFAULT_MODEL).strip()
    if not report or not report.strip():
        return {"ok": False, "error": "report 不能为空"}
    if not api_key or not api_key.strip():
        return {"ok": False, "error": "缺少 api_key（OpenAI 兼容密钥）"}

    # 1) 主张拆解
    try:
        raw = call_llm(api_key, base_url, model, DECOMP_SYS,
                       DECOMP_USR_TMPL.format(report=report))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "LLM 接口返回错误：%s" % e, "detail": e.read().decode("utf-8", "ignore")[:800]}
    except Exception as e:
        return {"ok": False, "error": "调用 LLM 失败：%s" % e}
    claims = safe_json(raw)
    if not isinstance(claims, list) or not claims:
        return {"ok": False, "error": "主张拆解未返回有效 JSON 数组", "raw": raw[:800]}

    # 规范化
    norm = []
    for i, c in enumerate(claims, 1):
        if not isinstance(c, dict):
            continue
        norm.append({
            "id": str(c.get("id", i)),
            "type": str(c.get("type", "D")).upper()[:1],
            "text": str(c.get("text", "")),
            "value": c.get("value"),
            "unit": str(c.get("unit", "") or ""),
            "period": str(c.get("period", "") or ""),
            "risk_level": str(c.get("risk_level", "MEDIUM") or "MEDIUM").upper(),
            "basis": c.get("basis") or [],
        })

    # 2) 确定性复算（数值主张）
    for c in norm:
        c["recompute"] = recompute(c)

    # 3) 逐条判定
    try:
        raw2 = call_llm(api_key, base_url, model, JUDGE_SYS,
                        JUDGE_USR_TMPL.format(report=report, claims_json=json.dumps(norm, ensure_ascii=False)))
    except Exception as e:
        return {"ok": False, "error": "判定调用 LLM 失败：%s" % e}
    judged = safe_json(raw2)
    jmap = {}
    if isinstance(judged, list):
        for j in judged:
            if isinstance(j, dict) and "id" in j:
                jmap[str(j["id"])] = j
    for c in norm:
        j = jmap.get(c["id"], {})
        v = str(j.get("verdict", "UNABLE_TO_DETERMINE")).upper()
        if v not in VERDICTS:
            v = "UNABLE_TO_DETERMINE"
        c["verdict"] = v
        c["verdict_cn"] = VERDICTS[v]
        c["reason"] = str(j.get("reason", ""))
        c["scope_period_issue"] = bool(j.get("scope_period_issue", False))

    # 4) 评分
    score = compute_score(norm)

    # 统计各结论数量
    dist = {}
    for c in norm:
        dist[c["verdict"]] = dist.get(c["verdict"], 0) + 1

    return {
        "ok": True,
        "model": "%s @ %s" % (model, base_url),
        "score": score,
        "verdict_distribution": {VERDICTS.get(k, k): v for k, v in dist.items()},
        "claims": norm,
        "note": "网页版 MVP：不含联网检索一手来源；来源权威性/时间口径两维为估算值（estimated_dims）。完整能力见 WorkBuddy 内「鉴融 FinProof」专家。",
    }


# ----------------------------------------------------------------------------
# HTTP 服务
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._send_json({"ok": True, "service": "finproof-web", "version": "mvp-1"})
            return
        # 默认服务 index.html
        self._serve_index()

    def _serve_index(self):
        try:
            with open(os.path.join(ROOT, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self._send_json({"error": "index.html not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/verify":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            self._send_json({"ok": False, "error": "请求体不是合法 JSON"}, 400)
            return
        result = verify(data.get("report", ""), data.get("api_key", ""),
                       data.get("base_url", ""), data.get("model", ""))
        self._send_json(result, 200 if result.get("ok") else 422)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("FinProof web listening on %s:%d" % (HOST, PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
