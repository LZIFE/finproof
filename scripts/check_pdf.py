#!/usr/bin/env python3
"""PDF 提取质量检查（Phase 1 候选公司筛选用，非业务核验逻辑）。

对每个 PDF 输出：页数、可提取字符数、是否文本型、含"营业收入"的页数、
表格行密度抽样、首页前 80 字。

用法：python scripts/check_pdf.py data/demo/tmp/600519_*.pdf
"""

import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

KEYWORDS = ["营业收入", "归属于上市公司股东的净利润", "经营活动产生的现金流量净额"]


def check(path: Path) -> None:
    doc = fitz.open(str(path))
    pages = len(doc)
    total_chars = 0
    keyword_pages = {k: 0 for k in KEYWORDS}
    empty_pages = []
    max_line_density = 0
    first_text = ""

    for i, page in enumerate(doc):
        text = page.get_text("text")
        chars = len(text.strip())
        total_chars += chars
        if chars < 20:
            empty_pages.append(i + 1)
        for k in KEYWORDS:
            if k in text:
                keyword_pages[k] += 1
        # 表格行密度近似：统计短行数量（表格单元格往往单行）
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if lines:
            max_line_density = max(max_line_density, len(lines))
        if i == 0:
            first_text = re.sub(r"\s+", " ", text)[:80]

    text_type = total_chars / max(pages, 1) >= 100 and not empty_pages
    print(f"{path.name}: 页数={pages} 字符={total_chars} 平均每页={total_chars // max(pages, 1)}")
    print(f"  文本型={text_type} 空页={empty_pages if empty_pages else '无'}")
    print(f"  关键词命中: " + ", ".join(f"{k}={v}页" for k, v in keyword_pages.items()))
    print(f"  最大单页行数(表格密度参考)={max_line_density}")
    print(f"  首页片段: {first_text}")
    doc.close()


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("用法: python scripts/check_pdf.py <pdf...>")
        return 1
    for p in paths:
        if not p.exists():
            print(f"文件不存在: {p}")
            return 1
        check(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
