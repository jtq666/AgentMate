"""
代码审查 Agent — LLM 驱动

不做硬编码的语言检测和正则提取。
直接把用户的输入（可能包含代码也可能不包含）交给 LLM 分析。
LLM 自己判断语言、提取代码、检测问题。
"""

from __future__ import annotations

from eduagent.agents.base import AgentState, BaseAgent


class CodeReviewAgent(BaseAgent):
    """代码审查 Agent — LLM 全权处理"""

    def __init__(self):
        super().__init__("code_review", "代码审查：分析代码、检测Bug、给出改进建议")

    async def run(self, state: AgentState) -> AgentState:
        input_text = state.user_query
        if state.code:
            input_text += "\n\n```\n" + state.code + "\n```"

        if not input_text.strip():
            state.response = "请提供需要审查的代码。"
            return state

        try:
            from langchain_openai import ChatOpenAI
            from eduagent.config import settings
            llm = ChatOpenAI(model=settings.llm.model, temperature=0, max_tokens=800,
                             api_key=settings.llm.api_key, base_url=settings.llm.base_url)

            prompt = f"""你是一个资深代码审查专家。分析以下输入中的代码并给出审查报告。

## 用户输入
{input_text}

## 任务
1. **识别语言**：自己判断这段代码是什么语言（C++/Python/Java等）
2. **提取代码**：从用户输入中提取出代码部分
3. **分析代码**：检查语法错误、逻辑错误、内存问题、安全问题、代码风格
4. **给出报告**：

请输出以下格式的审查报告：

## 代码审查报告

- **语言**: <识别的语言>
- **代码行数**: <行数>

### 发现的问题

<每个问题按以下格式>
🔴/🟡/🔵 **第X行**：问题描述
  💡 建议：修复建议

### 总结
2-3句话总结"""

            resp = await llm.ainvoke(prompt)
            state.response = resp.content.strip()

            # 提取 Bug 数量用于统计
            response = state.response
            state.bugs = [{"severity": "error"}] * response.count("🔴") + \
                        [{"severity": "warning"}] * response.count("🟡") + \
                        [{"severity": "info"}] * response.count("🔵")

        except Exception:
            state.response = "代码审查暂时不可用，请稍后重试。"

        state.log(self.name, f"审查完成，发现 {len(state.bugs)} 个问题")
        return state
