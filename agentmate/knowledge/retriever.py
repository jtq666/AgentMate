"""ChromaDB + BM25 + RRF 混合检索。"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RetrievedDoc:
    content: str
    source: str
    score: float
    method: str = ""
    doc_id: str = ""
    metadata: dict = field(default_factory=dict)


class KnowledgeBase:
    """可持久化的混合知识库。

    ChromaDB 负责语义召回，内存 BM25 负责关键词召回，RRF 用排名而非
    原始分数完成融合，避免两路分数尺度不一致。
    """

    def __init__(self, collection_name: str = "agentmate_kb", persist_dir: str | None = None):
        self._collection_name = collection_name
        self._persist_dir = Path(persist_dir or "agentmate/data")
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._docs: list[dict] = []
        self._doc_freqs: dict[str, int] = {}
        self._total_docs = 0
        self._lock = threading.RLock()
        self._collection = None
        self._init_chromadb()
        self._load_persisted_legacy()

    def _init_chromadb(self) -> None:
        try:
            import chromadb

            self._chroma_client = chromadb.PersistentClient(path=str(self._persist_dir / "chroma"))
            self._collection = self._chroma_client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            stored = self._collection.get(include=["documents", "metadatas"])
            for doc_id, content, metadata in zip(
                stored.get("ids", []), stored.get("documents", []), stored.get("metadatas", [])
            ):
                metadata = metadata or {}
                self._docs.append({
                    "id": doc_id,
                    "content": content,
                    "source": metadata.get("source", ""),
                    "metadata": metadata,
                })
            self._rebuild_bm25()
            logger.info("ChromaDB loaded %s chunks", len(self._docs))
        except Exception as exc:
            logger.warning("ChromaDB unavailable, BM25 fallback enabled: %s", exc)

    def add(self, content: str, source: str = "", metadata: dict | None = None) -> str:
        content = content.strip()
        if not content:
            return ""
        with self._lock:
            for existing in self._docs:
                if existing["content"] == content and existing["source"] == source:
                    return existing["id"]
            metadata = dict(metadata or {})
            source_type = metadata.get("source_type") or (
                source.split("://", 1)[0] if "://" in source else "course"
            )
            doc_id = str(metadata.get("document_id") or f"doc_{uuid.uuid4().hex}")
            metadata.update({
                "source": source,
                "source_type": source_type,
                "document_id": doc_id,
                "task_id": str(metadata.get("task_id", "")),
            })
            doc = {"id": doc_id, "content": content, "source": source, "metadata": metadata}
            self._docs.append(doc)
            self._rebuild_bm25()
            if self._collection is not None:
                try:
                    self._collection.add(documents=[content], ids=[doc_id], metadatas=[metadata])
                except Exception as exc:
                    logger.warning("ChromaDB write failed: %s", exc)
            if self._is_dynamic_source(source):
                self._save_legacy_json()
            return doc_id

    @staticmethod
    def _is_dynamic_source(source: str) -> bool:
        return source.startswith(("paper://", "arxiv://", "user://", "file://"))

    def _rebuild_bm25(self) -> None:
        self._doc_freqs = {}
        self._total_docs = len(self._docs)
        for doc in self._docs:
            for token in set(self._tokenize(doc.get("content", ""))):
                self._doc_freqs[token] = self._doc_freqs.get(token, 0) + 1

    def delete_at(self, index: int) -> dict | None:
        with self._lock:
            if not 0 <= index < len(self._docs):
                return None
            removed = self._docs.pop(index)
            if self._collection is not None:
                try:
                    self._collection.delete(ids=[removed["id"]])
                except Exception as exc:
                    logger.warning("ChromaDB delete failed: %s", exc)
            self._rebuild_bm25()
            self._save_legacy_json()
            return removed

    def update_title_at(self, index: int, title: str) -> dict | None:
        with self._lock:
            if not 0 <= index < len(self._docs):
                return None
            doc = self._docs[index]
            doc["metadata"]["heading"] = title.strip()
            if self._collection is not None:
                try:
                    self._collection.update(
                        ids=[doc["id"]], metadatas=[doc["metadata"]]
                    )
                except Exception as exc:
                    logger.warning("ChromaDB metadata update failed: %s", exc)
            self._save_legacy_json()
            return doc

    def clear(self) -> None:
        with self._lock:
            ids = [doc["id"] for doc in self._docs]
            if self._collection is not None and ids:
                self._collection.delete(ids=ids)
            self._docs.clear()
            self._rebuild_bm25()
            self._save_legacy_json()

    def _legacy_path(self) -> Path:
        return self._persist_dir / "kb_dynamic.json"

    def _save_legacy_json(self) -> None:
        docs = [doc for doc in self._docs if self._is_dynamic_source(doc["source"])]
        self._legacy_path().write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_persisted_legacy(self) -> None:
        path = self._legacy_path()
        if not path.exists():
            return
        try:
            for doc in json.loads(path.read_text(encoding="utf-8")):
                self.add(doc.get("content", ""), doc.get("source", ""), doc.get("metadata", {}))
        except Exception as exc:
            logger.warning("Legacy knowledge import skipped: %s", exc)

    def vector_search(self, query: str, top_k: int = 5) -> list[RetrievedDoc]:
        if self._collection is None or self._collection.count() == 0:
            return []
        try:
            results = self._collection.query(
                query_texts=[query], n_results=min(top_k, self._collection.count())
            )
            output = []
            for index, content in enumerate(results.get("documents", [[]])[0]):
                distance = results.get("distances", [[]])[0][index]
                metadata = results.get("metadatas", [[]])[0][index] or {}
                output.append(RetrievedDoc(
                    content=content,
                    source=metadata.get("source", ""),
                    score=max(1.0 - distance, 0.0),
                    method="chroma",
                    doc_id=results.get("ids", [[]])[0][index],
                    metadata=metadata,
                ))
            return output
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)
            return []

    def bm25_search(self, query: str, top_k: int = 5) -> list[RetrievedDoc]:
        if not self._docs:
            return []
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        avg_length = sum(len(self._tokenize(doc["content"])) for doc in self._docs) / len(self._docs)
        scored: list[tuple[float, dict]] = []
        for doc in self._docs:
            tokens = self._tokenize(doc["content"])
            frequencies: dict[str, int] = defaultdict(int)
            for token in tokens:
                frequencies[token] += 1
            score = 0.0
            for token in query_tokens:
                if token not in self._doc_freqs:
                    continue
                inverse = math.log((self._total_docs + 1) / self._doc_freqs[token]) + 1
                frequency = frequencies.get(token, 0)
                score += inverse * (frequency * 2.2) / (
                    frequency + 1.2 * (0.25 + 0.75 * len(tokens) / max(avg_length, 1))
                )
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [RetrievedDoc(
            content=doc["content"], source=doc["source"], score=score, method="bm25",
            doc_id=doc["id"], metadata=doc.get("metadata", {}),
        ) for score, doc in scored[:top_k] if score > 0]

    def search(self, query: str, top_k: int = 5) -> list[RetrievedDoc]:
        with self._lock:
            vectors = self.vector_search(query, top_k * 3)
            keywords = self.bm25_search(query, top_k * 3)
        scores: dict[str, float] = defaultdict(float)
        documents: dict[str, RetrievedDoc] = {}
        for rank, result in enumerate(vectors, 1):
            scores[result.doc_id] += 1.5 / (60 + rank)
            documents[result.doc_id] = result
        for rank, result in enumerate(keywords, 1):
            scores[result.doc_id] += 1.0 / (60 + rank)
            documents.setdefault(result.doc_id, result)
        ranked = sorted(scores, key=scores.get, reverse=True)[:top_k]
        return [RetrievedDoc(
            content=documents[key].content,
            source=documents[key].source,
            score=scores[key],
            method="rrf",
            doc_id=documents[key].doc_id,
            metadata=documents[key].metadata,
        ) for key in ranked]

    def search_relevant(
        self,
        query: str,
        top_k: int = 5,
        *,
        relevance_query: str | None = None,
    ) -> list[RetrievedDoc]:
        """Filter hybrid results through deterministic topic-term evidence.

        RRF expresses rank agreement rather than absolute relevance, so vector search
        can otherwise return the nearest Agent document for an unsupported topic.
        """
        candidates = self.search(query, max(top_k * 4, 20))
        terms = self._relevance_terms(relevance_query or query)
        if not terms:
            return []
        broad_english_terms = {
            "tool", "tools", "calling", "function", "memory", "planning", "plan",
            "thought", "action", "observation", "reasoning", "workflow", "system",
        }
        named_terms = {
            term for term in terms
            if term.isascii() and term not in broad_english_terms
        }

        relevant: list[tuple[float, RetrievedDoc]] = []
        for result in candidates:
            heading = str((result.metadata or {}).get("heading", ""))
            document_terms = set(self._tokenize(f"{heading} {result.source} {result.content}"))
            matched = terms.intersection(document_terms)
            if not matched or (named_terms and not named_terms.intersection(document_terms)):
                continue
            relevant.append((len(matched) / len(terms), result))
        relevant.sort(key=lambda item: (item[0], item[1].score), reverse=True)
        return [item[1] for item in relevant[:top_k]]

    @property
    def size(self) -> int:
        return len(self._docs)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens = re.findall(r"[a-zA-Z_]\w+", text.lower())
        for segment in re.findall(r"[\u4e00-\u9fff]+", text):
            tokens.extend(segment)
            tokens.extend(segment[index:index + 2] for index in range(len(segment) - 1))
        stop_words = {"的", "了", "是", "在", "和", "有", "就", "也", "都", "与", "能", "把"}
        return [token for token in tokens if token not in stop_words]

    @classmethod
    def _relevance_terms(cls, text: str) -> set[str]:
        generic = {
            "ai", "llm", "agent", "agents", "agentic", "智能体", "智能", "能体", "代理",
            "专题", "主题", "基础", "入门", "进阶", "深入", "概念", "方法", "系统", "机制",
            "评估", "研究", "综述", "面试", "准备", "理解",
        }
        return {
            token for token in cls._tokenize(text)
            if len(token) >= 2 and token not in generic
        }
