"""Phase 23.17 Step 3 — 本地 Embedding 语义检索（无外部 embedding 库时的本地抽象）

要求（任务）：
- claim embedding
- block embedding
- cosine similarity
- persistent cache（持久缓存，非内存）

实现（本地抽象）：
- LocalEmbedder：字符 n-gram HashingVectorizer（2-4 gram，64k 维哈希，L2 归一化）
  → 固定维度向量，不依赖词表，可增量；作为"无外部模型时的本地 embedding"。
- persistent cache：每 doc 的 block embedding 矩阵（npz 稀疏矩阵 + block_ids + 特征配置 hash）
  存到 backend/artifacts/embeddings/<doc_id>.npz，首次计算后从磁盘加载。
- embed_candidates：claim embedding 与全部 block embedding 余弦相似，返回 top-N block ids。

被 hybrid_retrieval.hybrid_candidates 调用（三路 union：BM25 + Embedding + Rule）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import HashingVectorizer

from app.models import DocumentBlock

BACKEND = Path(__file__).resolve().parents[3]  # backend/
EMBED_CACHE_DIR = BACKEND / "artifacts" / "embeddings"

# 本地 embedding 配置（固定，保证缓存一致性）
_NGRAM_RANGE = (2, 4)
_N_FEATURES = 65536
_COSINE_LIMIT = 200


def _feature_signature() -> str:
    """特征配置 hash（缓存失效判定）。"""
    return hashlib.sha256(f"ngram={_NGRAM_RANGE}-nfeat={_N_FEATURES}".encode()).hexdigest()[:12]


class LocalEmbedder:
    """本地 embedding：字符 n-gram hashing + L2 归一化 + 余弦。"""

    def __init__(self) -> None:
        self._vectorizer = HashingVectorizer(
            analyzer="char_wb",
            ngram_range=_NGRAM_RANGE,
            n_features=_N_FEATURES,
            norm="l2",
            alternate_sign=False,
        )
        self._block_cache: dict[int, tuple] = {}  # doc_id -> (block_ids, matrix)

    # ---- 持久缓存 ----
    def _cache_path(self, doc_id: int) -> Path:
        return EMBED_CACHE_DIR / f"doc{doc_id}_v{_feature_signature()}.npz"

    def _cache_meta_path(self, doc_id: int) -> Path:
        return EMBED_CACHE_DIR / f"doc{doc_id}_v{_feature_signature()}.json"

    def _load_cache(self, doc_id: int):
        npz_path = self._cache_path(doc_id)
        meta_path = self._cache_meta_path(doc_id)
        if npz_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            mat = sparse.load_npz(npz_path)
            return meta["block_ids"], mat
        return None

    def _save_cache(self, doc_id: int, block_ids: list[int], mat) -> None:
        EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        sparse.save_npz(self._cache_path(doc_id), mat.tocsr())
        self._cache_meta_path(doc_id).write_text(
            json.dumps({"doc_id": doc_id, "block_ids": block_ids, "feature_signature": _feature_signature()}),
            encoding="utf-8",
        )

    # ---- block embedding（带持久缓存）----
    def embed_blocks(self, session, doc_id: int):
        """返回 (block_ids, 归一化稀疏矩阵)；优先加载持久缓存，否则计算并落盘。"""
        if doc_id in self._block_cache:
            return self._block_cache[doc_id]
        cached = self._load_cache(doc_id)
        if cached is not None:
            self._block_cache[doc_id] = cached
            return cached
        rows = (
            session.query(DocumentBlock.id, DocumentBlock.text)
            .filter(DocumentBlock.document_id == doc_id, DocumentBlock.text.isnot(None))
            .all()
        )
        texts = [(bid, t or "") for bid, t in rows]
        if not texts:
            return [], sparse.csr_matrix((0, _N_FEATURES))
        block_ids = [b for b, _ in texts]
        mat = self._vectorizer.transform([t for _, t in texts])
        self._save_cache(doc_id, block_ids, mat)
        self._block_cache[doc_id] = (block_ids, mat)
        return block_ids, mat

    # ---- claim embedding ----
    def embed_claim(self, text: str):
        if not text or not text.strip():
            return sparse.csr_matrix((1, _N_FEATURES))
        return self._vectorizer.transform([text])

    # ---- cosine top-N ----
    def top_n(self, doc_id: int, block_ids: list[int], mat, claim_vec, limit: int = _COSINE_LIMIT) -> list[int]:
        """返回与 claim 余弦相似最高的 top-N block ids（相似度 > 0）。"""
        if mat.shape[0] == 0 or claim_vec.nnz == 0:
            return []
        scores = (mat @ claim_vec.T).toarray().ravel()
        ranked = sorted(zip(block_ids, scores), key=lambda x: -x[1])
        return [b for b, s in ranked[:limit] if s > 0]


_embedder = LocalEmbedder()


def embed_candidates(session, doc_id: int, claim: dict, limit: int = _COSINE_LIMIT) -> list[int]:
    """claim → block embedding 余弦检索，返回 top-N block ids。"""
    claim_text = " ".join(
        p for p in (
            str(claim.get("original_text") or claim.get("claim_text") or ""),
            str(claim.get("metric") or ""),
            str(claim.get("period") or ""),
        ) if p
    )
    if not claim_text.strip():
        return []
    block_ids, mat = _embedder.embed_blocks(session, doc_id)
    if not block_ids:
        return []
    claim_vec = _embedder.embed_claim(claim_text)
    return _embedder.top_n(doc_id, block_ids, mat, claim_vec, limit=limit)
