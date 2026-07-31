"""
知识检索器

技术栈：ChromaDB 向量检索 + BM25 关键词检索 + RRF 融合排序

面试深度点：
1. ChromaDB：向量数据库，内置 Embedding (all-MiniLM-L6-v2)
2. BM25：经典关键词检索，与向量互补
3. RRF (Reciprocal Rank Fusion)：多路召回融合，无需分数归一化
4. 文档分块策略：按语义边界切分
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RetrievedDoc:
    """检索结果"""
    content: str
    source: str
    score: float
    method: str = ""


class KnowledgeBase:
    """
    知识库：ChromaDB 向量检索 + BM25 关键词检索 + RRF 融合

    面试讲点：
    - ChromaDB：轻量级向量数据库，内置 Embedding
    - BM25：经典关键词检索，与向量互补
    - RRF：1/(k+rank) 多路融合，无需分数校准
    """

    def __init__(self, collection_name: str = "agentmate_kb", persist_dir: str = None):
        self._collection_name = collection_name
        self._docs: list[dict] = []
        self._doc_freqs: dict[str, int] = {}
        self._total_docs = 0
        self._persist_dir = persist_dir or "agentmate/data"

        # ChromaDB
        self._collection = None
        self._init_chromadb()

        # 加载已保存的动态文档
        self._load_persisted()

    def _init_chromadb(self):
        try:
            import chromadb
            self._chroma_client = chromadb.Client()
            self._collection = self._chroma_client.create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("ChromaDB 初始化成功")
        except Exception as e:
            logger.warning(f"ChromaDB 初始化失败: {e}")

    def add(self, content: str, source: str = "", metadata: dict = None):
        """添加文档"""
        doc_id = f"doc_{len(self._docs)}"
        doc = {"id": doc_id, "content": content, "source": source, "metadata": metadata or {}}
        self._docs.append(doc)

        # BM25 索引
        for t in set(self._tokenize(content)):
            self._doc_freqs[t] = self._doc_freqs.get(t, 0) + 1
        self._total_docs = len(self._docs)

        # ChromaDB
        if self._collection:
            try:
                self._collection.add(
                    documents=[content], ids=[doc_id],
                    metadatas=[{**(metadata or {}), "source": source}],
                )
            except Exception as e:
                logger.warning(f"ChromaDB 写入失败: {e}")

        # 动态添加的论文持久化
        if source.startswith("paper://") or source.startswith("arxiv://"):
            self._save_persisted()

    def _save_persisted(self):
        """保存动态添加的文档"""
        import json
        from pathlib import Path
        p = Path(self._persist_dir) / "kb_dynamic.json"
        docs = [d for d in self._docs if d["source"].startswith(("paper://", "arxiv://"))]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

    def _load_persisted(self):
        """加载已保存的动态文档"""
        import json
        from pathlib import Path
        p = Path(self._persist_dir) / "kb_dynamic.json"
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                docs = json.load(f)
            for doc in docs:
                self.add(doc["content"], doc["source"], doc.get("metadata", {}))

    # ==================== 向量检索 ====================

    def vector_search(self, query: str, top_k: int = 5) -> list[RetrievedDoc]:
        """ChromaDB 语义检索"""
        if not self._collection or self._collection.count() == 0:
            return []
        try:
            n = min(top_k, self._collection.count())
            results = self._collection.query(query_texts=[query], n_results=n)
            docs = []
            if results and results["documents"]:
                for i, content in enumerate(results["documents"][0]):
                    dist = results["distances"][0][i] if results.get("distances") else 0
                    src = results["metadatas"][0][i].get("source", "") if results.get("metadatas") else ""
                    docs.append(RetrievedDoc(content=content, source=src,
                                             score=max(1.0 - dist, 0), method="chroma"))
            return docs
        except Exception as e:
            logger.warning(f"ChromaDB 检索失败: {e}")
            return []

    # ==================== BM25 检索 ====================

    def bm25_search(self, query: str, top_k: int = 5) -> list[RetrievedDoc]:
        """BM25 关键词检索"""
        if not self._docs:
            return []
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        avg_dl = sum(len(self._tokenize(d["content"])) for d in self._docs) / max(self._total_docs, 1)
        scored = []
        for doc in self._docs:
            d_tokens = self._tokenize(doc["content"])
            tf = defaultdict(int)
            for t in d_tokens:
                tf[t] += 1
            score = 0.0
            for qt in query_tokens:
                if qt in self._doc_freqs:
                    idf = math.log(max(self._total_docs, 1) / max(self._doc_freqs[qt], 1)) + 1
                    tf_val = tf.get(qt, 0)
                    score += idf * (tf_val * 2.2) / (tf_val + 1.2 * (1 - 0.75 + 0.75 * len(d_tokens) / max(avg_dl, 1)))
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [RetrievedDoc(content=d["content"], source=d["source"],
                             score=s, method="bm25") for s, d in scored[:top_k]]

    # ==================== RRF 融合 ====================

    def search(self, query: str, top_k: int = 5) -> list[RetrievedDoc]:
        """
        混合检索：向量 + BM25 → RRF 融合

        策略：向量检索权重 x1.5，BM25 权重 x1.0
        原因：向量检索对中文语义理解更好
        """
        vec_results = self.vector_search(query, top_k=top_k * 3)
        bm25_results = self.bm25_search(query, top_k=top_k * 3)

        rrf_scores: dict[str, float] = defaultdict(float)
        doc_map: dict[str, RetrievedDoc] = {}
        k = 60

        # 向量检索权重 x1.5
        for rank, r in enumerate(vec_results):
            key = r.content[:80]
            rrf_scores[key] += 1.5 / (k + rank + 1)
            doc_map[key] = r

        # BM25 权重 x1.0
        for rank, r in enumerate(bm25_results):
            key = r.content[:80]
            rrf_scores[key] += 1.0 / (k + rank + 1)
            if key not in doc_map:
                doc_map[key] = r

        sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        results = []
        for key in sorted_keys[:top_k]:
            doc = doc_map[key]
            results.append(RetrievedDoc(content=doc.content, source=doc.source,
                                        score=rrf_scores[key], method="rrf"))
        return results

    @property
    def size(self) -> int:
        return len(self._docs)

    def _tokenize(self, text: str) -> list[str]:
        tokens = []
        tokens.extend(re.findall(r"[a-zA-Z_]\w+", text.lower()))
        chinese = re.findall(r"[一-鿿]+", text)
        for seg in chinese:
            for ch in seg:
                tokens.append(ch)
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i+2])
        stops = {"的", "了", "是", "在", "和", "有", "就", "也", "都", "不", "能", "把"}
        return [t for t in tokens if t not in stops and len(t) >= 1]
