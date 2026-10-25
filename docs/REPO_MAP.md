# 仓库地图（Repo Map）

```
finproof/
├── finproof-verifier/          ★ 鉴融专家包（产品本体，v2.8.0）
│   ├── agents/finproof-verifier.md        agent 定义（角色/能力/流程/操守）
│   ├── skills/finproof-verification/
│   │   ├── SKILL.md             操作手册（自足最小集，完整档必读）
│   │   ├── LITE.md              快速档轻量执行卡（自足 ~90 行）
│   │   ├── references/          17 份细则（评分规格/模板/协议/基准…）
│   │   └── bin/finproof_calc.py 确定性引擎（15 子命令，49 测试）
│   ├── .codebuddy-plugin/plugin.json      注册清单
│   └── check_package.py         包一致性检查（43 项一键全检）
├── evaluation/                 测评证据（六轮两臂对照 + Fin-Fact 真实语料 + 异源复核）
│   ├── 测评报告.md             主报告（从这里开始读）
│   ├── ground_truth*.json      评分密钥（含极性裁定密钥）
│   ├── runs/                   全部原始输出（含作废轮次）
│   └── keys.sh                 密钥隔离脚本
├── backend/                    历史参考实现（容差已对齐 0.001；984 测试）
├── docs/                       产品文档与仓库地图
├── 作品详情_鉴融.txt 等中文材料   比赛交付材料
├── CHANGELOG.md                版本摘要（详录在 finproof-verifier/README §十三）
├── LICENSE                     MIT
└── .github/workflows/ci.yml    CI（引擎测试 + 包检查 + backend 对齐）
```

**快速上手**：读 `finproof-verifier/README.md`（含英文摘要）→ 用法见 plugin quickPrompts → 测评证据从 `evaluation/测评报告.md` 进。
