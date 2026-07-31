"""
论文检索 Agent — 质量筛选 + 用户选择

LLM 提取搜索词 → 调用 Semantic Scholar API → 展示质量评分 → 用户选择入库
"""

from __future__ import annotations

from eduagent.agents.base import AgentState, BaseAgent
from eduagent.knowledge.paper_api import search_papers


class PaperSearchAgent(BaseAgent):

    def __init__(self, knowledge_base=None):
        super().__init__("paper_search", "论文检索：搜索论文、质量筛选、选入知识库")
        self._kb = knowledge_base
        self._pending_papers: list = []  # 待用户选择的论文

    async def run(self, state: AgentState) -> AgentState:
        query = state.user_query

        # 检查是否是选择指令
        if any(kw in query for kw in ["选择", "导入", "保存", "入库", "第"]):
            return self._handle_selection(state)

        # 1. LLM 提取搜索关键词
        try:
            from langchain_openai import ChatOpenAI
            from eduagent.config import settings
            llm = ChatOpenAI(model=settings.llm.model, temperature=0, max_tokens=100,
                             api_key=settings.llm.api_key, base_url=settings.llm.base_url)

            extract_prompt = f"""提取论文搜索关键词（英文）。

用户: {query}
注意：ReAct → "ReAct reasoning large language model"
多Agent → "multi-agent systems coordination"

只输出关键词："""
            resp = await llm.ainvoke(extract_prompt)
            search_query = resp.content.strip()
        except Exception:
            search_query = query

        # 2. 搜索（默认过滤 2020 年前、引用<1 的论文）
        papers = search_papers(search_query, max_results=8, min_year=2020)

        if not papers:
            state.response = f"未找到关于「{search_query}」的论文。试试其他关键词。"
            return state

        # 3. 按质量排序
        papers.sort(key=lambda p: p.quality_score, reverse=True)

        # 4. 存储待选列表 + 展示结果
        self._pending_papers = papers
        parts = [f"## 📄 论文检索: {search_query}", f"找到 {len(papers)} 篇，按质量排序：\n"]

        for i, p in enumerate(papers, 1):
            parts.append(f"### {i}. {p.to_markdown()}")
            parts.append("")

        parts.append("---")
        parts.append("**如何操作**：输入「导入第X篇」或「导入1,3,5」选择感兴趣的论文存入知识库。")
        parts.append("未选择的论文不会保存。")

        state.response = "\n".join(parts)
        state.log(self.name, f"论文搜索: {len(papers)} 篇")
        return state

    def _handle_selection(self, state: AgentState) -> AgentState:
        """处理用户的选导入指令"""
        query = state.user_query

        if not self._pending_papers:
            state.response = "没有待导入的论文。请先搜索。"
            return state

        # 解析选择
        import re
        numbers = re.findall(r"\d+", query)
        selected_indices = [int(n) - 1 for n in numbers if 1 <= int(n) <= len(self._pending_papers)]

        if not selected_indices:
            state.response = "请告诉我导入哪几篇（如「导入1,3,5」）。"
            return state

        imported = []
        for idx in selected_indices:
            p = self._pending_papers[idx]
            if self._kb:
                content = f"标题: {p.title}\n作者: {', '.join(p.authors)}\n摘要: {p.abstract}"
                self._kb.add(content, f"paper://{p.title[:50]}", {"heading": p.title})
            imported.append(f"#{idx+1} {p.title}")

        state.response = f"✅ 已导入 {len(imported)} 篇论文：\n" + "\n".join(imported)
        state.log(self.name, f"导入 {len(imported)} 篇论文")
        return state
