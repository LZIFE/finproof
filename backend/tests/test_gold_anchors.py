"""金标准锚点测试：从已复核的高风险主张中选择 5 条，验证解析层能定位其证据页。

注意：本测试只验证"解析完整性"（页面可读、非空、核心数字/关键词可找到、
页码与金标准一致），不属于证据检索或事实核验。
"""

import json
import re
from pathlib import Path

import pytest

from app.services.parser.pdf_parser import parse_pdf

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "data" / "demo" / "source"
GOLD_DIR = REPO_ROOT / "data" / "demo" / "annotations"

# 抽查锚点（来自高风险复核，页码 = PDF 物理页码 page_number）
ANCHORS = [
    ("CLM-001", "annual_report.pdf", 9, ["456,451,731", "407,149,600", "12.11%"]),
    ("CLM-005", "annual_report.pdf", 135, ["456,451,731", "335,989,528"]),
    ("CLM-009", "half_year_report.pdf", 96, ["252,331,494", "218,121,839"]),
    ("CLM-014", "annual_report.pdf", 9, ["53,345,930", "60,511,572", "-11.84%"]),
    ("CLM-019", "half_year_report.pdf", 17, ["OBM", "海外"]),
]


@pytest.fixture(scope="module")
def parsed_sources():
    """每个源文件只解析一次（模块级缓存）。"""
    return {
        "annual_report.pdf": parse_pdf((SOURCE_DIR / "annual_report.pdf").read_bytes()),
        "half_year_report.pdf": parse_pdf((SOURCE_DIR / "half_year_report.pdf").read_bytes()),
    }


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_gold_anchor_pages_are_parseable(parsed_sources):
    """锚点页面可读取且文字非空；页码与金标准一致。"""
    gold_evidence = json.loads((GOLD_DIR / "gold_evidence.json").read_text())["evidence"]
    gold_pages = {}
    for e in gold_evidence:
        if e["claim_id"] in {a[0] for a in ANCHORS}:
            gold_pages.setdefault(e["claim_id"], set()).add((e["document_name"], e["page"]))

    for claim_id, doc_name, page_no, _keywords in ANCHORS:
        parsed = parsed_sources[doc_name]
        assert 1 <= page_no <= parsed.page_count, f"{claim_id}: 页码越界"
        page = parsed.pages[page_no - 1]
        assert page.text.strip(), f"{claim_id}: 第 {page_no} 页文字为空"
        assert page.page_number == page_no
        # 页码与金标准一致
        assert (doc_name, page_no) in gold_pages.get(claim_id, set()), (
            f"{claim_id}: 页码 {doc_name} p{page_no} 与金标准不一致"
        )


def test_gold_anchor_keywords_found(parsed_sources):
    """空白字符标准化后，能找到证据中的核心数字或关键词。"""
    for claim_id, doc_name, page_no, keywords in ANCHORS:
        page = parsed_sources[doc_name].pages[page_no - 1]
        norm_text = _norm(page.text)
        for kw in keywords:
            assert _norm(kw) in norm_text, (
                f"{claim_id}: {doc_name} p{page_no} 未找到关键词 {kw}"
            )
