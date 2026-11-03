# AnamnesisBench OOD 错判归因（官方 in_scope）

- OOD 总数：104
- 官方范围内错判：2
- 范围外（novel，按设计弃权）：0

## 按失败阶段

| 阶段 | 数量 |
|---|---:|
| 单位/量级 | 2 |

## 按 artifact 类型

| 类型 | 数量 |
|---|---:|
| reconcile | 2 |

## 逐条

| ID | 类型 | 金标 | 实判 | 阶段 | 理由 |
|---|---|---|---|---|---|
| OOD-0001 | reconcile | consistent | violation | 单位/量级 | 单位表述不一致（USD billions vs USD millions） |
| OOD-0003 | reconcile | consistent | violation | 单位/量级 | 单位表述不一致（percent vs fraction） |

> **已知标签冲突（不修，v2.17.0 决策）**：主集 AB-0029…AB-0042 与 OOD-0001 结构同构（M/B 换算后等值），主集官方 reference 判 unit_scale_flip（violation），OOD 盲评判 consistent——修此 2 例必然破主集 392/392。按主集口径对齐（主集有官方 reference 1.0 可对照），见 `run_bench.py` 口径注释。
