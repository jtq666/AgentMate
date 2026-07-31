"""
意图路由 + 多Agent协调器

全部由 LLM 驱动，不做硬编码关键词匹配。
LLM 根据用户输入自主判断意图并选择 Agent。
"""

from __future__ import annotations

import logging
from eduagent.agents.base import AgentState, BaseAgent

logger = logging.getLogger(__name__)


class AgentCoordinator:
    """Agent 协调器 — LLM 驱动"""

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}
        self._llm = None

    def register(self, agent: BaseAgent):
        self._agents[agent.name] = agent
        logger.info(f"注册 Agent: {agent.name}")

    def _get_llm(self):
        if self._llm is None:
            try:
                from langchain_openai import ChatOpenAI
                from eduagent.config import settings
                self._llm = ChatOpenAI(
                    model=settings.llm.model, temperature=0,
                    max_tokens=200,
                    api_key=settings.llm.api_key, base_url=settings.llm.base_url,
                )
            except Exception:
                pass
        return self._llm

    async def classify_intent(self, query: str, code: str = "") -> str:
        """
        LLM 驱动的意图分类。

        不再用关键词匹配，而是让 LLM 理解用户意图。
        """
        llm = self._get_llm()
        if not llm:
            return self._rule_fallback(query, code)

        agent_list = "\n".join(f"- {name}: {agent.description}" for name, agent in self._agents.items())

        prompt = f"""## 可用 Agent
{agent_list}

## 用户输入
{query}

判断应该交给哪个 Agent，只输出名称。"""

        try:
            resp = await llm.ainvoke(prompt)
            intent = resp.content.strip().lower()
            # 验证是否是有效的 Agent 名称
            if intent in self._agents:
                return intent
            # 模糊匹配
            for name in self._agents:
                if name in intent:
                    return name
        except Exception:
            pass

        return self._rule_fallback(query, code)

    def _rule_fallback(self, query: str, code: str) -> str:
        """LLM 不可用时的规则回退"""
        q = query.lower()
        if any(kw in q for kw in ["论文", "paper", "arxiv", "文献", "搜索论文", "检索论文"]):
            return "paper_search"
        if any(kw in q for kw in ["出题", "面试", "练习", "推荐"]):
            return "practice"
        if any(kw in q for kw in ["什么是", "解释", "原理"]):
            return "concept_qa"
        return "teaching"

    async def run(self, state: AgentState) -> AgentState:
        """执行流程"""
        if not state.intent:
            state.intent = await self.classify_intent(state.user_query, state.code)
        state.log("coordinator", f"意图: {state.intent}")

        agent = self._agents.get(state.intent)
        if not agent:
            agent = self._agents.get("teaching")
        if not agent:
            state.response = "暂无可用的 Agent"
            return state

        state.log("coordinator", f"路由到: {agent.name}")

        # Agent 协作：前一个 Agent 的结果写入共享状态
        previous_response = state.response if state.response else ""

        state = await agent.run(state)

        # Agent 协作：如果本次是论文检索，标记结果供其他 Agent 使用
        if state.intent == "paper_search":
            state.retrieved_papers = state.response
            state.log("coordinator", "论文检索结果已共享给其他 Agent")

        return state
