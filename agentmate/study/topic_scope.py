"""Deterministic topic-scope and local-evidence checks for study tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

PRESET_TOPICS = (
    "LLM Agent 基础",
    "ReAct",
    "工具调用",
    "多 Agent 协作",
    "RAG",
    "记忆系统",
)

RETRIEVAL_QUERIES = {
    "LLM Agent 基础": "Agent 智能体 定义 架构 自主决策",
    "ReAct": "ReAct Thought Action Observation 推理 行动 观察",
    "工具调用": "Agent 工具调用 Tool Calling Function Calling ToolRegistry",
    "多 Agent 协作": "多 Agent 多智能体 协作 通信 分工",
    "RAG": "Agent RAG 检索增强生成 向量检索",
    "记忆系统": "Agent 记忆 工作记忆 长期记忆 Memory",
}

_ENGLISH_SCOPE_TERMS = (
    "agent", "agentic", "react", "tool calling", "function calling",
    "toolregistry", "multi-agent", "multi agent", "rag", "reflexion",
    "model context protocol", "mcp", "agent memory", "agent planning",
)
_CHINESE_SCOPE_TERMS = (
    "智能体", "工具调用", "函数调用", "多agent", "多智能体", "检索增强",
    "长期记忆", "工作记忆", "情景记忆", "反思机制", "自主决策", "任务规划",
    "智能体规划", "智能体协作", "代理协作", "代理记忆",
)


@dataclass(frozen=True)
class TopicCheckResult:
    status: Literal["supported", "needs_sources", "out_of_scope"]
    message: str
    evidence_count: int
    suggested_topics: tuple[str, ...] = PRESET_TOPICS

    def model_dump(self) -> dict:
        result = asdict(self)
        result["suggested_topics"] = list(self.suggested_topics)
        return result


def normalize_topic(topic: str) -> str:
    return " ".join(topic.split()).strip()


def retrieval_query(topic: str) -> str:
    normalized = normalize_topic(topic)
    return RETRIEVAL_QUERIES.get(normalized, normalized)


def topic_is_in_scope(topic: str) -> bool:
    normalized = normalize_topic(topic)
    if normalized in PRESET_TOPICS:
        return True
    lowered = normalized.casefold()
    return any(term in lowered for term in _ENGLISH_SCOPE_TERMS) or any(
        term in normalized for term in _CHINESE_SCOPE_TERMS
    )


def find_topic_sources(knowledge_base, topic: str, top_k: int = 6):
    query = retrieval_query(topic)
    if hasattr(knowledge_base, "search_relevant"):
        return knowledge_base.search_relevant(
            query,
            top_k,
            relevance_query=query if topic in PRESET_TOPICS else topic,
        )
    return knowledge_base.search(query, top_k)


def check_topic(knowledge_base, topic: str) -> TopicCheckResult:
    normalized = normalize_topic(topic)
    if not topic_is_in_scope(normalized):
        return TopicCheckResult(
            status="out_of_scope",
            message=(
                f"“{normalized}”不在当前支持范围内。AgentMate 当前只提供 AI Agent 相关专题，"
                "请选择内置专题或输入与 Agent 直接相关的主题。"
            ),
            evidence_count=0,
        )

    sources = find_topic_sources(knowledge_base, normalized)
    if normalized not in PRESET_TOPICS and not sources:
        return TopicCheckResult(
            status="needs_sources",
            message=(
                f"“{normalized}”属于 AI Agent 范围，但资料库暂时没有足够的直接资料。"
                "请先上传相关讲义、笔记或论文，再重新创建任务。"
            ),
            evidence_count=0,
        )

    return TopicCheckResult(
        status="supported",
        message=f"主题检查通过，找到 {len(sources)} 条可用于研学的相关资料。",
        evidence_count=len(sources),
    )
