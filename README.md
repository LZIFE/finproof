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

## 架构原则（摘要）

FinProof 为**混合核验架构**：数字格式化、单位/币种、同比/环比、累计转单季、比率与差异比较由**确定性程序**负责；主张拆解、语义识别、证据支持关系判断、因果/预测检测、修订建议由**大模型**负责；无 API Key 时走明确标识的 **Mock 模式**（输出带"Mock"标识，不伪装为真实模型结果）。详见 `docs/finproof_audit.md` 6.5 节。
