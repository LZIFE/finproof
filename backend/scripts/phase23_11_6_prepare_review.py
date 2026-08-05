"""Phase 23.11.6 Review Pack Preparer (Task 2).

Generates offline blind review package for 32 HUMAN_REVIEW_REQUIRED evidence:
- review.html (offline page, NO expected_verdict / prediction / gold labels)
- review_items.json
- review_results.template.json
- review_progress.json
- review_instructions.md

Run: cd backend && PYTHONPATH=. python scripts/phase23_11_6_prepare_review.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import load_canonical_claims
from app.db import SessionLocal
from app.models import DocumentBlock

REVIEW_DIR = BACKEND.parent / "data" / "gold_review" / "phase23_11_6"
AUDIT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_1_grounding_audit.json"

# First-round review must NOT expose these
BLINDED_FIELDS = ("expected_verdict", "prediction", "selected_by_system", "is_gold", "agent_recommendation")


def main() -> int:
    claims, _ = load_canonical_claims()
    claim_by_id = {c.claim_id: c for c in claims}
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).order_by(
            DocumentBlock.document_id, DocumentBlock.page_id, DocumentBlock.block_index).all()
    finally:
        session.close()
    block_by_id = {str(b.id): b for b in all_blocks}
    blocks_by_page: dict = {}
    for b in all_blocks:
        blocks_by_page.setdefault(b.page_id, []).append(b)

    # Only HUMAN_REVIEW_REQUIRED entries (32)
    items = []
    for p in audit["per_evidence"]:
        if p["new_status"] != "HUMAN_REVIEW_REQUIRED":
            continue
        cid = p["claim_id"]
        cc = claim_by_id.get(cid)
        cand_ids = p.get("candidate_block_ids", []) or []
        groups = []
        # Up to 5 candidate groups, no duplicates, in original order
        seen = set()
        for bid in cand_ids:
            if bid in seen:
                continue
            seen.add(bid)
            if len(groups) >= 5:
                break
            b = block_by_id.get(bid)
            if not b:
                continue
            page_blocks = blocks_by_page.get(b.page_id, [])
            idx = next((i for i, x in enumerate(page_blocks) if str(x.id) == bid), None)
            before = str(page_blocks[idx - 1].text or "")[:200] if (idx is not None and idx > 0) else ""
            after = str(page_blocks[idx + 1].text or "")[:200] if (idx is not None and idx < len(page_blocks) - 1) else ""
            groups.append({
                "candidate_group_id": f"{p['gold_evidence_id']}-g{len(groups) + 1}",
                "document_id": b.document_id,
                "page": b.page_id,
                "block_ids": [bid],
                "reconstructed_text": str(b.text or "")[:400],
                "context_before": before,
                "context_after": after,
                "reconstruction_coverage": round(p.get("reconstruction_coverage", 0.0), 4),
                "number_match": False,
                "metric_match": "UNKNOWN",
                "period_match": "UNKNOWN",
                "unit_match": "UNKNOWN",
                "company_match": "UNKNOWN",
            })
        # First-round item: NO expected_verdict / prediction / gold
        items.append({
            "item_id": p["gold_evidence_id"],
            "claim_id": cid,
            "claim_text": str(cc.claim_text if cc else "")[:300],
            "company": str(cc.company if cc else ""),
            "report_name": "annual_report" if (cc.dataset if cc else "") == "demo" else "holdout_report",
            "dataset": cc.dataset if cc else "",
            "gold_evidence_text": p["evidence_text"][:300],
            "candidate_groups": groups,
            "reviewer_choice": "",
            "selected_block_ids": [],
            "evidence_complete": "",
            "reviewer_note": "",
            "review_status": "PENDING",
        })

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # review_items.json
    (REVIEW_DIR / "review_items.json").write_text(
        json.dumps({"phase": "23.11.6", "total": len(items), "items": items},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # review_results.template.json (reviewer fills this)
    template = {
        "phase": "23.11.6",
        "instructions": "Fill reviewer_choice / selected_block_ids / evidence_complete / reviewer_note for each item. DO NOT touch other fields.",
        "items": [{k: ("" if k.startswith("reviewer") else ([] if k == "selected_block_ids" else v))
                   for k, v in it.items()} for it in items],
    }
    (REVIEW_DIR / "review_results.template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")

    # review_progress.json
    (REVIEW_DIR / "review_progress.json").write_text(
        json.dumps({"phase": "23.11.6", "total": len(items), "reviewed": 0, "pending": len(items),
                    "last_updated": ""}, ensure_ascii=False, indent=2), encoding="utf-8")

    # review_instructions.md
    (REVIEW_DIR / "review_instructions.md").write_text(_instructions(), encoding="utf-8")

    # review.html (offline, no JS framework; first round blind)
    (REVIEW_DIR / "review.html").write_text(_build_html(items), encoding="utf-8")

    print(f"Review pack written to {REVIEW_DIR}")
    print(f"  items: {len(items)}")
    print(f"  files: review.html / review_items.json / review_results.template.json / review_progress.json / review_instructions.md")
    return 0


def _instructions() -> str:
    return """# 第一轮盲审说明（Evidence Alignment）

