"""backend/tests/test_generic_verification/test_claim_extraction.py"""
from app.services.generic_verification.claim_extraction import (
    classify_kind,
    extract_cross_refs,
    extract_dates,
    extract_entities,
    extract_numbers,
    mark_candidate_blocks,
)


def test_extract_numbers_percent_and_thousands():
    nums = extract_numbers("同比增长 30%，营收 1,200 万元")
    assert any(n["value"] == 30 and n["unit"] == "%" for n in nums)
    assert any(n["value"] == 1200 and n["unit"] == "万" for n in nums)


def test_extract_numbers_skips_scientific_notation():
    """科学计数法（1e18）不得被误提取为整数部分（1）（P2 回归）。"""
    nums = extract_numbers("总资产 1e18 元，负债 2.5E-3 元")
    assert not any(n["value"] == 1 for n in nums)
    assert not any(n["value"] == 2.5 for n in nums)


def test_extract_dates():
    dates = extract_dates("2024年3月15日发布，年报期间为2024年，披露于2024-03-15")
    assert "2024年3月15日" in dates
    assert "2024年" in dates
    assert "2024-03-15" in dates


def test_extract_cross_refs():
    refs = extract_cross_refs("详见第 3 章及图 2-1，另见附录A")
    assert any("第 3 章" in r for r in refs)
    assert any("图 2-1" in r for r in refs)
    assert any("附录A" in r for r in refs)


def test_classify_kind():
    assert classify_kind("预计明年营收增长") == "PREDICTION"
    assert classify_kind("我们认为该方案可行") == "OPINION"
    assert classify_kind("主要由于成本下降导致") == "CAUSAL"
    assert classify_kind("营收 1.2 亿元") == "NUMERIC"
    assert classify_kind("公司成立于 2001 年") == "FACT"


def test_extract_entities():
    ents = extract_entities("华为技术有限公司发布新款手机，关于产能的说明")
    assert "华为技术有限公司" in ents
    assert "关于" not in ents


def test_mark_candidate_blocks():
    blocks = [
        {"index": 0, "text": "第一章 概述", "block_type": "heading"},
        {"index": 1, "text": "公司成立于 2001 年", "block_type": "paragraph"},
        {"index": 2, "text": "本项目没有需要核验的信息", "block_type": "paragraph"},
    ]
    marked = mark_candidate_blocks(blocks)
    assert 1 in marked
    assert 0 not in marked
    assert 2 not in marked
