#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鉴融专家包一致性检查（v2.6.2）。

背景：包内文档曾出现 4 处漏同步与"九臂"数字错（人工同步遗漏）。本脚本把
包一致性从"人肉 grep + 验收子代理"变成一键全检。

用法：
    python3 check_package.py            # 在 finproof-verifier/ 目录（或其父目录）下运行
退出码：0 = 全部通过；1 = 存在 FAIL。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE if os.path.basename(HERE) == "finproof-verifier" else os.path.join(HERE, "finproof-verifier")
SKILL = os.path.join(ROOT, "skills", "finproof-verification")
DEMO = os.path.normpath(os.path.join(ROOT, "..", "audit_template_demo_76.html"))
ZIP = os.path.normpath(os.path.join(ROOT, "..", "finproof-verifier.zip"))

RESULTS: list[tuple[str, str, str]] = []  # (status, check, detail)


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def add(status: str, name: str, detail: str = ""):
    RESULTS.append((status, name, detail))


def check(cond: bool, name: str, fail_detail: str = "", ok_detail: str = "OK"):
    add("PASS" if cond else "FAIL", name, ok_detail if cond else fail_detail)


def strip_changelog(text: str) -> str:
    """剥掉 README「版本与变更」节——历史条目记录的是'当时如此、后来已修'，
    其中出现旧口径字样属合法历史，不参与现行一致性检查。"""
    idx = text.find("## 十三、版本与变更")
    return text[:idx] if idx >= 0 else text


# 1. 版本一致
def check_versions():
    plugin = read(os.path.join(ROOT, ".codebuddy-plugin", "plugin.json"))
    try:
        v_plugin = json.loads(plugin)["version"] if plugin else ""
    except json.JSONDecodeError:
        v_plugin = ""
    m = re.search(r"^version:\s*(\S+)", read(os.path.join(SKILL, "SKILL.md")), re.M)
    v_skill = m.group(1) if m else ""
    m2 = re.search(r"^# FinProof 轻量执行卡（LITE · (v[\d.]+)）", read(os.path.join(SKILL, "LITE.md")), re.M)
    v_lite_raw = m2.group(1) if m2 else ""
    v_lite = v_lite_raw.lstrip("v")
    readme = read(os.path.join(ROOT, "README.md"))
    v_in_readme = bool(re.search(rf"^- \*\*v?{re.escape(v_skill)}\*\*：", readme, re.M))
    check(bool(v_plugin) and v_plugin == v_skill, "版本一致：plugin.json == SKILL frontmatter", f"plugin={v_plugin} skill={v_skill}")
    check(v_lite == v_skill, "版本一致：LITE 标题版本同步", f"lite={v_lite} skill={v_skill}")
    check(v_in_readme, f"README 变更记录含 v{v_skill} 条目")


# 2. 档位行格式（全部含"预测事实化 x"）
def check_grade_lines():
    targets = [
        ("SKILL.md §8.4", read(os.path.join(SKILL, "SKILL.md"))),
        ("scoring-spec.md §五", read(os.path.join(SKILL, "references", "scoring-spec.md"))),
        ("audit-report-template.md", read(os.path.join(SKILL, "references", "audit-report-template.md"))),
        ("演示件", read(DEMO)),
    ]
    bad = []
    for name, text in targets:
        for m in re.finditer(r"问题项[^\n]{0,40}?（反驳 x[^\n]*", text):
            if "预测事实化" not in m.group(0):
                bad.append(f"{name}: {m.group(0)[:60]}")
    check(not bad, "档位行强制格式均含『预测事实化 x』", "; ".join(bad[:3]))


# 3. 审计结论排序枚举
def check_conclusion_enum():
    files = {
        "SKILL.md": read(os.path.join(SKILL, "SKILL.md")),
        "audit-report-template.md": read(os.path.join(SKILL, "references", "audit-report-template.md")),
        "agent MD": read(os.path.join(ROOT, "agents", "finproof-verifier.md")),
        "README.md": strip_changelog(read(os.path.join(ROOT, "README.md"))),
    }
    bad = []
    for name, text in files.items():
        for m in re.finditer(r"反驳\s*[>＞]\s*证据不足\s*[>＞]\s*部分支持\s*[>＞]\s*无法判断(?!\s*[>＞]\s*预测事实化)", text):
            bad.append(name)
    check(not bad, "审计结论排序枚举含『预测事实化』", f"缺:{bad}")


