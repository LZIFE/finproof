#!/usr/bin/env python3
"""从交易所官方披露 API 下载上市公司定期报告 PDF（数据准备工具，非业务核验逻辑）。

数据源优先级：
1. 深交所 API：POST http://www.szse.cn/api/disc/announcement/annList（已验证可用）
2. 上交所 API：GET  http://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do（尽力而为）

用法示例：
  python scripts/download_cninfo.py --code 000333 --market szse --name 美的集团 \
      --patterns "2025年年度报告" "2025年第一季度报告" "2025年半年度报告" \
      --outdir data/demo/tmp
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SZSE_LIST_URL = "http://www.szse.cn/api/disc/announcement/annList?random=0.123"
SZSE_DOWNLOAD = "http://disc.static.szse.cn/download{path}"
SSE_LIST_URL = (
    "http://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do?{params}"
)
SSE_DOWNLOAD = "https://static.sse.com.cn{path}"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _request(url: str, data: bytes | None = None, referer: str = "") -> bytes:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def list_szse(code: str, start: str, end: str) -> list[dict]:
    body = json.dumps(
        {
            "seDate": [start, end],
            "channelCode": ["fixed_disc"],
            "pageSize": 50,
            "pageNum": 1,
            "stock": [code],
            "searchkey": "",
            "plate": "",
            "category": "",
        }
    ).encode("utf-8")
    payload = json.loads(_request(SZSE_LIST_URL, data=body, referer="http://www.szse.cn/"))
    return payload.get("data") or []


def list_sse(code: str, start: str, end: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "jsonCallBack": "cb",
            "isPagination": "true",
            "productId": code,
            "keyWord": "",
            "securityType": "0101,120100,020100,020200,120200",
            "reportType2": "",
            "reportType": "",
            "beginDate": start,
            "endDate": end,
            "pageHelp.pageSize": "25",
            "pageHelp.pageCount": "50",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": "5",
        }
    )
    raw = _request(SSE_LIST_URL.format(params=params), referer="http://www.sse.com.cn/")
    text = raw.decode("utf-8", errors="replace")
    m = re.search(r"cb\((.*)\)\s*$", text, re.S)
    payload = json.loads(m.group(1) if m else text)
    return payload.get("result") or []


def pick(items: list[dict], title_key: str, pattern: str):
    rx = re.compile(re.escape(pattern))
    matched = [a for a in items if rx.search(a.get(title_key, ""))]
    if not matched:
        return None
    for a in matched:
        if "摘要" not in a.get(title_key, ""):
            return a
    return matched[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="下载交易所官方定期报告 PDF")
    ap.add_argument("--code", required=True)
    ap.add_argument("--market", choices=["szse", "sse"], required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--outdir", default="data/demo/tmp")
    ap.add_argument("--patterns", nargs="+", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.market == "szse":
        items = list_szse(args.code, args.start, args.end)
        title_key = "title"
        download_url = lambda a: SZSE_DOWNLOAD.format(path=a["attachPath"])
    else:
        items = list_sse(args.code, args.start, args.end)
        title_key = "title"
        download_url = lambda a: SSE_DOWNLOAD.format(path=a["attachUrl"])

    print(f"== {args.name}({args.code}/{args.market}) 共 {len(items)} 条公告 ==")
    ok = True
    for pattern in args.patterns:
        hit = pick(items, title_key, pattern)
        if hit is None:
            print(f"  [缺失] 未找到包含 '{pattern}' 的公告")
            ok = False
            continue
        title = hit.get(title_key, "")
        url = download_url(hit)
        safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", pattern)
        dest = outdir / f"{args.code}_{safe}.pdf"
        try:
            data = _request(url, referer="http://www.szse.cn/" if args.market == "szse" else "http://www.sse.com.cn/")
            dest.write_bytes(data)
            print(f"  [下载] {title}  {len(data) / 1024:.0f}KB  -> {dest.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [失败] {title} : {exc}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
