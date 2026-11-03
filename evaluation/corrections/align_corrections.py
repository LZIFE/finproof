#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更正公告对齐解析器：pdftotext -layout 文本 → 更正对（label, before, after）。

处理三种真实结构（2024-2025 巨潮更正公告实测）：
  A. 标记行块：『更正前：』/『更正后：』各自跟一段表格 → 按出现顺序配对，
     块内逐行抽 (行标签, 数值序列)，两块行数一致时按序对齐。
  B. 行内三/四列表：表头一行含『更正前』与『更正后』（如 报表项目|更正前|影响金额|更正后），
     每行直接给 (label, before, [影响金额], after)。
  C. 敘述式：『……X 元更正为 Y 元』/『由 X 更正为 Y』。

输出统一为 dict：
  {kind, label, before, after, unit, context, line}
数值保留原始字符串（千分位/负数原样），数值化由引擎抽取层负责。
"""
from __future__ import annotations

import re

_NUM = r"-?\d[\d,]*(?:\.\d+)?"
_NUM_RE = re.compile(rf"({_NUM})\s*(元|万元|亿元|万股|万股|股|吨|%)?")
_AGG_SEARCH = re.compile(r"合计|总计|总资产|总收入|总成本|小计")
_MARK_BEFORE = re.compile(r"^\s*更正前[：:]?\s*$")
_MARK_AFTER = re.compile(r"^\s*更正后[：:]?\s*$")
_SECTION_BREAK = re.compile(r"^\s*(?:[一二三四五六七八九十]+、|\d+、|[（(]\s*[一二三四五六七八九十]+\s*[))])")
_PROSE_RE = re.compile(
    rf"([（(]?[一二三四五六七八九十\d]+[)）]?)?[^。；\n]{{0,40}}?({_NUM})\s*(元|万元|亿元|股|万股|吨)?"
    rf"[^。；\n]{{0,6}}?(?:更正为|调整为|变更为)\s*({_NUM})\s*(元|万元|亿元|股|万股|吨)?")


def _nums_in(line):
    """行内数值序列 [(value_str, unit)]；跳过纯年份与百分比序号。"""
    out = []
    for m in _NUM_RE.finditer(line):
        v = m.group(1)
        if re.match(r"^(?:19|20)\d{2}$", v):
            continue
        out.append((v, m.group(2) or ""))
    return out


def _row_label(line):
    """行标签：去掉数值/单位/括号注记后的前导文字。"""
    t = _NUM_RE.sub(" ", line)
    t = re.sub(r"[%（）()\-—一、\s]+", " ", t).strip()
    return t[:24]


def _is_noise(line):
    s = line.strip()
    if not s or s in ("单位：元", "单位：股", "单位：万元"):
        return True
    if re.match(r"^\s*[-\s|:：+]+$',?\s*$", s):
        return True
    return False


def block_rows(block_lines, stop=None):
    """块 → [(line_no, label, [数值...])]；遇段落断行/stop 行号即停。"""
    rows = []
    for ln, line in block_lines:
        if stop is not None and ln >= stop:
            break
        if _is_noise(line):
            continue
        nums = _nums_in(line)
        if not nums:
            continue
        rows.append((ln, _row_label(line), nums))
    return rows


def _rank_artifact(nums, idx):
    """序号/排名列判定：该位置是无单位 1..99 整数，且同行还有别的数值（≥3 列）。"""
    v, u = nums[idx]
    if u or not re.match(r"^\d{1,2}$", v):
        return False
    return len(nums) >= 3


def parse_inline_table(lines):
    """结构 B：表头含更正前+更正后 的行内表。"""
    out = []
    for i, line in enumerate(lines):
        if "更正前" in line and "更正后" in line and i + 1 < len(lines):
            for j in range(i + 1, min(i + 40, len(lines))):
                s = lines[j].strip()
                if not s or _SECTION_BREAK.match(s) or "更正事项" in s:
                    break
                nums = _nums_in(s)
                label = _row_label(s)
                if len(nums) >= 2 and label:
                    if len(nums) == 2:
                        out.append({"kind": "inline", "label": label,
                                    "before": nums[0][0], "after": nums[1][0],
                                    "unit": nums[1][1] or nums[0][1], "line": j + 1})
                    else:
                        # 含影响金额列：取首末两数
                        out.append({"kind": "inline", "label": label,
                                    "before": nums[0][0], "after": nums[-1][0],
                                    "unit": nums[-1][1] or nums[0][1], "line": j + 1})
    return out


def parse_prose(lines):
    """结构 C：敘述式 更正为。"""
    out = []
    for i, line in enumerate(lines):
        for m in _PROSE_RE.finditer(line):
            out.append({"kind": "prose", "label": _row_label(line[:m.start()]) or m.group(1) or "正文数值",
                        "before": m.group(2), "after": m.group(4),
                        "unit": m.group(5) or m.group(3) or "", "line": i + 1})
    return out


def parse_file(txt_path):
    """整文件解析 → 更正对列表（去重）。"""
    with open(txt_path, encoding="utf-8") as f:
        lines = [(i + 1, l.rstrip()) for i, l in enumerate(f.readlines())]
    bare = [l for _n, l in lines]
    items = []

    # A：标记行块
    marks = []
    for n, l in lines:
        if _MARK_BEFORE.match(l):
            marks.append((n, "before"))
        elif _MARK_AFTER.match(l):
            marks.append((n, "after"))
    k = 0
    while k + 1 < len(marks):
        (i1, t1), (i2, t2) = marks[k], marks[k + 1]
        if t1 == "before" and t2 == "after":
            nxt = marks[k + 2][0] if k + 2 < len(marks) else (lines[-1][0] + 1)
            b_rows = block_rows(lines[i1:i2 - 1])
            a_rows = block_rows(lines[i2:nxt - 1])
            # 标签对齐为主抽取器：更正后表常按新值重排（供应商/客户排名变动），
            # 行序不可信而"标签↔行"绑定可信。位置对齐实测会把重排行错配，
            # 只用作参考不作为采纳条件（详见套件 README 的对齐质量节）。
            from collections import defaultdict
            gb, ga = defaultdict(list), defaultdict(list)
            for ln, lab, nums in b_rows:
                gb[lab].append((ln, nums))
            for ln, lab, nums in a_rows:
                ga[lab].append((ln, nums))
            for lab, blist in gb.items():
                alist = ga.get(lab) or []
                if len(blist) != len(alist):
                    continue  # 出现次数不等：结构不一致，整组放弃（不硬配）
                for (lb, nb), (la, na) in zip(blist, alist):
                    if len(nb) != len(na):
                        continue  # 数值个数不等：换行/列错位，放弃该行
                    for k2, ((vb, ub), (va, ua)) in enumerate(zip(nb, na)):
                        if vb == va:
                            continue
                        # 序号/排名伪影：两侧都是无单位 1..99 整数且行内多列
                        if _rank_artifact(nb, k2) and _rank_artifact(na, k2):
                            continue
                        # 千分位合法性：逗号必须按 3 位分组（"64,72" 是换列碎片）
                        if not all(re.match(r"^\d{1,3}(,\d{3})*(\.\d+)?$", v.replace("-", "")) or
                                   re.match(r"^-?\d+(\.\d+)?$", v)
                                   for v in (vb, va)):
                            continue
                        # 跨列错配 sanity：小数(<10) ↔ 巨数(>10,000) 的对
                        # （如 1.07% ↔ 1,377,175 股）几乎必是换行错列，弃
                        fb, fa = float(vb.replace(",", "")), float(va.replace(",", ""))
                        if fb and fa and max(abs(fb), abs(fa)) / min(abs(fb), abs(fa)) > 1000:
                            continue
                        items.append({"kind": "block", "label": lab,
                                      "before": vb, "after": va,
                                      "unit": ua or ub, "line": la})
            k += 2
        else:
            k += 1

    # 重排污染检测：block 对的 after 值若等于文档内其他行的 before 值，
    # 说明两表行序不一致（供应商/股东表按新值重排），位置对齐不可信——
    # 该文档全部 block 对弃用（宁缺毋滥，不产出错误对齐）。
    # （v2：改用双抽取器共识，此污染门已由共识门取代）

    items += parse_inline_table(bare)
    items += parse_prose(bare)

    # 去重（同一 before/after/label 组合只留一条）
    seen, out = set(), []
    for it in items:
        key = (it["label"], it["before"], it["after"])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        pairs = parse_file(p)
        print(f"== {p}: {len(pairs)} 对")
        for it in pairs[:8]:
            print(f"   L{it['line']:3} [{it['kind']}] {it['label'][:18]:18} "
                  f"{it['before']} → {it['after']} {it['unit']}")
