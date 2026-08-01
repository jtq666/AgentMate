from __future__ import annotations

from dataclasses import dataclass, field

from agentmate.knowledge.retriever import KnowledgeBase, RetrievedDoc
from agentmate.study.topic_scope import PRESET_TOPICS, check_topic, retrieval_query


@dataclass
class TopicDoc:
    content: str = "MCP 让 Agent 通过标准协议发现并调用外部工具。"
    source: str = "user://MCP 工具生态"
    score: float = 0.03
    method: str = "rrf"
    doc_id: str = "mcp-doc"
    metadata: dict = field(default_factory=lambda: {"heading": "MCP 工具生态"})


class CoverageKnowledgeBase:
    def __init__(self, has_mcp_source: bool = False):
        self.has_mcp_source = has_mcp_source

    def search_relevant(self, query: str, top_k: int = 6, *, relevance_query: str | None = None):
        if self.has_mcp_source and "mcp" in query.casefold():
            return [TopicDoc()]
        return []


def test_presets_remain_supported_without_custom_coverage_check():
    kb = CoverageKnowledgeBase()
    assert all(check_topic(kb, topic).status == "supported" for topic in PRESET_TOPICS)


def test_out_of_scope_and_missing_sources_are_distinguished():
    kb = CoverageKnowledgeBase()
    assert check_topic(kb, "Transformer").status == "out_of_scope"
    assert check_topic(kb, "MCP Agent 工具协议").status == "needs_sources"


def test_agent_custom_topic_becomes_supported_after_source_import():
    result = check_topic(CoverageKnowledgeBase(has_mcp_source=True), "MCP Agent 工具协议")
    assert result.status == "supported"
    assert result.evidence_count == 1


def test_relevant_search_does_not_use_nearest_unrelated_agent_document():
    kb = object.__new__(KnowledgeBase)
    unrelated = RetrievedDoc(
        content="Agent 通过规划、工具调用和记忆完成复杂任务。",
        source="course://agent-basics",
        score=0.04,
        doc_id="agent-basics",
        metadata={"heading": "Agent 定义"},
    )
    kb.search = lambda query, top_k: [unrelated]

    assert retrieval_query("Transformer") == "Transformer"
    assert kb.search_relevant("Transformer", 6, relevance_query="Transformer") == []
