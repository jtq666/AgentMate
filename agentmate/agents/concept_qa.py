"""
概念问答 Agent
职责：检索课程文档，回答课程相关问题。

工具：知识库检索（RAG）
"""

from __future__ import annotations

from agentmate.agents.base import AgentState, BaseAgent


class ConceptQAAgent(BaseAgent):
    """概念问答 Agent（RAG）"""

    def __init__(self, knowledge_base=None):
        super().__init__("concept_qa", "概念问答：检索课程文档回答问题")
        self._kb = knowledge_base

    def set_knowledge_base(self, kb):
        self._kb = kb

    async def run(self, state: AgentState) -> AgentState:
        query = state.user_query

        # 1. 检索相关文档
        docs = []
        if self._kb and self._kb.size > 0:
            results = self._kb.search(query, top_k=3)
            docs = results
            state.retrieved_docs = [{"content": r.content[:200], "source": r.source, "score": r.score}
                                    for r in results]

        # 2. 组装上下文
        context_parts = []
        if docs:
            context_parts.append("## 课程相关内容\n")
            for i, d in enumerate(docs, 1):
                context_parts.append(f"### 片段{i} (来源: {d.source or '课程文档'})\n{d.content}\n")

        memory_text = ""
        if state.memory_context:
            memory_text = "\n## 学生之前的交互\n"
            for m in state.memory_context[:3]:
                memory_text += f"- {m.get('content', '')[:100]}\n"

        context = "\n".join(context_parts) if context_parts else "未找到相关课程内容"

        # 3. LLM 生成回答
        try:
            from langchain_openai import ChatOpenAI
            from agentmate.config import settings
            llm = ChatOpenAI(model=settings.llm.model, temperature=0.3, max_tokens=800,
                             api_key=settings.llm.api_key, base_url=settings.llm.base_url)

            prompt = f"""你是一个 AI Agent 领域的研究助教。请回答学生的问题。

{context}
{memory_text}

## 学生问题
{query}

## 重要约束
1. 你是一个 AI Agent/大模型领域的研究助教
2. **禁止使用 C++、Python、Java 等编程类比来解释概念**
3. 使用 AI 领域的类比（如"就像多Agent系统中的协调器一样"）
4. 优先使用课程内容，不够时结合 AI 知识补充
5. 回答简洁清晰，注明哪些来自课程文档"""
            resp = await llm.ainvoke(prompt)
            state.response = resp.content
        except Exception:
            # LLM 不可用时的回退
            if docs:
                state.response = f"根据课程资料，关于「{query}」的信息如下：\n\n{docs[0].content[:500]}"
            else:
                state.response = f"暂未找到关于「{query}」的课程资料，请先导入课程文档。"

        state.log(self.name, f"检索到{len(docs)}个相关文档")
        return state
