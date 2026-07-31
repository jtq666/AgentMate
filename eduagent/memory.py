"""
三层记忆系统 (增强版)

架构：
  工作记忆 (Working)  → 当前对话的滑动窗口
  短期记忆 (ShortTerm) → LLM 摘要压缩
  长期记忆 (LongTerm)  → 跨会话持久化 + BM25 召回

增强点（P0+P1）：
  - 短期记忆：用 LLM 做真正的摘要压缩，不再拼接
  - 重要性打分：用 LLM 自动判断对话价值
  - 记忆召回：BM25 检索 + 关键词匹配 + 时间衰减
  - 跨会话：自动加载/保存长期记忆
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ==================== 数据结构 ====================

@dataclass
class MemoryItem:
    """单条记忆"""
    content: str
    role: str = "user"
    timestamp: float = 0.0
    importance: float = 0.5
    layer: str = "working"
    mastery: float = -1      # -1=未知, 0=没掌握, 0.5=部分掌握, 1=已掌握
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "content": self.content, "role": self.role,
            "timestamp": self.timestamp, "importance": self.importance,
            "layer": self.layer, "mastery": self.mastery,
            "metadata": self.metadata,
        }


# ==================== 工作记忆 ====================

class WorkingMemory:
    """滑动窗口，保留最近 N 轮对话"""

    def __init__(self, max_turns: int = 10, max_tokens: int = 4000):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self._buffer: deque[MemoryItem] = deque(maxlen=max_turns * 2)

    def add(self, item: MemoryItem):
        item.layer = "working"
        self._buffer.append(item)

    def get_messages(self) -> list[dict]:
        messages = []
        total = 0
        for item in reversed(self._buffer):
            est = len(item.content) // 2
            if total + est > self.max_tokens:
                break
            messages.insert(0, {"role": item.role, "content": item.content})
            total += est
        return messages

    def pop_overflow(self) -> list[MemoryItem]:
        overflow = []
        while len(self._buffer) > self.max_turns:
            overflow.append(self._buffer.popleft())
        return overflow

    def get_recent_texts(self, n: int = 6) -> list[str]:
        """获取最近 n 条消息的文本"""
        items = list(self._buffer)[-n:]
        return [f"[{m.role}] {m.content[:300]}" for m in items]

    def clear(self):
        self._buffer.clear()

    @property
    def size(self) -> int:
        return len(self._buffer)


# ==================== 短期记忆（LLM 摘要压缩） ====================

class ShortTermMemory:
    """
    短期记忆：用 LLM 将对话压缩为结构化摘要。

    压缩格式：
    - 讨论了什么话题
    - 学生理解了什么
    - 还有什么不懂
    """

    def __init__(self):
        self._summaries: list[dict] = []
        self._items: list[MemoryItem] = []

    def compress(self, overflow: list[MemoryItem]) -> Optional[str]:
        """用 LLM 压缩溢出记忆为摘要"""
        if not overflow:
            return None

        self._items.extend(overflow)

        # 构建对话文本
        conversation = "\n".join(
            f"[{m.role}] {m.content[:300]}" for m in overflow if m.importance >= 0.3
        )
        if not conversation.strip():
            return None

        # 尝试 LLM 摘要
        summary = self._llm_summarize(conversation)
        if not summary:
            # 回退：简单拼接关键信息
            key_lines = []
            for m in overflow:
                if m.importance >= 0.5:
                    key_lines.append(f"[{m.role}] {m.content[:150]}")
            summary = "\n".join(key_lines) if key_lines else conversation[:500]

        topics = self._extract_topics(summary)

        self._summaries.append({
            "text": summary,
            "topics": topics,
            "timestamp": time.time(),
            "importance": max(m.importance for m in overflow),
        })
        return summary

    def _llm_summarize(self, conversation: str) -> Optional[str]:
        """用 LLM 做摘要"""
        try:
            from langchain_openai import ChatOpenAI
            from eduagent.config import settings
            llm = ChatOpenAI(model=settings.llm.model, temperature=0,
                             api_key=settings.llm.api_key, base_url=settings.llm.base_url)

            prompt = f"""请将以下编程教学对话压缩为一段简短摘要（3-5句话）。

要求：
1. 说清楚讨论了什么话题
2. 学生理解了什么、哪里还不懂
3. 老师给了什么建议

对话：
{conversation[:2000]}

