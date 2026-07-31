"""ORM 模型注册：导入本包后 Base.metadata 将包含全部表。"""

from app.models.document import Document, DocumentBlock, DocumentPage  # noqa: F401
