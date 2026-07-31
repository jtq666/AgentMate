"""
Agent 架构核心模块

包含：
1. ToolRegistry — 工具注册与发现
2. AgentState（状态机）— Agent 生命周期管理
3. Reflexion — 自我反思机制
4. PlanAndExecute — 规划执行模式

面试深度点：
- 工具注册：Agent 通过工具描述自主选择（类比 Function Calling）
- 状态机：IDLE → THINKING → TOOL_CALLING → OBSERVING → RESPONDING → DONE
- Reflexion：生成→评审→修改的自我纠错循环
- Plan-and-Execute：先规划步骤，再逐步执行，支持依赖管理
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ==================== 1. 工具注册中心 ====================

@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str          # LLM 看到的工具描述
    parameters: str           # 参数说明（自然语言）
    function: Callable        # 实际执行函数

    def to_prompt(self) -> str:
        """转为 LLM 可读的工具描述"""
        return f"- {self.name}: {self.description}。参数: {self.parameters}"


class ToolRegistry:
    """
    工具注册中心

    Agent 通过工具描述自主决定调用哪个工具。
    类比 OpenAI Function Calling，但更灵活。

    面试讲点：
    - 工具注册机制：统一接口，动态注册
    - 工具发现：LLM 读取工具描述后自主选择
    - 工具调用：解析 LLM 输出 → 调用对应函数 → 返回结果
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: str, function: Callable):
        """注册工具"""
        self._tools[name] = Tool(
            name=name, description=description,
            parameters=parameters, function=function,
        )
        logger.info(f"注册工具: {name}")

    def get_descriptions(self) -> str:
        """获取所有工具描述（给 LLM 看）"""
        if not self._tools:
            return "无可用工具"
        return "\n".join(t.to_prompt() for t in self._tools.values())

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    async def call(self, name: str, **kwargs) -> str:
        """调用工具"""
        tool = self._tools.get(name)
        if not tool:
            return f"工具 {name} 不存在。可用工具: {', '.join(self.list_tools())}"
        try:
            result = tool.function(**kwargs)
            if hasattr(result, '__await__'):
                result = await result
            return str(result)
        except Exception as e:
            return f"工具 {name} 执行失败: {str(e)}"


# ==================== 2. Agent 状态机 ====================

