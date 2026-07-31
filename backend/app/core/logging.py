"""日志配置。

约定（Phase 2）：每次解析至少记录 document_id / 文件名 / 大小 / SHA-256 /
页数 / 总字符数 / 解析耗时 / 状态 / 错误类型；日志不得记录文件内容或敏感信息。
"""

import logging
import sys

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """配置根 logger（幂等）。"""
    root = logging.getLogger()
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.setLevel(level)
    root.addHandler(handler)
