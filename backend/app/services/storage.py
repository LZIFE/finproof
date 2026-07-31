"""文件存储管理。

目录规范（Phase 2）：

    storage/
    └── documents/
        └── <document_id>/
            ├── original.<ext>      # 原始上传文件（系统生成文件名）
            └── extraction.json     # 解析产物（页码/文本块坐标等元数据，不含全文）

安全要点：
- 磁盘路径完全由系统生成：document_id 强制为 int 且 >= 1，绝不使用用户文件名，
  从根上防止路径穿越；
- 不覆盖已有文件（FileExistsError）；
- 删除文档目录由本模块统一负责。
"""

import json
import logging
import shutil
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def storage_root() -> Path:
    return Path(get_settings().storage_dir)


def _document_dir(document_id: int) -> Path:
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id < 1:
        raise ValueError(f"非法 document_id: {document_id!r}")
    return storage_root() / "documents" / str(document_id)


def save_original(document_id: int, data: bytes, ext: str) -> Path:
    """保存原始文件到 storage/documents/<id>/original.<ext>；已存在则拒绝覆盖。"""
    doc_dir = _document_dir(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    dest = doc_dir / f"original.{ext}"
    if dest.exists():
        raise FileExistsError(f"存储文件已存在，拒绝覆盖: {dest}")
    dest.write_bytes(data)
    logger.info("saved original file document_id=%s path=%s bytes=%s", document_id, dest, len(data))
    return dest


def write_extraction_json(document_id: int, payload: dict) -> Path:
    """保存解析产物元数据（页码与文本块坐标，不含全文）。"""
    doc_dir = _document_dir(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    dest = doc_dir / "extraction.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def remove_document_dir(document_id: int) -> None:
    """删除某文档的存储目录（解析失败回滚时使用）。"""
    doc_dir = _document_dir(document_id)
    if doc_dir.exists():
        shutil.rmtree(doc_dir)
        logger.info("removed storage dir document_id=%s path=%s", document_id, doc_dir)