# 4. 独立复核四档
def check_review_tiers():
    files = {
        "SKILL.md §六": read(os.path.join(SKILL, "SKILL.md")),
        "independent-review.md": read(os.path.join(SKILL, "references", "independent-review.md")),
        "audit-report-template.md": read(os.path.join(SKILL, "references", "audit-report-template.md")),
        "agent MD": read(os.path.join(ROOT, "agents", "finproof-verifier.md")),
    }
    bad = [n for n, t in files.items() if "自检复核" not in t]
    check(not bad, "独立复核四档（含自检复核〔机械层〕）", f"缺:{bad}")
    check("三档" not in read(os.path.join(SKILL, "references", "independent-review.md")).replace("四档", ""),
          "无『三档』残留（独立复核语境）")


# 5. N_e 口径
def check_ne_rule():
    for name, path in [("SKILL.md", os.path.join(SKILL, "SKILL.md")),
                       ("audit-report-template.md", os.path.join(SKILL, "references", "audit-report-template.md")),
                       ("演示件", DEMO)]:
        t = read(path)
        check("逐字一致，免引擎" in t or "不计入 N_e" in t, f"N_e 口径已落：{name}")


# 6. LITE 关键内容
def check_lite():
    lite = read(os.path.join(SKILL, "LITE.md"))
    check(bool(lite), "LITE.md 存在")
    for kw in ["0.1%", "0.5pp", "判定校准", "时序不可能", "temporal", "时点漂移", "G 类", "逐字摘录"]:
        check(kw in lite, f"LITE 含关键内容：{kw}")
    check("只读本目录 `LITE.md`" in read(os.path.join(SKILL, "SKILL.md")), "SKILL §0.1 快速档指向 LITE.md")


# 7. temporal 引擎
def check_engine():
    eng = os.path.join(SKILL, "bin", "finproof_calc.py")
    t = read(eng)
    check("def temporal_check" in t and "IMPOSSIBLE" in t, "引擎含 temporal 子命令")
    for name, path in [("SKILL.md", os.path.join(SKILL, "SKILL.md")), ("LITE.md", os.path.join(SKILL, "LITE.md")),
                       ("agent MD", os.path.join(ROOT, "agents", "finproof-verifier.md"))]:
        check("temporal" in read(path), f"{name} 同步 temporal 命令")
    r = subprocess.run([sys.executable, eng, "temporal", "--source", "2025年年度报告", "--data", "2026年上半年"],
                       capture_output=True, text=True)
    check('"IMPOSSIBLE"' in r.stdout, "temporal CLI 冒烟：E5 原型判 IMPOSSIBLE", r.stdout[:80])


# 8. 引擎回归测试
def check_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", os.path.join(SKILL, "bin", "test_finproof_calc.py"), "-q"],
                       capture_output=True, text=True, cwd=os.path.join(SKILL, "bin"))
    check("passed" in r.stdout and "failed" not in r.stdout.split("passed")[0],
          "引擎回归测试全绿", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[:80])


# 9. 算例计数自洽（audit-report-template + 演示件）
def check_worked_example():
    for name, path in [("audit-report-template.md", os.path.join(SKILL, "references", "audit-report-template.md")),
                       ("演示件", DEMO)]:
        t = read(path)
        ok_rows = ("#7" in t and "预测事实化" in t and "其余 5 条" in t
                   and re.search(r"问题项 4 条（反驳 1 / 证据不足 1 / 部分支持 1 / 无法判断 0 / 预测事实化 1", t)
                   and "一致 7 条" in t)
        check(bool(ok_rows), f"算例计数自洽（问题项4/其余5/一致7）：{name}")


