"""
Agent 基类
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """Agent 间共享状态"""
    user_query: str = ""
    intent: str = ""
    student_id: str = "default"

    # 代码分析结果
    code: str = ""
    language: str = "python"
    code_analysis: dict = field(default_factory=dict)
    bugs: list = field(default_factory=list)
    test_cases: list = field(default_factory=list)  # 作业批改的测试用例

    # 知识检索结果
    retrieved_docs: list = field(default_factory=list)

    # 记忆
    memory_context: list = field(default_factory=list)

    # 教学
    hint_level: str = ""  # light / medium / detailed
    teaching_thoughts: list = field(default_factory=list)
    trajectory: Any = None  # AgentTrajectory，记录完整执行轨迹

    # 输出
    response: str = ""
    sources: list = field(default_factory=list)
    execution_log: list = field(default_factory=list)

    def log(self, agent: str, msg: str):
        self.execution_log.append({"agent": agent, "message": msg})


class BaseAgent(ABC):
    """Agent 基类"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.logger = logging.getLogger(name)

    @abstractmethod
    async def run(self, state: AgentState) -> AgentState:
        ...

    def __repr__(self):
        return f"<{self.name}>"
