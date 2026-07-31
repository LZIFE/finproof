# FinProof 开发进度记录

> 更新日期：2026-07-31
> 当前阶段：**Phase 0（脚手架）与 Phase 1（演示数据与金标准）已完成**，等待进入 Phase 2。
> 进度约定：每个 Phase 满足 Definition of Done 后提交一次 git commit 并在本文件登记。

---

## Phase 0：工程骨架与仓库初始化 — ✅ 已完成（commit `a591bff`）

**产出**：

| 项 | 结果 |
| -- | ---- |
| 后端 | FastAPI + Pydantic v2 + SQLAlchemy + SQLite + pytest（`backend/`，Python 3.12） |
| 健康检查 | `GET /health` 与 `GET /api/health` → `{"status":"ok","service":"finproof-api","database":"3.51.0"}` |
| 配置管理 | `backend/app/core/config.py`（pydantic-settings，`FINPROOF_` 前缀，全默认值可运行，LLM 默认 Mock 模式） |
| SQLite 连接 | `backend/app/db.py`（engine/SessionLocal/Base/init_db/check_db_connection） |
| 异常处理 | `backend/app/core/exceptions.py`（AppError + 统一 handler） |
| 测试 | `backend/tests/`：test_health / test_db / test_config / test_exceptions（11 项） |
| 前端 | Next.js 15 + TypeScript + pnpm（`frontend/`）：首页展示 FinProof 定位 + 后端健康状态（`/api/*` 代理到 8000 端口） |
| 基础文件 | `.gitignore`、`.env.example`（根 + backend）、`README.md`（启动步骤）、`backend/requirements.txt`、`frontend/package.json` |

**验证结果**（实测）：

- 后端 pytest：`24 passed`（含 Phase 1 的 13 项校验脚本测试）
- 前端：`pnpm build` 成功；`pnpm start` 后首页返回 200，代理 `/api/health` 转发后端成功
- 启动冒烟：uvicorn 启动 → `/health` 返回 200 且含 SQLite 版本

**DoD 状态**：全部满足（后端可启动 / /health 正常 / 前端可启动且显示后端健康状态 / SQLite 连接测试通过 / 测试全绿 / README 含完整启动步骤）。

---

## Phase 1：演示数据与金标准 — ✅ 已完成（commit `8270be4`）

**产出**：

| 项 | 结果 |
| -- | ---- |
| 候选公司筛选 | 实测三家深市公司（美的集团 000333 / 五粮液 000858 / 宁德时代 300750）共 9 份真实披露 PDF 的提取测试，见 `data/demo/company_selection.md` |
| 最终选定 | **美的集团（000333，深交所主板）**：错误构造空间最大（多分部 + 海外业务）、理解成本低、提取质量实测最优 |
| 来源文件 | `data/demo/source/`：`annual_report.pdf`（276 页）/ `q1_report.pdf`（11 页）/ `half_year_report.pdf`（205 页），均为文本型，SHA-256 与来源记录见 `data/demo/README.md` |
| 预埋错误研报 | `data/demo/reports/ai_report_with_errors.md`（约 2,300 字，26 条可核验主张） |
| 校正版 | `data/demo/reports/corrected_report.md`（人工校正参考版） |
| 金标准 | `data/demo/annotations/`：gold_claims.json（26 条）/ gold_evidence.json（29 条）/ gold_verifications.json（26 条） |
| 抽查验证 | `data/demo/annotations/validation_report.md`：随机抽查 5 条（CLM-001/005/009/014/019）全部通过（页码、证据存在、数值可得、结论一致、计算可复现） |
| 校验脚本 | `scripts/validate_gold.py`（金标准完整性校验）+ `backend/tests/test_validate_gold.py`（13 项测试） |

**金标准统计**：

| 类别 | 数量 |
| ---- | ---- |
| 主张总数 | 26 |
| SUPPORTED（正确） | 11 |
| REFUTED（错误） | 10 |
| PARTIALLY_SUPPORTED（部分支持） | 1 |
| INSUFFICIENT_EVIDENCE（证据不足） | 2 |
| UNABLE_TO_DETERMINE（无法判断） | 1 |
| OPINION_OR_FORECAST（观点/预测） | 1 |
| 覆盖错误类型 | 14 种（≥6 要求） |
| 确定性计算主张（带公式） | 7（≥5 要求） |
| 单季度/累计口径主张 | 3（≥3 要求） |
| 非数字语义主张 | 5（≥3 要求） |

**验证结果**（实测）：

- `python scripts/validate_gold.py` → `claims=26 evidence=29 verifications=26 errors=0`，退出码 0
- 金标准一致性：evidence/verification 引用的 claim_id 全部存在，claims 与 verifications 一一对应
- 抽查 5 条金标准：证据片段在指定 PDF 页真实存在（PyMuPDF 重新提取比对）

**DoD 状态**：全部满足（3 家公司实测 / 选定 1 家 / ≥3 份真实 PDF 归档带哈希 / 预埋错误研报 + 校正版 / ≥20 条金标准 / 正确+错误+证据不足样本齐备 / ≥6 种错误类型 / 抽查 5 条通过 / 校验脚本与测试通过）。

---

## 遗留问题（数据质量）

1. **宁德时代一季报"归属于上市公司股东的净利润"整词提取命中 0 页**（表格单元格拆分所致，仅影响其候选评估，与最终选定公司无关）。
2. **五粮液一季报/半年报为"更新后"版本**，来源标注需额外说明（未入选，无影响）。
3. **美的金标准中 21 条非抽查主张**建议正式评测前对高风险项（CLM-002/004/006/010/015/016/017/018/020/024）再各复核一次页码。
4. **Q3 报告未纳入证据文件**：CLM-025（Q4 单季）因此被设计为"无法判断"，属有意为之（演示拒答能力），如后续补入三季报可升级为可核验。
5. `data/demo/tmp/` 保留三家候选公司的 9 份原始下载（已 gitignore），可经 `scripts/download_cninfo.py` 重新下载或用于更换演示公司。

---

## 下一步（不在本轮范围）

- **Phase 2：PDF 解析与文档入库**（上传接口 + PyMuPDF 页码保留解析 + documents/pages 表）
- Phase 3：主张提取与结构化（规则初筛 + LLM/Mock 拆解）
- Phase 4：证据匹配；Phase 5：确定性计算引擎；Phase 6：五类判定与评分
- Phase 7：前端三栏展示；Phase 8：评测与导出

详见 `docs/finproof_execution_plan.md`。
