"""
面试模拟 Agent — LLM 驱动

LLM 自主出题、推荐、解答，专注于 AI Agent 领域的面试题。
"""

from __future__ import annotations

from eduagent.agents.base import AgentState, BaseAgent


class PracticeAgent(BaseAgent):
    """面试模拟 Agent"""

    def __init__(self):
        super().__init__("practice", "面试模拟：出题、推荐、模拟问答")

    async def run(self, state: AgentState) -> AgentState:
        try:
            from langchain_openai import ChatOpenAI
            from eduagent.config import settings
            llm = ChatOpenAI(model=settings.llm.model, temperature=0.5,
                             api_key=settings.llm.api_key, base_url=settings.llm.base_url,
                             max_tokens=600)

            # 读取学生记忆，个性化出题
            memory_info = ""
            if state.memory_context:
                recent = []
                for m in state.memory_context[:5]:
                    recent.append(f"- [{m.get('source','')}] {m.get('content','')[:100]}")
                if recent:
                    memory_info = "## 学生的学习历史\n" + "\n".join(recent) + "\n根据历史判断学生已学/薄弱的话题，针对薄弱点出题。"

            prompt = f"""你是 CS 保研面试官。根据学生的学习历史，出个性化面试题。

## 知识范围
ReAct推理、多Agent协作、记忆系统(工作/短期/长期)、Tool Use/Function Calling、Plan-and-Execute、Agent评估

{memory_info}

## 用户输入
{state.user_query}

## 要求
1. 如果学生有历史记录，针对薄弱/已学话题出题
2. 如果学生刚入门，出基础概念的题
3. 适合**本科保研面试**难度，考察概念理解
4. 附上 2-3 个参考答案要点
5. 如果用户说"推荐"，推荐3个高频考点

直接输出，简洁。"""

            resp = await llm.ainvoke(prompt)
            state.response = resp.content.strip()
        except Exception:
            state.response = self._fallback()

        state.log(self.name, "面试题生成完成")
        return state

    def _fallback(self) -> str:
        return """### AI Agent 面试题

**题目：解释 ReAct 模式的工作原理**

**参考答案思路：**
1. ReAct = Reasoning + Acting（推理 + 行动）
2. 核心循环：Thought → Action → Observation
3. 与普通 LLM 的区别：多步推理 + 工具调用
4. 举例说明一个完整的 ReAct 循环

**追问：**
- ToolRegistry 是怎么让 Agent 自主选择工具的？
- 如何防止 Agent 陷入无限循环？"""