## 你的任务
对每条 Gold Evidence 文本，判断哪（些）候选 Block 真正对应它。

## 可选答案
- MATCH_SINGLE_BLOCK: 单个 Block 完全对应
- MATCH_MULTIPLE_BLOCKS: 多个相邻 Block 共同对应
- NONE_OF_THE_ABOVE: 候选都不对应
- UNSURE: 无法确定

## 必填字段
- selected_block_ids: 你确认的 Block ID 列表
- evidence_complete: yes / no（候选是否完整包含 Gold Evidence 全部内容）
- reviewer_note: 你的判断依据

## 注意
- 页面不显示 expected_verdict / 系统预测 / Gold 标签，避免影响你的判断。
- 相同 Block 不会重复出现。
- 只能选择页面提供的候选，不要自行臆测。
"""


def _build_html(items) -> str:
    """Interactive offline review page: navigation, form, export, resume, blind."""
    # Serialize items as JSON data (embedded, no external resources)
    items_json = json.dumps(items, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>Phase 23.11.6 Gold Evidence 盲审包（交互式）</title>
<style>
body {{ font-family: sans-serif; max-width: 900px; margin: 20px auto; padding: 0 20px; }}
#nav {{ display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }}
#nav button {{ padding: 8px 16px; font-size: 15px; }}
#progressbar {{ height: 6px; background: #eee; border-radius: 3px; margin-bottom: 16px; }}
#progressbar > div {{ height: 100%; background: #4caf50; width: 0%; border-radius: 3px; }}
.item {{ border: 1px solid #ccc; border-radius: 8px; padding: 16px; }}
.candidate {{ border-left: 4px solid #888; margin: 10px 0; padding: 8px 12px; background: #fafafa; }}
.candidate.selected {{ border-left-color: #4caf50; background: #e8f5e9; }}
.gold {{ background: #fff8e1; border: 1px solid #e0c; padding: 8px 12px; }}
.block {{ background: #e8f5e9; padding: 8px 12px; margin: 6px 0; }}
.ctx {{ background: #f3e5f5; padding: 6px 10px; margin: 4px 0; font-size: 0.9em; }}
label {{ display: block; margin: 6px 0; }}
input[type=text], textarea, select {{ width: 100%; padding: 6px; font-size: 14px; }}
.btnrow {{ margin-top: 14px; display: flex; gap: 10px; }}
#exportbtn {{ background: #1976d2; color: #fff; border: none; padding: 10px 20px; font-size: 15px; border-radius: 4px; cursor: pointer; }}
#savebtn {{ background: #388e3c; color: #fff; border: none; padding: 10px 20px; font-size: 15px; border-radius: 4px; cursor: pointer; }}
.notice {{ background: #fff3e0; border: 1px solid #ffb74d; padding: 8px 12px; margin: 10px 0; font-size: 14px; }}
</style></head><body>
<h1>Phase 23.11.6 Gold Evidence 盲审包（第一轮：Evidence Alignment）</h1>
<div class="notice">本页已隐藏金标准判定与系统预测标签。共 {len(items)} 条。<b>建议先审核完一部分后点击「保存进度」，可随时刷新继续。</b>全部完成后点击「导出JSON」下载结果文件。</div>
<div id="progressbar"><div id="progressfill"></div></div>
<div id="nav">
  <button id="prevbtn">← 上一条</button>
  <span id="counter">1 / {len(items)}</span>
  <button id="nextbtn">下一条 →</button>
  <span id="statuslabel" style="margin-left:10px;color:#666;"></span>
</div>
<div id="itemcontainer" class="item"></div>
<div class="btnrow">
  <button id="savebtn">💾 保存进度（本地）</button>
  <button id="exportbtn">📤 导出JSON</button>
</div>
<div id="exportinfo" class="notice" style="display:none;"></div>
<script>
var ITEMS = {items_json};
var state = JSON.parse(localStorage.getItem('fp_review_state') || '{{"idx":0,"answers":{{}}}}');
var idx = state.idx || 0;

function render() {{
  var it = ITEMS[idx];
  var ans = state.answers[it.item_id] || {{'choice':'','blocks':[],'complete':'','note':''}};
  var h = '<h3>Evidence: ' + it.item_id + ' (claim ' + it.claim_id + ')</h3>';
  h += '<p><b>公司:</b> ' + it.company + ' &nbsp; <b>报告:</b> ' + it.report_name + ' &nbsp; <b>数据集:</b> ' + it.dataset + '</p>';
  h += '<p><b>Claim文本:</b> ' + it.claim_text + '</p>';
  h += '<div class="gold"><b>原Gold Evidence文本:</b><br>' + it.gold_evidence_text + '</div>';
  // Candidate groups with checkbox
  h += '<h4>候选Block（勾选你认为对应的候选组）</h4>';
  for (var gi = 0; gi < it.candidate_groups.length; gi++) {{
    var g = it.candidate_groups[gi];
    var cid = it.item_id + '-g' + gi;
    var checked = (ans.blocks.indexOf(g.candidate_group_id) >= 0) ? 'checked' : '';
    h += '<div class="candidate" id="' + cid + '">';
    h += '<label><input type="checkbox" data-g="' + g.candidate_group_id + '" ' + checked + ' onchange="toggleGroup(this)"> <b>候选组 ' + g.candidate_group_id + '</b></label>';
    h += '<p><b>document_id:</b> ' + g.document_id + ' &nbsp; <b>page:</b> ' + g.page + ' &nbsp; <b>block_ids:</b> ' + JSON.stringify(g.block_ids) + '</p>';
    h += '<div class="block"><b>候选原文:</b><br>' + g.reconstructed_text + '</div>';
    h += '<div class="ctx"><b>前一个Block:</b><br>' + g.context_before + '</div>';
    h += '<div class="ctx"><b>后一个Block:</b><br>' + g.context_after + '</div>';
    h += '<p><b>重建覆盖率:</b> ' + g.reconstruction_coverage + ' &nbsp; <b>匹配方式:</b> fuzzy</p>';
    h += '</div>';
  }}
  // Choice radios
  h += '<h4>审核选择</h4>';
  var choices = ['MATCH_SINGLE_BLOCK','MATCH_MULTIPLE_BLOCKS','NONE_OF_THE_ABOVE','UNSURE'];
  for (var ci = 0; ci < choices.length; ci++) {{
    var chk = (ans.choice == choices[ci]) ? 'checked' : '';
    h += '<label><input type="radio" name="choice" value="' + choices[ci] + '" ' + chk + ' onchange="setChoice(this.value)"> ' + choices[ci] + '</label>';
  }}
  h += '<label><b>evidence_complete:</b> <select id="complete" onchange="setComplete(this.value)"><option value="">-- 选择 --</option><option value="yes" ' + (ans.complete=='yes'?'selected':'') + '>yes</option><option value="no" ' + (ans.complete=='no'?'selected':'') + '>no</option></select></label>';
  h += '<label><b>reviewer_note:</b> <textarea id="note" rows="3" onchange="setNote(this.value)">' + (ans.note||'') + '</textarea></label>';
  document.getElementById('itemcontainer').innerHTML = h;
  document.getElementById('counter').textContent = (idx+1) + ' / ' + ITEMS.length;
  var done = Object.keys(state.answers).length;
  document.getElementById('progressfill').style.width = (done / ITEMS.length * 100) + '%';
  document.getElementById('statuslabel').textContent = '已完成 ' + done + ' / ' + ITEMS.length;
  // enable/disable nav
  document.getElementById('prevbtn').disabled = (idx <= 0);
  document.getElementById('nextbtn').disabled = (idx >= ITEMS.length - 1);
}}

function save() {{
  localStorage.setItem('fp_review_state', JSON.stringify(state));
  alert('进度已保存到浏览器本地。导出时请用「导出JSON」下载结果文件。');
}}

function toggleGroup(cb) {{
  var it = ITEMS[idx];
  var ans = state.answers[it.item_id] || {{'choice':'','blocks':[],'complete':'','note':''}};
  var gid = cb.getAttribute('data-g');
  if (cb.checked) {{ if (ans.blocks.indexOf(gid) < 0) ans.blocks.push(gid); }}
  else {{ ans.blocks = ans.blocks.filter(function(x){{return x != gid;}}); }}
  state.answers[it.item_id] = ans;
}}

function setChoice(v) {{
  var it = ITEMS[idx];
  var ans = state.answers[it.item_id] || {{'choice':'','blocks':[],'complete':'','note':''}};
  ans.choice = v; state.answers[it.item_id] = ans;
}}

function setComplete(v) {{
  var it = ITEMS[idx];
  var ans = state.answers[it.item_id] || {{'choice':'','blocks':[],'complete':'','note':''}};
  ans.complete = v; state.answers[it.item_id] = ans;
}}

function setNote(v) {{
  var it = ITEMS[idx];
  var ans = state.answers[it.item_id] || {{'choice':'','blocks':[],'complete':'','note':''}};
  ans.note = v; state.answers[it.item_id] = ans;
}}

function exportJSON() {{
  var items_out = [];
  var today = new Date().toISOString().slice(0,10);
  for (var i = 0; i < ITEMS.length; i++) {{
    var it = ITEMS[i];
    var ans = state.answers[it.item_id] || {{'choice':'','blocks':[],'complete':'','note':''}};
    // collect selected block_ids from candidate groups
    var sel = [];
    for (var gi = 0; gi < it.candidate_groups.length; gi++) {{
      if (ans.blocks.indexOf(it.candidate_groups[gi].candidate_group_id) >= 0) {{
        sel = sel.concat(it.candidate_groups[gi].block_ids);
      }}
    }}
    items_out.push({{
      'item_id': it.item_id,
      'claim_id': it.claim_id,
      'claim_text': it.claim_text,
      'company': it.company,
      'report_name': it.report_name,
      'dataset': it.dataset,
      'gold_evidence_text': it.gold_evidence_text,
      'candidate_groups': it.candidate_groups,
      'reviewer_choice': ans.choice,
      'selected_block_ids': sel,
      'evidence_complete': ans.complete,
      'reviewer_note': ans.note,
      'reviewed_at': today,
      'review_status': (ans.choice ? 'REVIEWED' : 'PENDING')
    }});
  }}
  var blob = new Blob([JSON.stringify({{'phase':'23.11.6','total':ITEMS.length,'items':items_out}}, null, 2)], {{type:'application/json'}});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'review_results.json';
  a.click();
  var info = document.getElementById('exportinfo');
  info.style.display = 'block';
  info.innerHTML = '<b>已下载 review_results.json。</b>请将文件移动到 <code>data/gold_review/phase23_11_6/review_results.json</code>，然后执行导入命令（见 quickstart 第7步）。';
}}

document.getElementById('prevbtn').addEventListener('click', function(){{ if (idx>0) {{ idx--; render(); }} }});
document.getElementById('nextbtn').addEventListener('click', function(){{ if (idx<ITEMS.length-1) {{ idx++; render(); }} }});
document.getElementById('savebtn').addEventListener('click', save);
document.getElementById('exportbtn').addEventListener('click', exportJSON);
render();
</script>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())