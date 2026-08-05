"""Phase 23.11.6.1 Upgrade NOT_FOUND review page to interactive form (Task 6)."""
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

REC_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_not_found_recovery.json"
OUT_PATH = BACKEND.parent / "data" / "gold_review" / "phase23_11_6" / "not_found_review.html"


def main() -> int:
    rec = json.loads(REC_PATH.read_text(encoding="utf-8"))
    claims, _ = load_canonical_claims()
    claim_by_id = {c.claim_id: c for c in claims}
    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).order_by(
            DocumentBlock.document_id, DocumentBlock.page_id, DocumentBlock.block_index).all()
    finally:
        session.close()
    blocks_by_page: dict = {}
    for b in all_blocks:
        blocks_by_page.setdefault(b.page_id, []).append(b)

    items = []
    for it in rec["per_item"]:
        cid = it["claim_id"]
        cc = claim_by_id.get(cid)
        page = it["annotated_page"]
        page_txt = "\n".join(str(b.text or "")[:120] for b in blocks_by_page.get(page, [])[:8])
        items.append({
            "item_id": it["gold_evidence_id"], "claim_id": cid,
            "claim_text": str(cc.claim_text if cc else "")[:300],
            "company": it["company"], "dataset": it["dataset"],
            "gold_evidence_text": it["evidence_text"][:300],
            "annotated_page": page, "recovery_status": it["recovery_status"],
            "recovery_reason": it["recovery_reason"],
            "page_parsed_text": page_txt,
            "adjacent_pages": [{"page": a["page"], "text": a["text"][:150]} for a in it.get("adjacent_pages", [])],
            "pdf_sources": [p["name"] + " (" + p["sha256"] + ")" for p in it.get("source_pdfs", [])],
            "reviewer_decision": "", "reviewer_note": "", "reviewed_at": "", "review_status": "PENDING",
        })

    items_json = json.dumps(items, ensure_ascii=False)
    html = _build(items_json, len(items))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    leaks = [w for w in ("expected_verdict", "SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED",
                         "INSUFFICIENT_EVIDENCE", "prediction", "is_gold") if w in html]
    print(f"not_found_review.html regenerated ({len(html)} bytes, {len(items)} items)")
    print(f"leaks: {leaks if leaks else 'none'}")
    print(f"offline: {('http://' not in html and 'https://' not in html)}")
    print(f"export: {'exportJSON' in html}")
    return 0


