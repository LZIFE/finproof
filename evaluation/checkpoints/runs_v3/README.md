# v3 规模轴运行存档（workspace3：11 公司 / 261 对 / 37 证据文件）

- A1v3_bare.md — 裸提示臂：287,681 tok / 449s / 15 工具，检出≈全覆盖（逐公司 before/after 表）
- B1v3_framework.md — 框架臂（全骨架阅读+誊抄）：303,627 tok —— 教训：誊抄明细吃掉成本优势
- B2v3_framework.md — 框架臂（引用不誊抄但 F 类自述）：360,866 tok —— 教训：F 类应管线化
- B3v3_framework.md — 框架臂（F 类管线化+全骨架阅读）：186,578 tok —— 骨架阅读成本随对数线性涨
- B4v3_framework.md — 框架臂（摘要视图 1.8KB）：**87,055 tok / 165s**，检出全覆盖，
  F 类确认+1 处示例锚点纠正，E 抽检 5/5，Q2 forecast_scan FLAG
- 管线本体：pipeline_prefilter.py v3.2（A/B/C/F 类全机械，0 token / 数秒）

金标：ground_truth3.json（261 对引擎裁决 = 227 错误 [丰光 160 低置信] + 34 容差陷阱 + 构造语义 2）
