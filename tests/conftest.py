from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeRetrievedDoc:
    content: str
    source: str
    score: float = 0.03
    method: str = "rrf"
    doc_id: str = "doc-react"
    metadata: dict = field(default_factory=lambda: {
        "heading": "ReAct 与工具调用",
        "source_type": "course",
        "document_id": "doc-react",
    })


class FakeKnowledgeBase:
    def __init__(self):
        self.size = 1
        self._docs = [{
            "id": "doc-react",
            "content": "ReAct 通过 Thought、Action、Observation 循环把推理与工具行动交错执行。",
            "source": "course://react",
            "metadata": {"heading": "ReAct 与工具调用", "source_type": "course"},
        }]

    def search(self, query: str, top_k: int = 5):
        return [FakeRetrievedDoc(
            content="ReAct 通过 Thought、Action、Observation 循环把推理与工具行动交错执行。",
            source="course://react",
        )]

    def add(self, content: str, source: str = "", metadata: dict | None = None):
        return "fake-doc"

    def delete_at(self, index: int):
        return None
