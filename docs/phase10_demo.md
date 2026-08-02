# FinProof Phase 10 · Demo — 美的集团金融知识图谱

> 公司：美的集团（000333，深交所主板）
> 报告期：2025FY
> 输入：已有 Claim Extraction + Evidence Retrieval + Intelligence Report
> 演示日期：2026-07-31

## 1. 流程（任务书 §1）

```
Claims + Evidence + Company Facts
   ↓ Entity Extraction（公司/业务/产品/地区/竞争对手/指标/高管）
Entities + Relationships + Facts（kg_entities / kg_relationships / kg_facts）
   ↓ Conflict Reasoning（Claim vs Graph Fact）
ConflictFindings（claim / graph_facts / difference / risk_type / risk_score）
```

## 2. Entity Extraction（任务书 §2）

从已有 Claims / Evidence / Company Facts 抽取：

| 实体类型 | 美的集团示例 |
| ---- | ---- |
| Company | 美的集团 |
| Business | 暖通空调 / 消费电器 / 机器人与自动化 |
| Product | 空调 / 冰箱 / COLMO / KUKA |
| Region | 海外 / 北美 / 欧洲 / 东南亚 |
| Competitor | 海尔 / 格力 / 海信 / 西门子 |
| Metric | 营业收入 / 归母净利润 / 毛利率 |
| Executive | 方洪波（董事长）|

## 3. Relationships（任务书 §4）

- OWNS           美的集团 → 空调 / 冰箱
- HAS_BUSINESS   美的集团 → 暖通空调 / 消费电器
- COMPETES_WITH  美的集团 → 海尔 / 格力
- LOCATED_IN     暖通空调 → 海外 / 北美
- HAS_METRIC     美的集团 → 营业收入 4564.52 亿元
- SUPPORTED_BY   事实 → 证据（Evidence First）

## 4. Conflict Reasoning（任务书 §5）

| 检测类型 | 示例 |
| ---- | ---- |
| CLAIM_VS_FACT            Claim "营收 5000 亿" vs Fact 4564.52 亿 |
| BUSINESS_OVERSTATEMENT  Claim 含"遥遥领先/唯一/龙头" |
| COMPETITIVE_NO_EVIDENCE Claim "行业领先" 但图谱无市场份额强证据 |
| GROWTH_INSUFFICIENT     Claim "海外业务高速增长" 但无增长数字事实 |

## 5. Committee Integration（任务书 §6）

Research Agent 增加 Knowledge Graph 工具调用：
- `get_company_profile`  Company Profile（公司画像）
- `get_business_map`     Business Map（业务图谱）
- 合并 KG 字段到 ResearchFindings

## 6. 运行方式

```bash
cd backend
python -m scripts.phase10_demo
```

输出包含：
- 知识图谱统计（实体数 / 关系数 / 事实数）
- Entity Network（实体网络）
- Facts（图谱事实，含 source/evidence/confidence/timestamp）
- ConflictFindings（冲突推理结论）

## 7. 设计约束

- 不修改已有 Verification 逻辑；
- Knowledge Graph 作为新增层，与已有模块解耦；
- Evidence First：每个 Fact 必须包含 source / evidence / confidence / timestamp。