# 10. 陈旧标记
def check_stale_markers():
    alltext = ""
    for dirpath, _dirs, files in os.walk(ROOT):
        if ".pytest_cache" in dirpath:
            continue
        for fn in files:
            if not fn.endswith((".md", ".json", ".py")):
                continue
            p = os.path.join(dirpath, fn)
            if os.path.exists(__file__) and os.path.samefile(p, __file__):
                continue  # 检查器自身含标记字样，跳过
            t = read(p)
            alltext += strip_changelog(t) if fn == "README.md" else t
    for marker in ["九臂", "五类结论", "八字段", "证据覆盖率」维度"]:
        check(marker not in alltext, f"无陈旧标记：{marker}")


# 10.5 审计质量分 AQS（v2.7.0）
def check_aqs():
    for name, path in [("SKILL.md", os.path.join(SKILL, "SKILL.md")),
                       ("scoring-spec.md", os.path.join(SKILL, "references", "scoring-spec.md")),
                       ("LITE.md", os.path.join(SKILL, "LITE.md")),
                       ("audit-report-template.md", os.path.join(SKILL, "references", "audit-report-template.md")),
                       ("演示件", DEMO),
                       ("agent MD", os.path.join(ROOT, "agents", "finproof-verifier.md")),
                       ("README.md", os.path.join(ROOT, "README.md"))]:
        check("审计质量分 AQS" in read(path), f"AQS 已落：{name}")
    demo = read(DEMO)
    check("AQS 94" in demo, "演示件 AQS 算例为 94（并列展示）")


# 10.7 引擎-文档同步（v2.8.0）：parser 注册的子命令必须出现在 SKILL/LITE 速查
def check_engine_doc_sync():
    import ast
    eng = os.path.join(SKILL, "bin", "finproof_calc.py")
    tree = ast.parse(read(eng))
    cmds = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_parser":
            if node.args and isinstance(node.args[0], ast.Constant):
                cmds.add(node.args[0].value)
    skill = read(os.path.join(SKILL, "SKILL.md"))
    lite = read(os.path.join(SKILL, "LITE.md"))
    missing_skill = sorted(c for c in cmds if c not in skill)
    check(not missing_skill, f"引擎子命令({len(cmds)})全部见于 SKILL 速查", f"缺:{missing_skill}")
    # LITE 是快速档最小卡：只要求三项硬检查+通用复算核心子命令（全量表在 SKILL，属有意精简）
    lite_core = {"match", "yoy", "quarter", "margin", "sum_check", "temporal", "convert"}
    missing_lite = sorted(c for c in lite_core if c not in lite)
    check(not missing_lite, "LITE 含快速档核心子命令（7 个）", f"缺:{missing_lite}")


# 11. zip 新旧提醒
def check_zip_freshness():
    if not os.path.exists(ZIP):
        add("WARN", "zip 存在性", "finproof-verifier.zip 不存在（如需交付请打包）")
        return
    zip_mtime = os.path.getmtime(ZIP)
    stale = []
    for dirpath, _dirs, files in os.walk(ROOT):
        if ".pytest_cache" in dirpath:
            continue
        for fn in files:
            p = os.path.join(dirpath, fn)
            if os.path.getmtime(p) > zip_mtime:
                stale.append(os.path.relpath(p, ROOT))
    if stale:
        add("WARN", "zip 新旧", f"{len(stale)} 个文件比 zip 新，需重新打包：{stale[:3]}")
    else:
        add("PASS", "zip 新旧", "zip 比包内全部文件新")


def main():
    for fn in (check_versions, check_grade_lines, check_conclusion_enum, check_review_tiers,
               check_ne_rule, check_lite, check_engine, check_tests, check_worked_example,
               check_stale_markers, check_aqs, check_engine_doc_sync, check_zip_freshness):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            add("FAIL", fn.__name__, f"检查器异常: {e}")
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    warns = [r for r in RESULTS if r[0] == "WARN"]
    for status, name, detail in RESULTS:
        mark = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}[status]
        line = f"{mark} [{status}] {name}"
        if status != "PASS" or os.environ.get("VERBOSE"):
            line += f" —— {detail}"
        print(line)
    print(f"\n合计 {len(RESULTS)} 项：PASS {len(RESULTS)-len(fails)-len(warns)} · FAIL {len(fails)} · WARN {len(warns)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
