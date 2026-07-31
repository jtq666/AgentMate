"""
教学 Agent（架构深度版）

集成：
- ToolRegistry：工具注册与自主选择
- Plan-and-Execute：先规划再执行
- Reflexion：自我反思修正
- AgentTrajectory：完整执行轨迹可视化

面试讲点：
- 工具注册机制（类比 Function Calling）
- Plan-and-Execute 任务分解
- Reflexion 自我纠错
- 完整的 Agent 执行轨迹
"""

from __future__ import annotations

import json
import re
from agentmate.agents.arch import (
    AgentPhase, AgentTrajectory, PlannerEngine, ReflexionEngine, ToolRegistry,
)
from agentmate.agents.base import AgentState, BaseAgent


# ==================== 内置工具函数 ====================

def _tool_query_memory(memory_context: list) -> str:
    """查询学生记忆"""
    if not memory_context:
        return "该学生没有历史交互记录"
    lines = []
    for m in memory_context[:5]:
        src = m.get("source", "")
        content = m.get("content", "")[:150]
        lines.append(f"- [{src}] {content}")
    return "学生历史记录：\n" + "\n".join(lines)


def _tool_analyze_code(code: str, language: str = "cpp") -> str:
    """分析代码结构"""
    if not code:
        return "没有代码可分析"
    from agentmate.code_engine.analyzer import analyze_code
    m = analyze_code(code, language)
    parts = [
        f"语言: {m.language}, 总行数: {m.total_lines}",
        f"函数: {', '.join(m.functions) if m.functions else '无'}",
        f"类: {', '.join(m.classes) if m.classes else '无'}",
        f"圈复杂度: {m.cyclomatic}, 认知复杂度: {m.cognitive}, 嵌套深度: {m.nesting}",
    ]
    return "\n".join(parts)


def _tool_retrieve_knowledge(query: str, kb=None) -> str:
    """检索课程知识库"""
    if not kb or kb.size == 0:
        return "知识库为空"
    results = kb.search(query, top_k=3)
    if not results:
        return f"未找到关于「{query}」的课程资料"
    lines = [f"[相关度 {r.score:.3f}] {r.content[:200]}" for r in results]
    return "检索到的相关知识：\n" + "\n".join(lines)


# ==================== Teaching Agent ====================