def _build(items_json: str, total: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>Phase 23.11.6 NOT_FOUND 视觉审核包（交互式）</title>
<style>
body {{ font-family: sans-serif; max-width: 900px; margin: 20px auto; padding: 0 20px; }}
#nav {{ display:flex; gap:10px; align-items:center; margin-bottom:16px; }}
#nav button {{ padding:8px 16px; font-size:15px; }}
#progressbar {{ height:6px; background:#eee; border-radius:3px; margin-bottom:16px; }}
#progressbar>div {{ height:100%; background:#4caf50; width:0%; border-radius:3px; }}
.item {{ border:1px solid #ccc; border-radius:8px; padding:16px; }}
.gold {{ background:#fff8e1; border:1px solid #e0c; padding:8px 12px; }}
.page {{ background:#e3f2fd; padding:8px 12px; margin:6px 0; white-space:pre-wrap; }}
.adj {{ background:#f3e5f5; padding:6px 10px; margin:4px 0; font-size:0.9em; }}
label {{ display:block; margin:6px 0; }}
textarea, select {{ width:100%; padding:6px; }}
.btnrow {{ margin-top:14px; display:flex; gap:10px; }}
#exportbtn {{ background:#1976d2; color:#fff; border:none; padding:10px 20px; border-radius:4px; cursor:pointer; }}
#savebtn {{ background:#388e3c; color:#fff; border:none; padding:10px 20px; border-radius:4px; cursor:pointer; }}
.notice {{ background:#fff3e0; border:1px solid #ffb74d; padding:8px 12px; margin:10px 0; }}
</style></head><body>
<h1>Phase 23.11.6 NOT_FOUND 视觉审核包（交互式）</h1>
<div class="notice">共 {total} 条。请打开对应PDF页面核对。建议先审核一部分后点「保存进度」，完成后点「导出JSON」。</div>
<div id="progressbar"><div id="progressfill"></div></div>
<div id="nav"><button id="prevbtn">&larr; 上一条</button><span id="counter">1 / {total}</span><button id="nextbtn">下一条 &rarr;</button></div>
<div id="itemcontainer" class="item"></div>
<div class="btnrow"><button id="savebtn">&#128190; 保存进度</button><button id="exportbtn">&#128228; 导出JSON</button></div>
<div id="exportinfo" class="notice" style="display:none;"></div>
<script>
var ITEMS={items_json};
var state=JSON.parse(localStorage.getItem('fp_nf_state')||'{{"idx":0,"answers":{{}}}}');
var idx=state.idx||0;
function render(){{
  var it=ITEMS[idx]; var ans=state.answers[it.item_id]||{{'decision':'','note':'','at':''}};
  var h='<h3>Evidence: '+it.item_id+' (claim '+it.claim_id+')</h3>';
  h+='<p><b>公司:</b> '+it.company+' &nbsp; <b>数据集:</b> '+it.dataset+' &nbsp; <b>标注页码:</b> '+it.annotated_page+'</p>';
  h+='<p><b>Claim文本:</b> '+it.claim_text+'</p>';
  h+='<div class="gold"><b>原Gold Evidence文本:</b><br>'+it.gold_evidence_text+'</div>';
  h+='<p><b>恢复状态:</b> '+it.recovery_status+' &nbsp; <b>原因:</b> '+it.recovery_reason+'</p>';
  h+='<p><b>PDF源:</b> '+(it.pdf_sources.join('; ')||'无')+'</p>';
  h+='<div class="page"><b>第'+it.annotated_page+'页解析文本:</b><br>'+(it.page_parsed_text||'(无文本Block)')+'</div>';
  for(var i=0;i<it.adjacent_pages.length;i++){{ h+='<div class="adj"><b>第'+it.adjacent_pages[i].page+'页:</b> '+it.adjacent_pages[i].text+'</div>'; }}
  var opts=['FOUND_ON_PAGE','FOUND_ON_ADJACENT_PAGE','FOUND_IN_OTHER_DOCUMENT','GOLD_TEXT_IS_PARAPHRASED','GOLD_ANNOTATION_IS_WRONG','SOURCE_MISSING','UNSURE'];
  h+='<h4>人工选择</h4>';
  for(var i=0;i<opts.length;i++){{
    var chk=(ans.decision==opts[i])?'checked':'';
    h+='<label><input type="radio" name="decision" value="'+opts[i]+'" '+chk+' onchange="setDec(this.value)"> '+opts[i]+'</label>';
  }}
  h+='<label><b>reviewer_note:</b> <textarea rows="3" onchange="setNote(this.value)">'+(ans.note||'')+'</textarea></label>';
  h+='<label><b>reviewed_at:</b> <input type="text" value="'+(ans.at||new Date().toISOString().slice(0,10))+'" onchange="setAt(this.value)"></label>';
  document.getElementById('itemcontainer').innerHTML=h;
  document.getElementById('counter').textContent=(idx+1)+' / '+ITEMS.length;
  document.getElementById('progressfill').style.width=(Object.keys(state.answers).length/ITEMS.length*100)+'%';
  document.getElementById('prevbtn').disabled=(idx<=0);
  document.getElementById('nextbtn').disabled=(idx>=ITEMS.length-1);
}}
function save(){{ localStorage.setItem('fp_nf_state',JSON.stringify(state)); alert('进度已保存'); }}
function setDec(v){{ var it=ITEMS[idx]; var a=state.answers[it.item_id]||{{'decision':'','note':'','at':''}}; a.decision=v; state.answers[it.item_id]=a; }}
function setNote(v){{ var it=ITEMS[idx]; var a=state.answers[it.item_id]||{{'decision':'','note':'','at':''}}; a.note=v; state.answers[it.item_id]=a; }}
function setAt(v){{ var it=ITEMS[idx]; var a=state.answers[it.item_id]||{{'decision':'','note':'','at':''}}; a.at=v; state.answers[it.item_id]=a; }}
function exportJSON(){{
  var out=[]; var today=new Date().toISOString().slice(0,10);
  for(var i=0;i<ITEMS.length;i++){{
    var it=ITEMS[i]; var a=state.answers[it.item_id]||{{'decision':'','note':'','at':''}};
    out.push({{'item_id':it.item_id,'claim_id':it.claim_id,'reviewer_decision':a.decision,'reviewer_note':a.note,'reviewed_at':a.at||today,'review_status':(a.decision?'REVIEWED':'PENDING')}});
  }}
  var blob=new Blob([JSON.stringify({{'phase':'23.11.6','type':'not_found','total':ITEMS.length,'items':out}},null,2)],{{type:'application/json'}});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='not_found_results.json'; a.click();
  var info=document.getElementById('exportinfo'); info.style.display='block';
  info.innerHTML='<b>已下载 not_found_results.json</b>，请保存到 data/gold_review/phase23_11_6/not_found_results.json。';
}}
document.getElementById('prevbtn').addEventListener('click',function(){{if(idx>0){{idx--;render();}}}});
document.getElementById('nextbtn').addEventListener('click',function(){{if(idx<ITEMS.length-1){{idx++;render();}}}});
document.getElementById('savebtn').addEventListener('click',save);
document.getElementById('exportbtn').addEventListener('click',exportJSON);
render();
</script></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())