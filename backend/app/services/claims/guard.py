"""金标准泄漏防护（Phase 3.6）。

提取链路（services/claims/*、claim_service、providers）不得读取：
- data/demo/annotations/（gold_claims/gold_evidence/gold_verifications）
- data/holdout/annotations/（盲测金标准）
- artifacts/evaluations/（历史匹配结果、人工审核答案）

提取服务的运行时输入只允许：待核验报告、文档元数据、规则词典、Prompt 模板、配置参数。
评测脚本可以在提取完成后读取金标准；提取服务本身不能。

防护方式：
1. 静态断言：扫描提取服务源码（剔除注释行），不允许出现金标准文件名/目录。
2. 运行时调用：claim_service 在调用 Provider 前执行本断言，任何违规立即失败。
"""

import re
from pathlib import Path

# 金标准/评测数据的关键标识（出现在非注释代码行即视为泄漏引用）
FORBIDDEN_TOKENS = (
    "gold_claims",
    "gold_evidence",
    "gold_verifications",
    "holdout",
    "annotations",
    "artifacts/evaluations",
    "matched_claims",
    "unmatched_system",
)

# 提取服务源码根（相对本文件：backend/app/services/claims/ -> 上两级为 services）
CLAIMS_PKG = Path(__file__).resolve().parent  # .../services/claims
SCAN_ROOTS = [
    CLAIMS_PKG,
    Path(__file__).resolve().parents[1] / "claim_service.py",  # .../services/claim_service.py
    Path(__file__).resolve().parents[2] / "api" / "claims.py",  # .../api/claims.py
]

# 允许出现上述 token 的说明性路径（文档字符串内安全提及属正常，代码路径除外）
_ALLOWED_CONTEXT = ("gold", "leak", "泄漏", "防护", "guard", "forbidden", "金标准")

_DOCSTRING_RE = re.compile(r'("""|\'\'\')(.*?)\1', re.S)


def _strip_comments(source: str) -> str:
    """剔除注释行与三引号文档字符串（仅扫描实际代码路径）。"""
    source = _DOCSTRING_RE.sub("", source)
    lines = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def assert_extraction_isolated() -> None:
    """断言提取服务源码不引用金标准/评测数据；违规抛 RuntimeError。"""
    violations: list[str] = []
    this_file = Path(__file__).resolve()
    for root in SCAN_ROOTS:
        if root.is_file():
            files = [root]
        else:
            files = sorted(root.rglob("*.py"))
        for path in files:
            if path.resolve() == this_file:  # 防护定义文件自身除外
                continue
            source = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_TOKENS:
                for lineno, line in enumerate(_strip_comments(source).splitlines(), start=1):
                    if token in line:
                        try:
                            display = str(path.relative_to(Path(__file__).resolve().parents[3]))
                        except ValueError:
                            display = str(path)
                        violations.append(f"{display}:{lineno}: {token}")
    if violations:
        raise RuntimeError(
            "金标准泄漏防护触发：提取链路引用了金标准/评测数据路径\n" + "\n".join(violations)
        )
