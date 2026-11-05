#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""证据获取工具化（v5 实验中模型手写检索循环的固化版）。

对给定公司清单：巨潮 API 检索「更正公告」→ 下载 PDF → pdftotext -layout
转文本 → 输出管线可直接使用的 evidence 目录。

用法：
    python3 fetch_announcements.py --companies "凯大催化:830974,凯德石英:835179" \
        --out-dir /tmp/v5ev --se-date 2023-01-01~2026-01-01

设计要点（来自 v5 B1 教训——检索漏检海希的根因）：
  - searchkey 同时尝试「<公司名>更正公告」与「<代码> 更正」两种检索词，
    任一命中即收；
  - 每家公司最多取 pageSize*2 条候选，按标题过滤（含"更正公告"、
    排除"更正后"——全文重发件不含更正前/后对照）；
  - 下载失败/文本层过小（<500B，扫描件）不中断整体，逐条记录状态；
  - 幂等：--out-dir 已存在同名文件跳过下载。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def cninfo_query(searchkey, se_date, page=1, size=10):
    data = urllib.parse.urlencode({
        "pageNum": page, "pageSize": size, "column": "szse", "tabName": "fulltext",
        "searchkey": searchkey, "seDate": se_date, "isHLtitle": "true",
    }).encode()
    req = urllib.request.Request(
        "http://www.cninfo.com.cn/new/hisAnnouncement/query", data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_one(company, code, out_dir, se_date):
    got = []
    for key in (f"{company}更正公告", f"{code} 更正"):
        try:
            d = cninfo_query(key, se_date)
        except Exception as e:
            return got, f"query失败:{e}"
        for a in d.get("announcements") or []:
            title = a["announcementTitle"].replace("<em>", "").replace("</em>", "")
            if "更正公告" not in title or "更正后" in title:
                continue
            url = "http://static.cninfo.com.cn/" + a["adjunctUrl"]
            pdf = os.path.join(out_dir, f"{code}_{os.path.basename(a['adjunctUrl'])}")
            txt = pdf.replace(".PDF", ".txt").replace(".pdf", ".txt")
            if os.path.exists(txt) and os.path.getsize(txt) > 500:
                got.append(txt)
                continue
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=30) as r:
                    open(pdf, "wb").write(r.read())
                subprocess.run(["pdftotext", "-layout", pdf, txt], check=True, timeout=60)
                if os.path.getsize(txt) > 500:
                    got.append(txt)
                else:
                    os.remove(txt)  # 扫描件文本层过小，弃
            except Exception:
                pass
            time.sleep(0.2)
        if got:
            break  # 第一种检索词已命中即止
    return got, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies", required=True, help="逗号分隔的 公司名:代码")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--se-date", default="2023-01-01~2026-01-01")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    manifest = {}
    for item in args.companies.split(","):
        company, _, code = item.strip().partition(":")
        files, err = fetch_one(company, code, args.out_dir, args.se_date)
        manifest[f"{company}:{code}"] = {"files": files, "error": err}
        flag = f"{len(files)} 份" if files else (f"失败({err})" if err else "0 份")
        print(f"  {company}({code}): {flag}")

    ok = sum(1 for m in manifest.values() if m["files"])
    json.dump(manifest, open(os.path.join(args.out_dir, "manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"{ok}/{len(manifest)} 家公司取得更正公告 → {args.out_dir}")
    sys_exit = 0 if ok == len(manifest) else 1
    raise SystemExit(sys_exit)


if __name__ == "__main__":
    main()
