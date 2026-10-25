# FinProof 事实核验专家 — v1.5.0 收尾概览

## 本次完成
- **去金融化，升级为通用「报告验证专家」**：任何事实性报告（金融研报、行业研究、市场分析、政策解读、尽调纪要、数据白皮书、学术综述）均可核验；金融研报是验证最深的场景，方法论通用。**名字保留「鉴融」**。
- 主张分类 A–G 通用化（原始数字/计算/口径/事实/因果/比较/预测）；财务公式对非财务报告自动降级为通用数值复算（占比/增长/总和一致性）。
- 附带能力（v1.4.1 起已内置）：**扫描件 OCR**——PyMuPDF 渲染 + 本机 tesseract（chi_sim 实测可用）/ 多模态视觉读取；缺口分类 G1–G4 + 用户自核清单。

## 交付物
- `finproof-verifier.zip` — 专家包 v1.5.0（18 文件，396.1 KB），validate ✅（0 warning）/ register ✅ / package ✅。

## 身份变更
- displayName：鉴融—报告验证专家（en: Jianrong — Report Verification Expert）
- profession：报告事实核验专家
- tags：事实核验 / 证据链审计 / 报告复审
- category：10-ProjectQuality（原 08-FinanceInvestment）
- 技术 id 保留 finproof-verifier

## 关键路径
- 专家包：`/Users/z1/.workbuddy/plugins/marketplaces/my-experts/plugins/finproof-verifier/`
- 注册表：`/Users/z1/.workbuddy/plugins/marketplaces/my-experts/.codebuddy-plugin/marketplace.json`
