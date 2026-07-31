"""文件安全校验（Phase 2）。

只负责"文件本身是否可接受"，不做任何业务判断。覆盖检查项：
1. 扩展名白名单（.pdf / .md / .markdown）
2. MIME / 魔数检查（PDF 要求 %PDF 文件头；Markdown 拒绝二进制内容）
3. PDF 文件头检查
4. 文件大小限制（由调用方传入上限）
5. 空文件拒绝
6. 路径穿越防护（文件名清洗：只取 basename、限长、兜底名）
7. 重复哈希检查（compute_sha256 供服务层去重）
8. 加密 PDF 检测（PyMuPDF needs_pass）
9. 无文本 PDF 识别：由解析层抛出 NoTextError（见 parser/pdf_parser.py），
   服务层映射为 UNSUPPORTED——不在本模块重复解析
10. 解析异常回滚：由服务层事务处理（见 document_service.py）

统一错误：AppError(message, status_code, code, details)，响应结构 {"error": {...}}。
"""

import hashlib
from pathlib import PurePath

import fitz

from app.core.exceptions import AppError

ALLOWED_EXTENSIONS = {".pdf", ".md", ".markdown"}
EXT_TO_TYPE = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown"}
PDF_MAGIC = b"%PDF"
MAX_FILENAME_LEN = 200
DEFAULT_FILENAME = "upload"


def extract_extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def sanitize_filename(filename: str) -> str:
    """清洗用户文件名：仅保留 basename、去除路径分隔符、限长、兜底。"""
    if not filename:
        return DEFAULT_FILENAME
    name = PurePath(filename.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        return DEFAULT_FILENAME
    return name[:MAX_FILENAME_LEN]


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_pdf(data: bytes) -> None:
    if not data.startswith(PDF_MAGIC):
        raise AppError(
            "不是有效的 PDF 文件（缺少 %PDF 文件头）", status_code=415, code="INVALID_FILE"
        )
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 —— 损坏 PDF 由解析层标记 FAILED
        raise AppError(
            f"PDF 文件无法打开（可能已损坏）: {exc}", status_code=415, code="INVALID_FILE"
        ) from exc
    try:
        if doc.needs_pass:
            raise AppError("PDF 已加密，不支持解析", status_code=415, code="ENCRYPTED_PDF")
    finally:
        doc.close()


def _check_markdown(data: bytes) -> None:
    # 拒绝二进制/含 NUL 字节的内容（MIME 近似检查）
    if b"\x00" in data[:4096]:
        raise AppError("Markdown 文件内容不是文本", status_code=415, code="INVALID_FILE")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        # 允许常见中文编码（gbk 等）——只拦截明显非文本
        try:
            data.decode("gbk")
        except UnicodeDecodeError as exc:
            raise AppError("Markdown 文件内容不是文本", status_code=415, code="INVALID_FILE") from exc


def validate_upload(filename: str, data: bytes, max_size_bytes: int) -> str:
    """校验上传文件，返回归一化 document_type（pdf | markdown）。

    校验顺序：扩展名 → 空文件 → 大小 → 类型内容。任一失败抛出 AppError。
    """
    ext = extract_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError(
            f"不支持的文件类型: {ext or '(无扩展名)'}（仅支持 .pdf / .md / .markdown）",
            status_code=415,
            code="UNSUPPORTED_DOCUMENT",
        )
    if not data:
        raise AppError("上传文件为空", status_code=400, code="EMPTY_FILE")
    if len(data) > max_size_bytes:
        raise AppError(
            f"文件大小 {len(data)} 字节超过上限 {max_size_bytes} 字节",
            status_code=413,
            code="FILE_TOO_LARGE",
        )
    if ext == ".pdf":
        _check_pdf(data)
    else:
        _check_markdown(data)
    return EXT_TO_TYPE[ext]