class AgentPhase(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    RESPONDING = "responding"
    DONE = "done"


@dataclass
class AgentStep:
    """Agent 的一步行动"""
    phase: AgentPhase
    content: str           # 这一步的内容（Thought/Action/Observation）
    tool_name: str = ""    # 如果调用了工具，记录工具名
    tool_result: str = ""  # 工具返回结果


@dataclass
class AgentTrajectory:
    """Agent 的完整执行轨迹（面试展示用）"""
    steps: list[AgentStep] = field(default_factory=list)
    final_response: str = ""
    is_refined: bool = False   # 是否经过反思修正
    plan: list[str] = field(default_factory=list)  # 规划步骤

    def add_step(self, phase: AgentPhase, content: str, tool_name: str = "", tool_result: str = ""):
        self.steps.append(AgentStep(
            phase=phase, content=content,
            tool_name=tool_name, tool_result=tool_result,
        ))

    def get_thoughts(self) -> list[str]:
        return [s.content for s in self.steps if s.phase == AgentPhase.THINKING]

    def get_tool_calls(self) -> list[dict]:
        return [{"tool": s.tool_name, "result": s.tool_result[:200]}
                for s in self.steps if s.phase == AgentPhase.TOOL_CALLING]

    def to_display(self) -> str:
        """转为前端可展示的格式"""
        parts = []
        if self.plan:
            parts.append("**📋 执行计划:**")
            for i, step in enumerate(self.plan, 1):
                parts.append(f"  {i}. {step}")
            parts.append("")

        for step in self.steps:
            if step.phase == AgentPhase.THINKING:
                parts.append(f"💭 **思考:** {step.content}")
            elif step.phase == AgentPhase.TOOL_CALLING:
                parts.append(f"🔧 **调用工具 {step.tool_name}**")
                if step.tool_result:
                    parts.append(f"   → {step.tool_result[:150]}...")
            elif step.phase == AgentPhase.REFLECTING:
                parts.append(f"🔍 **反思:** {step.content}")
            elif step.phase == AgentPhase.OBSERVING:
                parts.append(f"👁️ **观察:** {step.content[:100]}")

        if self.is_refined:
            parts.append("\n🔄 **经过自我反思修正**")

        return "\n".join(parts)


# ==================== 3. Reflexion 自我反思 ====================

class ReflexionEngine:
    """
    Reflexion 自我反思引擎

    流程：生成 → 自我评审 → 不满意则重新生成
    最多反思 max_reflections 次。

    面试讲点：
    - Reflexion 原理：Agent 对自己的输出进行质量评估
    - 评审维度：准确性、完整性、引导性
    - 修正策略：根据评审意见针对性修改
    """

    def __init__(self, max_reflections: int = 1):
        self.max_reflections = max_reflections

    async def generate_with_reflection(
        self,
        llm,
        prompt: str,
        trajectory: AgentTrajectory,
    ) -> str:
        """带反思的生成"""
        best_response = ""

        for reflection_round in range(self.max_reflections + 1):
            # 1. 生成回答
            resp = await llm.ainvoke(prompt)
            response = resp.content.strip()

            if reflection_round == 0:
                best_response = response
                trajectory.add_step(AgentPhase.RESPONDING, response[:200])

            # 2. 自我评审（最后一次不评审）
            if reflection_round < self.max_reflections:
                critique = await self._self_critique(llm, response, prompt)
                trajectory.add_step(AgentPhase.REFLECTING, critique)

                if critique.startswith("PASS"):
                    break

                # 3. 根据评审意见修正
                prompt = prompt + f"\n\n## 上一版回答的问题\n{critique}\n\n请修正后重新回答。"
                best_response = response
                trajectory.is_refined = True

        return best_response

    async def _self_critique(self, llm, response: str, original_prompt: str) -> str:
        """自我评审"""
        critique_prompt = f"""你是一个严格的教学质量评审员。请评估以下回答的质量。

## 用户问题
{original_prompt[:500]}

## Agent 回答
{response[:500]}

## 评审维度
1. 准确性：信息是否正确？
2. 完整性：是否回答了用户的问题？
3. 引导性：如果是教学场景，是否在引导而非直接给答案？

如果回答质量好，直接回复 "PASS"
如果需要改进，指出具体问题（2-3 句话）："""
        try:
            resp = await llm.ainvoke(critique_prompt)
            return resp.content.strip()
        except Exception:
            return "PASS"


# ==================== 4. Plan-and-Execute ====================

class PlannerEngine:
    """
    规划执行引擎

    流程：
    1. LLM 生成执行计划（步骤列表）
    2. 逐步执行每个步骤
    3. 每步的结果作为下一步的输入

    面试讲点：
    - 任务分解：将复杂任务拆解为原子步骤
    - 依赖管理：步骤间的前后依赖
    - 动态调整：根据执行结果修改后续计划
    """

    def __init__(self, max_steps: int = 5):
        self.max_steps = max_steps

    async def create_plan(
        self,
        llm,
        query: str,
        available_tools: str,
        context: str = "",
    ) -> list[str]:
        """生成执行计划"""
        prompt = f"""你是一个任务规划专家。请为以下任务制定一个执行计划。

## 用户请求
{query}

## 可用工具
{available_tools}

## 已有信息
{context if context else "无"}

## 要求
输出一个 JSON 格式的步骤列表，每步说明要做什么、用什么工具：
```json
["步骤1描述", "步骤2描述", ...]
```

步骤数量控制在 2-5 步，按逻辑顺序排列。"""

        try:
            resp = await llm.ainvoke(prompt)
            text = resp.content.strip()
            # 解析 JSON
            json_match = re.search(r"\[.*\]", text, re.DOTALL)
            if json_match:
                steps = json.loads(json_match.group(0))
                return steps[:self.max_steps]
        except Exception:
            pass

        # 默认计划
        return ["分析用户需求", "收集必要信息", "生成最终回答"]

    async def execute_plan(
        self,
        plan: list[str],
        tool_executor: Callable,
        llm,
        trajectory: AgentTrajectory,
        context: dict,
    ) -> str:
        """逐步执行计划"""
        trajectory.plan = plan

        for i, step_desc in enumerate(plan):
            trajectory.add_step(AgentPhase.THINKING, f"Step {i+1}: {step_desc}")

            # LLM 决定这一步调用什么工具
            tool_call = await self._decide_tool(llm, step_desc, context)

            if tool_call["tool"] == "final_answer":
                return tool_call.get("answer", "")

            # 执行工具
            trajectory.add_step(
                AgentPhase.TOOL_CALLING,
                f"调用 {tool_call['tool']}",
                tool_name=tool_call["tool"],
            )

            result = await tool_executor(tool_call["tool"], **tool_call.get("params", {}))
            trajectory.add_step(AgentPhase.OBSERVING, result[:300])

            # 更新上下文
            context[f"step_{i+1}_result"] = result

        return ""

    async def _decide_tool(self, llm, step_desc: str, context: dict) -> dict:
        """LLM 决定调用哪个工具"""
        context_text = "\n".join(f"- {k}: {str(v)[:100]}" for k, v in context.items())

        prompt = f"""请为以下步骤选择要调用的工具。

## 步骤
{step_desc}

## 已有信息
{context_text if context_text else "无"}

## 可用工具
- query_memory: 查询学生历史记录。参数: query(字符串)
- analyze_code: 分析代码结构。参数: code(字符串), language(字符串)
- retrieve_knowledge: 检索课程知识库。参数: query(字符串)
- execute_code: 运行代码。参数: code(字符串), language(字符串)
- final_answer: 直接给出最终回答。参数: answer(字符串)

请输出 JSON:
{{"tool": "工具名", "params": {{"参数名": "值"}}}}

如果信息足够直接回答，选 final_answer。"""

        try:
            resp = await llm.ainvoke(prompt)
            text = resp.content.strip()
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception:
            pass

        return {"tool": "final_answer", "params": {"answer": ""}}