class TeachingAgent(BaseAgent):
    """
    教学 Agent

    架构：
    1. Plan-and-Execute：先规划步骤，再逐步执行
    2. ToolRegistry：工具自主选择
    3. Reflexion：自我反思修正
    4. AgentTrajectory：完整执行轨迹
    """

    def __init__(self, knowledge_base=None, max_steps: int = 4):
        super().__init__("teaching", "教学引导：ReAct多步推理，引导式教学")
        self._kb = knowledge_base
        self._max_steps = max_steps

        # 工具注册
        self._registry = ToolRegistry()
        self._registry.register(
            "query_memory", "查询学生的历史学习记录",
            "query: 搜索关键词", _tool_query_memory,
        )
        self._registry.register(
            "analyze_code", "分析代码的结构、复杂度和潜在问题",
            "code: 代码内容, language: 编程语言(cpp/python)", _tool_analyze_code,
        )
        self._registry.register(
            "retrieve_knowledge", "从课程知识库检索相关文档",
            "query: 搜索关键词", lambda query: _tool_retrieve_knowledge(query, self._kb),
        )

        # 引擎
        self._planner = PlannerEngine(max_steps=max_steps)
        self._reflexion = ReflexionEngine(max_reflections=1)

    def set_knowledge_base(self, kb):
        self._kb = kb
        # 更新工具
        self._registry.register(
            "retrieve_knowledge", "从课程知识库检索相关文档",
            "query: 搜索关键词", lambda query: _tool_retrieve_knowledge(query, kb),
        )

    async def run(self, state: AgentState) -> AgentState:
        from agentmate.config import settings
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=settings.llm.model, temperature=0.3, max_tokens=600,
                         api_key=settings.llm.api_key, base_url=settings.llm.base_url)

        trajectory = AgentTrajectory()

        # ========== Step 1: 预收集信息 ==========
        trajectory.add_step(AgentPhase.THINKING, "开始分析用户请求，预收集必要信息...")

        # 自动调用工具
        if state.memory_context:
            mem_result = _tool_query_memory(state.memory_context)
            trajectory.add_step(AgentPhase.TOOL_CALLING, "查询学生记忆",
                               tool_name="query_memory", tool_result=mem_result[:200])

        code_analysis = ""
        if state.code:
            code_analysis = _tool_analyze_code(state.code, state.language)
            trajectory.add_step(AgentPhase.TOOL_CALLING, "分析代码",
                               tool_name="analyze_code", tool_result=code_analysis[:200])

        kb_result = _tool_retrieve_knowledge(state.user_query, self._kb)
        trajectory.add_step(AgentPhase.TOOL_CALLING, "检索知识库",
                           tool_name="retrieve_knowledge", tool_result=kb_result[:200])

        # ========== Step 2: 生成 + Reflexion 自我反思 ==========
        trajectory.add_step(AgentPhase.THINKING, "综合所有信息，生成教学回答...")

        context = {"code_analysis": code_analysis[:300] if code_analysis else "无代码"}
        prompt = self._build_prompt(state, context, kb_result)

        try:
            resp = await llm.ainvoke(prompt)
            response = resp.content.strip()

            # Reflexion: 自我反思检查
            reflect_prompt = f"""你是一个严格的评审员。检查以下回答是否合适：

用户问题: {state.user_query}
回答: {response[:500]}

检查项：
1. 是否引用了课程内容（如果有的话）？
2. 是否引导而非直接给答案？
3. 是否简洁清晰？

如果回答没问题，回复 "OK"。如果有问题，指出需要修改的地方（一句话）："""
            reflect_resp = await llm.ainvoke(reflect_prompt)
            critique = reflect_resp.content.strip()

            if not critique.startswith("OK"):
                trajectory.add_step(AgentPhase.REFLECTING, critique)
                trajectory.is_refined = True
                # 根据反思修正
                fix_prompt = f"""请修正以下回答。问题：{critique}

原回答: {response[:300]}

请直接输出修正后的完整回答："""
                fix_resp = await llm.ainvoke(fix_prompt)
                response = fix_resp.content.strip()
        except Exception:
            response = self._fallback(state)

        state.response = response
        state.teaching_thoughts = trajectory.get_thoughts()
        state.trajectory = trajectory
        state.log(self.name, f"执行完成，步骤: {len(trajectory.steps)}")

        return state

    def _build_prompt(self, state: AgentState, context: dict, kb_result: str) -> str:
        """构建最终生成 Prompt"""
        student_ctx = ""
        if state.memory_context:
            student_ctx = "学生历史:\n" + "\n".join(
                f"  - [{m.get('source','')}] {m.get('content','')[:100]}"
                for m in state.memory_context[:3]
            )

        return f"""你是一个 AI Agent 领域的学习助手。

## 课程知识
{kb_result[:500] if kb_result else "无相关课程内容"}

## 学生信息
{student_ctx or "新学生，没有任何学习记录"}

## 学生问题
{state.user_query}

## 自主判断策略
- 如果学生是新手/刚开始/说"入门"，主动给出建议的学习路径（6步系统学习）
- 学习路径参考: Agent基础 → LLM Agent架构 → ReAct推理 → 多Agent → 记忆系统 → 工具调用
- 如果学生表示不理解，降低难度
- 如果学生理解了，建议下一步
- **禁止用C++/Python/Java编程类比**，用AI领域类比
- 回答简洁，3-5句话为主"""

    def _fallback(self, state: AgentState) -> str:
        if state.code:
            return "我注意到这段代码，你能先运行看看结果吗？"
        return f"关于「{state.user_query}」—— 你觉得从哪里开始理解比较好？"
