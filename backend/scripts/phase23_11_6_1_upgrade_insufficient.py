"""Phase 23.11.6.1 Intentional Insufficient interactive form page (Task 7).

Creates an offline form page so reviewers don't hand-edit JSON:
- data/gold_review/phase23_11_6/insufficient_review.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import load_canonical_claims
from app.services.evaluation_cohorts import get_evidence_by_claim

OUT_PATH = BACKEND.parent / "data" / "gold_review" / "phase23_11_6" / "insufficient_review.html"
REVIEW_JSON = BACKEND.parent / "data" / "gold_review" / "phase23_11_6" / "insufficient_review.json"

CLAIM_IDS = ["CLM-021", "CLM-022", "CLM-H17"]


def main() -> int:
    claims, _ = load_canonical_claims()
    claim_by_id = {c.claim_id: c for c in claims}
    ev_by = get_evidence_by_claim()

    items = []
    for cid in CLAIM_IDS:
        cc = claim_by_id.get(cid)
        items.append({
            "claim_id": cid,
            "claim_text": str(cc.claim_text if cc else "")[:300],
            "expected_verdict": cc.expected_verdict if cc else "INSUFFICIENT_EVIDENCE",
            "document_scope": "annual_report" if (cc.dataset if cc else "") == "demo" else "holdout_report",
            "evidence_count": len(ev_by.get(cid, [])),
            "reviewer_confirmed_insufficient": "",
            "reviewer_rationale": "",
            "reviewer_name": "",
            "reviewed_at": "",
            "review_status": "PENDING",
        })

    items_json = json.dumps([{k: v for k, v in it.items() if k != "expected_verdict"} for it in items], ensure_ascii=False)
    html = _build(items_json)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")

    # Also refresh insufficient_review.json with empty human fields + example note
    review = {
        "phase": "23.11.6",
        "description": "Intentional Insufficient审核协议（3条）。请在 insufficient_review.html 表单中填写，或只修改本JSON中 reviewer_ 开头字段。",
        "instructions": "每条只需确认：reviewer_confirmed_insufficient(yes/no)、reviewer_rationale、reviewer_name、reviewed_at。其他字段不得修改。",
        "total": len(items),
        "items": items,
    }
    REVIEW_JSON.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    leaks = [w for w in ("expected_verdict", "SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED",
                         "INSUFFICIENT_EVIDENCE", "prediction", "is_gold") if w in html]
    print(f"insufficient_review.html regenerated ({len(html)} bytes, {len(items)} items)")
    print(f"insufficient_review.json refreshed (human fields empty)")
    print(f"leaks: {leaks if leaks else 'none'}")
    return 0


def _build(items_json: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>Phase 23.11.6 Intentional Insufficient 审核</title>
<style>
body {{ font-family: sans-serif; max-width: 800px; margin: 20px auto; padding: 0 20px; }}
.item {{ border:1px solid #ccc; border-radius:8px; padding:16px; margin-bottom:20px; }}
label {{ display:block; margin:8px 0; }}
textarea, input[type=text] {{ width:100%; padding:6px; }}
#exportbtn {{ background:#1976d2; color:#fff; border:none; padding:10px 20px; border-radius:4px; cursor:pointer; }}
.notice {{ background:#fff3e0; border:1px solid #ffb74d; padding:8px 12px; margin:10px 0; }}
</style></head><body>
<h1>Phase 23.11.6 Intentional Insufficient 审核</h1>
<div class="notice">这3条 Claim 被标注为「材料不足」。请确认它们确实：现有材料既无法支持、也无法反驳。审核字段默认为空，请填写后点「导出JSON」。</div>
<div id="container"></div>
<div style="margin-top:14px;"><button id="exportbtn">&#128228; 导出JSON</button></div>
<div id="exportinfo" class="notice" style="display:none;"></div>
<script>
var ITEMS={items_json};
var state=JSON.parse(localStorage.getItem('fp_insuf_state')||'{{}}');
function render(){{
  var h='';
  for(var i=0;i<ITEMS.length;i++){{
    var it=ITEMS[i]; var a=state[it.claim_id]||{{'confirmed':'','rationale':'','name':'','at':''}};
    h+='<div class="item"><h3>'+it.claim_id+'</h3>';
    h+='<p><b>Claim文本:</b> '+it.claim_text+'</p>';
    h+='<p><b>文档范围:</b> '+it.document_scope+' &nbsp; <b>证据数:</b> '+it.evidence_count+'（应为0）</p>';
    h+='<label><b>reviewer_confirmed_insufficient:</b> <select onchange="setVal(\\''+it.claim_id+'\\',\\'confirmed\\',this.value)"><option value="">-- 选择 --</option><option value="yes" '+(a.confirmed=="yes"?"selected":"")+'>yes（确认不足）</option><option value="no" '+(a.confirmed=="no"?"selected":"")+'>no（实际上有证据可判）</option></select></label>';
    h+='<label><b>reviewer_rationale:</b> <textarea rows="3" onchange="setVal(\\''+it.claim_id+'\\',\\'rationale\\',this.value)">'+(a.rationale||'')+'</textarea></label>';
    h+='<label><b>reviewer_name:</b> <input type="text" value="'+(a.name||'')+'" onchange="setVal(\\''+it.claim_id+'\\',\\'name\\',this.value)"></label>';
    h+='<label><b>reviewed_at:</b> <input type="text" value="'+(a.at||new Date().toISOString().slice(0,10))+'" onchange="setVal(\\''+it.claim_id+'\\',\\'at\\',this.value)"></label>';
    h+='</div>';
  }}
  document.getElementById('container').innerHTML=h;
}}
function setVal(cid,field,v){{ state[cid]=state[cid]||{{}}; state[cid][field]=v; localStorage.setItem('fp_insuf_state',JSON.stringify(state)); }}
function exportJSON(){{
  var out=[]; var today=new Date().toISOString().slice(0,10);
  for(var i=0;i<ITEMS.length;i++){{
    var it=ITEMS[i]; var a=state[it.claim_id]||{{}};
    out.push({{'claim_id':it.claim_id,'claim_text':it.claim_text,'document_scope':it.document_scope,
      'system_visible_evidence_set':[],
      'reviewer_confirmed_insufficient':a.confirmed||'','reviewer_rationale':a.rationale||'',
      'reviewer_name':a.name||'','reviewed_at':a.at||today,
      'review_status':(a.confirmed?'REVIEWED':'PENDING')}});
  }}
  var blob=new Blob([JSON.stringify({{'phase':'23.11.6','total':ITEMS.length,'items':out}},null,2)],{{type:'application/json'}});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='insufficient_results.json'; a.click();
  var info=document.getElementById('exportinfo'); info.style.display='block';
  info.innerHTML='<b>已下载 insufficient_results.json</b>，请保存到 data/gold_review/phase23_11_6/insufficient_results.json。';
}}
document.getElementById('exportbtn').addEventListener('click',exportJSON);
render();
</script></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())