# 真实 LLM 运行失败记录（Phase 3.6）

> 日期：2026-07-31
> **比赛环境说明**：比赛环境采用官方 Coding Agent 承担金融语义推理（Agent-assisted 架构），
> 本阶段已完成 Agent-assisted 主张提取验证（assisted_ai / deepseek-v4-flash）。
> 模型 API Provider 属于商业化部署扩展，不影响比赛版本开发。
> 本文档为**历史实验记录**（模型 API 凭据未配置时的明确失败行为），保留原始记录，不作为比赛版本的能力缺失。

## 一、配置检查结果（实测）

| 配置项 | 状态 |
| ------ | ---- |
| CLAIM_EXTRACTION_MODE / PROVIDER / MODEL / BASE_URL / API_KEY / PROMPT_VERSION | 全部未设置 |
| FINPROOF_CLAIM_EXTRACTION_*（同义前缀） | 全部未设置 |
| OPENAI_API_KEY / OPENAI_BASE_URL | 未设置 |
| 本地模型服务（Ollama 11434 / LM Studio 1234 / llama.cpp 8080） | 无服务在监听 |
| ollama CLI | 不存在 |

最小连通性测试：**无法执行**（无 base_url 可探测）。

## 二、未执行项与原因

| 项 | 状态 | 原因 |
| -- | ---- | ---- |
| 开发集真实 LLM 三次运行（Prompt v2） | **未执行** | 无模型凭据（API Key / Base URL / Model 缺失） |
| 开发集 Token/耗时/Provider 错误重试记录 | 未产生 | 同上 |
| 盲测集真实 LLM 首次运行 | **未执行** | 同上 |
| Claim Set Stability（真实 LLM 三次） | 未验证 | 需要三次真实运行 |

## 三、防止伪装的措施（已落实）

1. **未回退 Mock 冒充真实调用**：`LLMClaimExtractionProvider` 配置缺失时抛 `LLM_NOT_CONFIGURED`；`HybridClaimExtractionProvider` 同样明确失败（均有单测覆盖）。
2. **未宣称任何真实模型成绩**：本记录及全部评测产物均为 Mock/规则模式结果，`human_reviewed=false`，带明确模式标识。
3. **API Key 安全**：未写入代码/数据库/Git/评测产物/日志。

## 四、替代执行（明确标注模式，供参考）

- 开发集：mock（run 11）、rules（run 12）已完成评测（见 `artifacts/evaluations/claim_extraction/`）。
- 盲测集：以 **rules 模式**执行首次运行作为流程验证（产物 `artifacts/evaluations/holdout/`），**明确标注为规则模式，非真实 LLM 成绩**。

## 五、恢复条件

配置以下环境变量后即可真实运行（无需改代码）：
```bash
export CLAIM_EXTRACTION_MODE=llm
export CLAIM_EXTRACTION_BASE_URL=<真实地址>      # 如 https://api.openai.com/v1 或本地兼容服务
export CLAIM_EXTRACTION_MODEL=<模型名>
export CLAIM_EXTRACTION_API_KEY=<密钥>            # 不入库、不入 Git、不写日志
export CLAIM_EXTRACTION_PROMPT_VERSION=v2
```
随后执行：开发集三次运行（`--mode llm --force` ×3）→ 稳定性 → 盲测集首次运行 → 人工审核。
