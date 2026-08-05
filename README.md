# FinProof 鉴融

> 让金融报告中的每一个数字，都能被重新计算；让每一个结论，都能找到原始证据。

金融研究报告事实核验与证据链智能体（黑客松 MVP）。系统将研究报告拆解为可核验的金融主张，对照原始披露文件重新计算财务指标，输出"支持 / 反驳 / 部分支持 / 证据不足 / 无法判断"五类核验结果，并提供可追溯的审计报告。

## 文档

| 文档 | 说明 |
| ---- | ---- |
| `docs/finproof_product_spec.md` | 完整产品方案（25 章） |
| `docs/finproof_audit.md` | 项目审计报告（含混合核验架构原则 6.5） |
| `docs/finproof_mvp_scope.md` | MVP 范围与验收标准 |
| `docs/finproof_execution_plan.md` | Phase 0–8 执行计划 |
| `docs/finproof_progress.md` | 开发进度记录 |
| `docs/phase23_9_core_path_integration.md` | Phase 23.9 核心调用链接线、指标校准与 17 个错误闭环结果 |
| `docs/phase23_9_legacy_inventory.md` | Phase 23.9 重复实现分类清单（PRIMARY/LEGACY_USED/TEST_ONLY） |
| `docs/blind_holdout_user_guide.md` | Blind Holdout 最简用户操作说明（当前 BLOCKED） |
| `docs/phase23_10_table_aware_retrieval.md` | Phase 23.10 Table-aware Retrieval 与 E2E 鲁棒性修复结果 |
| `docs/phase23_11_evidence_routing_and_gate.md` | Phase 23.11 Evidence Routing、Precision Gate 与真实 E2E 止损修复 |
| `docs/phase23_11_1_evaluation_repair.md` | Phase 23.11.1 评测链路修复与真实 E2E 结果 |
| `docs/phase23_11_2_gate_semantics_and_calibration.md` | Phase 23.11.2 Evidence Gate 语义修复、阈值校准与真实 E2E 恢复 |
| `docs/phase23_11_3_aggregation_contract.md` | Phase 23.11.3 Evidence 聚合契约、Verdict 映射与逐层真值对账 |
| `docs/phase23_11_4_gold_contract_and_core_verify.md` | Phase 23.11.4 Gold契约清理、Core Verify修复与可信Oracle重建 |
| `docs/phase23_11_5_gold_grounding_and_core_closure.md` | Phase 23.11.5 Gold Evidence Grounding与Core错误闭环结果 |
| `docs/phase23_11_5_1_grounding_integrity_audit.md` | Phase 23.11.5.1 Gold Grounding完整性复核结果 |
| `docs/phase23_11_6_human_review_handoff.md` | Phase 23.11.6 Human Gold Review Pack与人工审核交接 |
| `docs/human_gold_review_quickstart.md` | 人工Gold审核快速上手（8步操作说明） |

## 目录结构

```text
finproof/
├── backend/            # FastAPI 后端（Python 3.12 / SQLAlchemy / SQLite）
├── frontend/           # Next.js 前端（TypeScript / pnpm）
├── data/
│   ├── demo/           # 演示数据（来源文件 / 预埋错误研报 / 金标准）
│   └── uploads/        # 运行时上传文件（gitignore）
├── docs/               # 产品与规划文档
└── tests/              # 数据校验与评测脚本
```

## 本地启动

### 后端

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # 首次
pip install -r requirements.txt                       # 首次
cp .env.example .env                                  # 可选，默认值即可运行
uvicorn app.main:app --reload --port 8000
```

验证：`curl http://127.0.0.1:8000/health` → `{"status":"ok","service":"finproof-api"}`

运行测试：`cd backend && source .venv/bin/activate && python -m pytest tests/ -v`

### 前端

```bash
cd frontend
pnpm install        # 首次
pnpm dev            # 默认 http://localhost:3000
```

首页会展示 FinProof 名称与项目定位，并显示后端健康状态（后端需先启动；未启动时显示"异常"）。

生产构建：`pnpm build && pnpm start`

## 当前状态（Phase 0 + Phase 1）

- Phase 0（脚手架）：后端 FastAPI + `/health` + SQLite 连接 + pytest；前端 Next.js 最小首页 + 后端健康状态。
- Phase 1（演示数据）：候选公司筛选、真实披露文件归档、预埋错误研报、金标准与校验脚本。详见 `docs/finproof_progress.md`。

## 当前阶段（Phase 23.11，PARTIAL — 不标记 Competition-Usable）

- **Claim Router**（8 routes）、**Financial Fact Index**、**Channel A/B 双检索**、**Evidence Precision Gate**、**Evidence Selector (Top1/Top3/Top5)**、**Evidence Margin/弃权** 全部进入真实主链。
- **Oracle**：Accuracy=1.0，Macro-F1=1.0（连续 2 次一致）。
- **Real E2E**：Accuracy=0.326，Macro-F1=0.424，coverage=0.465，abstentions=23（连续 2 次一致）。
- **Metamorphic**：invariance=1.0，contradiction=0.9021，removal=0.9429，all_met=True。
- **pytest**：845 passed ×5；**frontend build**：success ×3。
- **Blind Holdout**：仍 BLOCKED（需补充两家全新公司 PDF 与待审计报告）。

**未达标**：Real E2E Accuracy 0.326 < 0.70；Evidence Gate precision 0.062 < 0.80；accepted_noise_rate 0.938 > 0.15；coverage 0.465 < 0.65。按 §十五，若真实 E2E 仍低于 0.60，不得继续新增检索特征、不得标记 Competition-Usable，必须选择更窄的比赛演示范围并明确标注不支持的 Claim 类型。

## 架构原则（摘要）

FinProof 为**混合核验架构**：数字格式化、单位/币种、同比/环比、累计转单季、比率与差异比较由**确定性程序**负责；主张拆解、语义识别、证据支持关系判断、因果/预测检测、修订建议由**大模型**负责；无 API Key 时走明确标识的 **Mock 模式**（输出带"Mock"标识，不伪装为真实模型结果）。详见 `docs/finproof_audit.md` 6.5 节。