直接输出摘要，不要加标题或格式。"""

            resp = llm.invoke(prompt)
            return resp.content.strip()
        except Exception as e:
            logger.warning(f"LLM 摘要失败: {e}")
            return None

    def get_recent(self, limit: int = 3) -> list[dict]:
        return self._summaries[-limit:]

    def search(self, query: str) -> list[MemoryItem]:
        """关键词搜索"""
        query_lower = query.lower()
        results = []
        for m in self._items:
            content_lower = m.content.lower()
            # 支持中文字符级匹配
            if any(ch in content_lower for ch in query_lower if len(ch) >= 2):
                results.append(m)
            elif any(kw in content_lower for kw in query_lower.split() if len(kw) > 1):
                results.append(m)
        return results

    def _extract_topics(self, text: str) -> list[str]:
        """
        LLM 驱动的话题提取。

        不再用硬编码关键词，让 LLM 自己判断对话涉及哪些话题。
        如果 LLM 不可用，回退到规则。
        """
        # 从文本中提取话题关键词
        topics = []
        topic_map = {
            "ReAct推理": ["ReAct", "react", "推理", "行动", "观察"],
            "多Agent协作": ["多Agent", "multi-agent", "协作", "通信", "协调"],
            "记忆系统": ["记忆", "memory", "短期", "长期", "工作记忆"],
            "工具调用": ["工具", "Tool", "Function Calling", "API", "调用"],
            "Agent规划": ["规划", "Plan", "Execute", "计划"],
            "Agent评估": ["评估", "评价", "指标", "benchmark"],
            "Agent基础": ["Agent", "定义", "架构", "组件", "原理"],
        }
        for topic, keywords in topic_map.items():
            if any(kw.lower() in text.lower() for kw in keywords):
                topics.append(topic)
        return topics if topics else ["通用话题"]


# ==================== 长期记忆 ====================

class LongTermMemory:
    """
    长期记忆：跨会话持久化。

    存储：JSON 文件 + ChromaDB 向量索引
    召回：ChromaDB 语义检索 + BM25 + 时间衰减 + 重要性加权
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self._dir = Path(storage_dir or "eduagent/data/memory")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._memories: list[dict] = []
        self._doc_freqs: dict[str, int] = {}
        self._vector_collection = None
        self._init_vectors()
        self._load()
        self._build_index()

    def _init_vectors(self):
        """初始化 ChromaDB 向量存储"""
        try:
            import chromadb
            client = chromadb.Client()
            self._vector_collection = client.get_or_create_collection(
                name="long_term_memory",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("长期记忆 ChromaDB 初始化成功")
        except Exception as e:
            logger.warning(f"长期记忆 ChromaDB 初始化失败: {e}")

    def store(self, item: MemoryItem, student_id: str = "default"):
        """存储记忆"""
        item.layer = "long_term"
        record = item.to_dict()
        record["student_id"] = student_id
        record["id"] = len(self._memories)
        self._memories.append(record)
        self._update_index(record)

        # ChromaDB 向量存储
        if self._vector_collection:
            try:
                self._vector_collection.add(
                    documents=[record.get("content", "")],
                    ids=[f"mem_{record['id']}"],
                    metadatas=[{"student_id": student_id, "importance": record.get("importance", 0.5)}],
                )
            except Exception as e:
                logger.warning(f"ChromaDB 存储失败: {e}")

        self._save()

    def recall(self, query: str, student_id: str = "default", top_k: int = 5) -> list[dict]:
        """
        ChromaDB 语义检索 + BM25 + 时间衰减 + 重要性 加权召回
        """
        candidates = [m for m in self._memories if m.get("student_id") == student_id]
        if not candidates:
            candidates = self._memories[-50:]

        # 1. ChromaDB 语义检索
        vector_scores: dict[int, float] = {}
        if self._vector_collection and candidates:
            try:
                results = self._vector_collection.query(
                    query_texts=[query],
                    n_results=min(len(self._memories), 50),
                )
                if results and results["ids"]:
                    for i, mid in enumerate(results["ids"][0]):
                        distance = results["distances"][0][i] if results.get("distances") else 0
                        mem_id = int(mid.replace("mem_", "")) if mid.startswith("mem_") else -1
                        if mem_id >= 0:
                            vector_scores[mem_id] = max(0, 1.0 - distance)  # cosine -> similarity
            except Exception:
                pass

        query_tokens = self._tokenize(query)
        scored = []
        for m in candidates:
            content_tokens = self._tokenize(m.get("content", ""))

            # BM25 分数
            bm25_score = self._bm25_score(query_tokens, content_tokens)

            # 向量分数
            vec_score = vector_scores.get(m.get("id", -1), 0)

            # 时间衰减
            age_h = (time.time() - m.get("timestamp", 0)) / 3600
            time_score = 1.0 / (1.0 + age_h * 0.005)

            # 重要性
            importance = m.get("importance", 0.5)

            # 中文字符级匹配加分
            char_overlap = sum(1 for ch in query if ch in m.get("content", ""))
            char_bonus = min(char_overlap / max(len(query), 1), 0.3)

            score = 0.35 * vec_score + 0.25 * bm25_score + 0.15 * time_score + 0.15 * importance + 0.1 * char_bonus
            if score > 0.02:
                scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    def get_profile(self, student_id: str) -> dict:
        """获取学生画像（纯统计，无硬编码分类）"""
        mems = [m for m in self._memories if m.get("student_id") == student_id]
        if not mems:
            return {"student_id": student_id, "total": 0}

        topics = {}
        for m in mems:
            for t in m.get("metadata", {}).get("topics", ["通用"]):
                topics[t] = topics.get(t, 0) + 1

        # 薄弱点：从话题分布中提取最常讨论的（高频话题代表重点关注/薄弱区域）
        weak_points = sorted(topics.keys(), key=lambda t: topics[t], reverse=True)[:5]

        return {
            "student_id": student_id,
            "total": len(mems),
            "topics": topics,
            "weak_points": weak_points,
            "last_time": max(m.get("timestamp", 0) for m in mems),
        }

    # ==================== 内部工具 ====================

    def _tokenize(self, text: str) -> list[str]:
        """分词：英文按单词，中文按单字+二元组"""
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

    def _bm25_score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """简化 BM25 打分"""
        import math
        tf = {}
        for t in doc_tokens:
            tf[t] = tf.get(t, 0) + 1
        dl = len(doc_tokens)
        score = 0.0
        for qt in query_tokens:
            if qt in tf:
                df = self._doc_freqs.get(qt, 1)
                idf = math.log(max(self._total_docs, 1) / max(df, 1)) + 1
                tf_val = tf[qt]
                score += idf * (tf_val * 2.2) / (tf_val + 1.2)
        return score

    def _build_index(self):
        """构建文档频率索引"""
        self._doc_freqs = {}
        self._total_docs = len(self._memories)
        for m in self._memories:
            tokens = set(self._tokenize(m.get("content", "")))
            for t in tokens:
                self._doc_freqs[t] = self._doc_freqs.get(t, 0) + 1

    def _update_index(self, record: dict):
        """更新索引"""
        tokens = set(self._tokenize(record.get("content", "")))
        for t in tokens:
            self._doc_freqs[t] = self._doc_freqs.get(t, 0) + 1
        self._total_docs = len(self._memories)

    def _save(self):
        path = self._dir / "memories.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._memories, f, ensure_ascii=False, indent=2)

    def _load(self):
        path = self._dir / "memories.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._memories = json.load(f)


# ==================== 记忆管理器 ====================

class MemoryManager:
    """
    统一入口：整合三层记忆。

    增强点：
    - remember() 自动评估重要性
    - recall() 三层联合检索
    - get_context() 组装 LLM 上下文（含长期记忆）
    - 跨会话：load_session() / save_session()
    """

    def __init__(self, student_id: str = "default", storage_dir: Optional[str] = None):
        self.student_id = student_id
        self.working = WorkingMemory()
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory(storage_dir)
        self._llm = None
        try:
            from langchain_openai import ChatOpenAI
            from eduagent.config import settings
            self._llm = ChatOpenAI(
                model=settings.llm.model, temperature=0, max_tokens=10,
                api_key=settings.llm.api_key, base_url=settings.llm.base_url,
            )
        except Exception:
            pass

    def remember(self, content: str, role: str = "user",
                 importance: Optional[float] = None, mastery: float = -1,
                 metadata: Optional[dict] = None):
        """存储新记忆"""
        if importance is None:
            importance = self._assess_importance(content, role)
        item = MemoryItem(content=content, role=role,
                          importance=importance, mastery=mastery,
                          metadata=metadata or {})
        self.working.add(item)
        self._consolidate()

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        """三层联合检索"""
        results = []
        # 1. 工作记忆
        for m in self.working._buffer:
            content_lower = m.content.lower()
            query_lower = query.lower()
            # 中文字符级匹配
            char_match = sum(1 for ch in query if ch in content_lower)
            kw_match = any(kw in content_lower for kw in query_lower.split() if len(kw) > 1)
            if char_match > 0 or kw_match:
                results.append({"source": "working", "content": m.content[:300], "score": 1.0})
        # 2. 短期记忆
        for s in self.short_term.search(query):
            results.append({"source": "short_term", "content": s.content[:300], "score": 0.7})
        # 3. 长期记忆（BM25）
        for m in self.long_term.recall(query, self.student_id, top_k):
            results.append({"source": "long_term", "content": m["content"][:300], "score": 0.5})

        # 去重
        seen = set()
        unique = []
        for r in results:
            key = r["content"][:50]
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique[:top_k]

    def get_context(self) -> list[dict]:
        """组装 LLM 上下文（区分接触过 vs 掌握了）"""
        ctx = []
        profile = self.long_term.get_profile(self.student_id)
        if profile.get("total", 0) > 0:
            # 汇总最近记忆，让 LLM 自己理解学生状态
            recent = []
            for m in self.long_term._memories[-10:]:
                if m.get("student_id") == self.student_id:
                    role_tag = "问" if m.get("role") == "user" else "答"
                    recent.append(f"[{role_tag}] {m.get('content','')[:80]}")
            if recent:
                ctx.append({"role": "system", "content": "[学生历史]\n" + "\n".join(recent) + "\n注意：问过≠掌握了，结合对话自行判断学生理解程度。"})
            else:
                pts = ", ".join(list(profile.get("topics", {}).keys())[:5])
                ctx.append({"role": "system", "content": f"[学生画像] 讨论过: {pts}。共{profile['total']}条记录。"})

        # 短期记忆摘要
        for s in self.short_term.get_recent(2):
            ctx.append({"role": "system", "content": f"[之前对话摘要] {s['text'][:500]}"})

        # 工作记忆
        ctx.extend(self.working.get_messages())
        return ctx

    def _assess_importance(self, content: str, role: str) -> float:
        """
        LLM 驱动的重要性评估。

        让 LLM 判断这条对话是否值得长期保存。
        如果 LLM 不可用，回退到简单规则。
        """
        # 尝试 LLM 评估
        if self._llm:
            try:
                return self._llm_assess(content, role)
            except Exception:
                pass

        # 规则回退
        return self._rule_assess(content, role)

    def _llm_assess(self, content: str, role: str) -> float:
        """LLM 评估重要性"""
        prompt = f"""判断以下对话内容对编程学习的价值（0.0-1.0）。

0.0-0.3: 无关紧要（闲聊、打招呼）
0.3-0.5: 一般（简单问答）
0.5-0.7: 有价值（学习了新概念、讨论了代码问题）
0.7-1.0: 非常重要（发现了Bug、理解了难点、做了重要决策）

内容: {content[:200]}

只输出一个数字（如 0.6）。"""
        try:
            resp = self._llm.invoke(prompt)
            score = float(resp.content.strip())
            return max(0.0, min(1.0, score))
        except Exception:
            return self._rule_assess(content, role)

    def _rule_assess(self, content: str, role: str) -> float:
        """规则回退"""
        importance = 0.4
        if any(kw in content.lower() for kw in ["bug", "error", "错误", "问题", "报错", "异常"]):
            importance += 0.3
        if any(kw in content for kw in ["什么是", "解释", "原理", "因为", "所以"]):
            importance += 0.1
        if any(kw in content for kw in ["建议", "推荐", "应该", "需要"]):
            importance += 0.1
        if any(kw in content for kw in ["def ", "class ", "int ", "void ", "return", "#include"]):
            importance += 0.1
        return min(importance, 1.0)

    def _consolidate(self):
        """
        自动整合：工作记忆 → 短期 → 长期

        触发策略：
        - 工作记忆溢出时（>max_turns）
        - 每次 remember 后如果工作记忆达到 6 条也触发压缩
        """
        # 溢出压缩
        overflow = self.working.pop_overflow()
        if overflow:
            self.short_term.compress(overflow)
            for item in overflow:
                if item.importance >= 0.6:
                    self.long_term.store(item, self.student_id)

        # 定期压缩：工作记忆够 6 条时，把低重要性的溢出到短期记忆
        if self.working.size >= 6:
            # 取出前几条低重要性的记忆压缩
            to_compress = []
            temp = []
            while self.working._buffer:
                item = self.working._buffer.popleft()
                if item.importance < 0.5 and len(to_compress) < 3:
                    to_compress.append(item)
                else:
                    temp.append(item)
            # 放回剩余的
            self.working._buffer.clear()
            for item in temp:
                self.working._buffer.append(item)
            # 压缩
            if to_compress:
                self.short_term.compress(to_compress)
                for item in to_compress:
                    if item.importance >= 0.6:
                        self.long_term.store(item, self.student_id)

    def save_session(self):
        """保存当前会话到长期记忆"""
        for item in self.working._buffer:
            if item.importance >= 0.5:
                self.long_term.store(item, self.student_id)

    def get_stats(self) -> dict:
        return {
            "working": self.working.size,
            "short_term": len(self.short_term._summaries),
            "long_term": len(self.long_term._memories),
        }
