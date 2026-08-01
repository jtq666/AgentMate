"""固定研学流水线中的领域 Agent。

每个角色只接收上游结构化结果，并产生自己的 Pydantic 输出。模型异常时使用
可解释的本地回退，外部论文失败不会阻断核心学习链路。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from agentmate.config import settings
from agentmate.knowledge.paper_api import search_papers
from agentmate.study.models import (
    ConceptSection,
    EvaluationOutput,
    InterviewOutput,
    InterviewQuestion,
    QuestionEvaluation,
    ResearchOutput,
    SourceRef,
    StudyState,
    TeachingOutput,
)
from agentmate.study.topic_scope import find_topic_sources, retrieval_query

JsonInvoker = Callable[[str], Awaitable[dict[str, Any]]]


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("模型没有返回 JSON 对象")
        return json.loads(match.group(0))


class StudyAgents:
    def __init__(self, knowledge_base, json_invoker: JsonInvoker | None = None,
                 enable_llm: bool = True, enable_reflexion: bool = True):
        self.kb = knowledge_base
        self._json_invoker = json_invoker
        self.enable_llm = enable_llm
        self.enable_reflexion = enable_reflexion
        self.research_agent = ResearchAgent(self)
        self.teaching_agent = TeachingAgent(self)
        self.interview_agent = InterviewAgent(self)
        self.evaluation_agent = EvaluationAgent(self)
        self.supervisor = Supervisor(self)

    async def _invoke_json(self, prompt: str) -> dict:
        if self._json_invoker:
            return await self._json_invoker(prompt)
        if not self.enable_llm or not settings.llm.api_key:
            raise RuntimeError("LLM 未配置")
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.llm.model,
            temperature=0.2,
            max_tokens=settings.llm.max_tokens,
            api_key=settings.llm.api_key,
            base_url=settings.llm.base_url,
        )
        response = await llm.ainvoke(prompt)
        return _extract_json(str(response.content))

    async def research(self, state: StudyState) -> ResearchOutput:
        query = retrieval_query(state.topic)
        docs = await asyncio.to_thread(find_topic_sources, self.kb, state.topic, 6)
        sources: list[SourceRef] = []
        for index, doc in enumerate(docs, 1):
            metadata = doc.metadata or {}
            sources.append(SourceRef(
                citation_id=f"S{index}",
                document_id=doc.doc_id or metadata.get("document_id", f"local-{index}"),
                title=metadata.get("heading") or self._source_title(doc.source),
                source=doc.source or "内置课程",
                source_type=metadata.get("source_type", "course"),
                excerpt=doc.content[:800],
            ))
        warnings: list[str] = []
        if state.include_papers:
            try:
                papers = await asyncio.to_thread(
                    search_papers,
                    state.topic,
                    max_results=3,
                    min_year=2018,
                    min_citations=0,
                )
                for paper in papers[:3]:
                    index = len(sources) + 1
                    sources.append(SourceRef(
                        citation_id=f"S{index}",
                        document_id=paper.arxiv_id or f"paper-{index}-{abs(hash(paper.title))}",
                        title=paper.title,
                        source=paper.url or paper.pdf_url or f"paper://{paper.title}",
                        source_type="paper",
                        excerpt=paper.abstract[:800],
                        url=paper.url or paper.pdf_url,
                    ))
                if not papers:
                    warnings.append("论文检索未返回结果，已仅使用本地资料完成研学任务。")
            except Exception as exc:
                warnings.append(f"论文检索失败，已回退本地资料：{exc}")
        if not sources:
            warnings.append("知识库没有检索到相关资料，后续内容将使用保守的基础讲解。")
        key_points = [
            f"{source.title}：{self._first_sentence(source.excerpt)}"
            for source in sources[:5] if source.excerpt
        ]
        gaps = [] if len(sources) >= 3 else ["当前可追溯资料较少，建议补充课程讲义或代表性论文。"]
        return ResearchOutput(
            sources=sources,
            key_points=key_points,
            gaps=gaps,
            warnings=warnings,
            retrieval={"strategy": "ChromaDB + BM25 + RRF + topic relevance gate",
                       "query": query, "local_hits": len(docs),
                       "paper_hits": sum(item.source_type == "paper" for item in sources)},
        )

    async def teaching(self, state: StudyState) -> TeachingOutput:
        assert state.research is not None
        evidence = "\n".join(
            f"[{item.citation_id}] {item.title}\n{item.excerpt}" for item in state.research.sources
        )[:12000]
        prompt = f"""你是面向计算机保研学生的 Teaching Agent。请严格输出 JSON，不要输出 Markdown 代码围栏。
主题：{state.topic}；目标：{state.goal.value}；难度：{state.level.value}
需要重点补强：{'；'.join(state.focus_points) or '无指定薄弱点'}
资料：
{evidence or '无可用资料'}

JSON 结构：
{{"learning_map":["..."],"overview":"...","concepts":[{{"title":"...","explanation":"... [S1]","example":"...","citations":["S1"]}}],"misconceptions":["..."],"summary":"..."}}
要求：3-5 个概念；所有资料性陈述必须引用上述真实编号；不得编造不存在的编号；中文回答。"""
        try:
            output = self._sanitize_teaching(
                TeachingOutput.model_validate(await self._invoke_json(prompt)), state.research
            )
            if self.enable_reflexion:
                reflection_prompt = f"""你是 Teaching Agent 的 Reflexion 审校器。检查讲解是否覆盖主题、是否适合{state.level.value}难度、每个资料性陈述是否只用了真实引用。
真实引用：{sorted(source.citation_id for source in state.research.sources)}
当前输出：{json.dumps(output.model_dump(mode='json'), ensure_ascii=False)}
严格输出 JSON，结构与当前输出完全一致；修正遗漏和无效引用，不增加不存在的资料。"""
                revised = TeachingOutput.model_validate(await self._invoke_json(reflection_prompt))
                output = self._sanitize_teaching(revised, state.research)
            return output
        except Exception:
            return self._fallback_teaching(state)

    async def interview(self, state: StudyState) -> InterviewOutput:
        assert state.teaching is not None
        concepts = "、".join(section.title for section in state.teaching.concepts)
        prompt = f"""你是计算机保研 Interview Agent。请严格输出 JSON，不要输出答案给学生。
主题：{state.topic}；目标：{state.goal.value}；难度：{state.level.value}；核心概念：{concepts}
需要重点检验：{'；'.join(state.focus_points) or '无指定薄弱点'}
指定题型：{'、'.join(state.question_types)}
JSON：{{"questions":[{{"id":"q1","question":"...","difficulty":1,"question_type":"概念辨析","rubric":"内部评分规则","required_points":["必答点"],"follow_up":"追问"}}]}}
必须恰好生成 5 道递进问题，只使用指定题型并尽量均匀覆盖。rubric、required_points、follow_up 仅供内部评分。"""
        try:
            result = InterviewOutput.model_validate(await self._invoke_json(prompt))
            if len(result.questions) != 5:
                raise ValueError("问题数量不是 5")
            for index, question in enumerate(result.questions, 1):
                question.id = f"q{index}"
                question.difficulty = index
            return result
        except Exception:
            return self._fallback_interview(state)

    async def evaluate(self, state: StudyState, answers: list[str]) -> EvaluationOutput:
        assert state.interview is not None
        questions = state.interview.questions
        payload = [{
            "id": question.id,
            "question": question.question,
            "rubric": question.rubric,
            "required_points": question.required_points,
            "answer": answers[index] if index < len(answers) else "",
        } for index, question in enumerate(questions)]
        prompt = f"""你是严格但公平的计算机保研 Evaluation Agent。按每题 20 分评分。
题目、内部规则和学生答案：{json.dumps(payload, ensure_ascii=False)}
严格输出 JSON：{{"items":[{{"question_id":"q1","score":0,"hits":[],"misses":[],"misconceptions":[],"feedback":""}}],"total_score":0,"weak_points":[],"suggestions":[],"summary":""}}
必须逐题指出命中和遗漏；总分等于逐题分数之和；不能因语言风格扣分；中文输出。"""
        try:
            result = EvaluationOutput.model_validate(await self._invoke_json(prompt))
            if len(result.items) != 5:
                raise ValueError("评分项数量不是 5")
            result.total_score = round(sum(item.score for item in result.items), 2)
            return result
        except Exception:
            return self._fallback_evaluation(questions, answers)

    async def answer_task_chat(self, state: StudyState, message: str,
                               history: list[dict]) -> tuple[str, list[str]]:
        assert state.research is not None
        evidence = "\n".join(
            f"[{source.citation_id}] {source.title}: {source.excerpt}"
            for source in state.research.sources
        )[:10000]
        prompt = f"""你是任务内助教，只能基于给定研学资料回答，并保留 [S1] 引用。
主题：{state.topic}
资料：{evidence}
最近对话：{json.dumps(history[-6:], ensure_ascii=False)}
问题：{message}
严格输出 JSON：{{"answer":"...","citations":["S1"]}}。若资料不足要明确说明。
answer 必须是简洁 Markdown，控制在 700 个中文字符以内，并使用以下结构：
### 一句话理解
用 1-2 句话直接回答。
### 核心要点
- 3-5 个短要点，每个要点单独一行。
### 具体例子
给出一个贴近本科生或项目实践的例子。
### 面试怎么说
给出一段可直接口述的简短回答。
禁止输出连续的大段文字；所有资料性结论继续保留真实 [Sx] 引用。"""
        try:
            data = await self._invoke_json(prompt)
            valid = {item.citation_id for item in state.research.sources}
            citations = [item for item in data.get("citations", []) if item in valid]
            answer = self._remove_invalid_citations(str(data.get("answer", "")), valid)
            if re.search(r"###\s*面试怎么说\s*$", answer.strip()):
                answer += (
                    f"\n面试时可以先说明 {state.topic} 的定义和目标，再按“核心机制—"
                    "具体例子—工程权衡”展开，最后说明它的适用边界。"
                )
            return answer or "现有任务资料不足以回答这个问题。", citations
        except Exception:
            matches = [source for source in state.research.sources
                       if any(token in source.excerpt.lower() for token in self._keywords(message))]
            if not matches:
                return "现有任务资料不足以可靠回答这个问题，建议先向资料库补充相关材料。", []
            source = matches[0]
            return f"根据任务资料，{self._first_sentence(source.excerpt)} [{source.citation_id}]", [source.citation_id]

    def build_report(self, state: StudyState, evaluation: EvaluationOutput | None = None,
                     mastery: dict | None = None) -> str:
        teaching = state.teaching or TeachingOutput()
        lines = [
            f"# AgentMate 研学报告：{state.topic}", "",
            f"- 研学目标：{state.goal.value}",
            f"- 难度：{state.level.value}",
            f"- 任务编号：`{state.task_id}`", "",
            "## 学习地图", "",
        ]
        lines.extend(f"{index}. {item}" for index, item in enumerate(teaching.learning_map, 1))
        lines.extend(["", "## 核心讲解", "", teaching.overview])
        for concept in teaching.concepts:
            lines.extend(["", f"### {concept.title}", "", concept.explanation])
            if concept.example:
                lines.extend(["", f"> 示例：{concept.example}"])
        if teaching.misconceptions:
            lines.extend(["", "## 常见误区", ""])
            lines.extend(f"- {item}" for item in teaching.misconceptions)
        lines.extend(["", "## 实践评测", ""])
        if evaluation:
            lines.append(f"总分：**{evaluation.total_score:.1f}/100**")
            for item in evaluation.items:
                lines.extend(["", f"- {item.question_id}：{item.score:.1f}/20 — {item.feedback}"])
            if evaluation.weak_points:
                lines.extend(["", "### 薄弱点", ""])
                lines.extend(f"- {item}" for item in evaluation.weak_points)
            if evaluation.suggestions:
                lines.extend(["", "### 改进建议", ""])
                lines.extend(f"- {item}" for item in evaluation.suggestions)
            if mastery:
                lines.extend(["", f"当前专题掌握度：**{mastery['mastery']:.1f}%**（基于 {mastery['evidence_count']} 次测评证据）"])
        else:
            lines.append("尚未提交完整测评；掌握度将在评测后自动生成。")
        lines.extend(["", "## 资料来源", ""])
        for source in (state.research.sources if state.research else []):
            link = f" — {source.url}" if source.url else ""
            lines.append(f"- [{source.citation_id}] {source.title}（{source.source_type}）{link}")
        if state.warnings:
            lines.extend(["", "## 运行警告", ""])
            lines.extend(f"- {warning}" for warning in state.warnings)
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _source_title(source: str) -> str:
        cleaned = source.replace("\\", "/").split("/")[-1]
        return cleaned or "内置课程资料"

    @staticmethod
    def _first_sentence(text: str) -> str:
        sentence = re.split(r"[。！？\n]", text.strip(), maxsplit=1)[0]
        return sentence[:180]

    @staticmethod
    def _keywords(text: str) -> set[str]:
        english = re.findall(r"[a-zA-Z]{3,}", text.lower())
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        grams = [segment[index:index + 2] for segment in chinese
                 for index in range(max(0, len(segment) - 1))]
        return set(english + grams)

    @staticmethod
    def _remove_invalid_citations(text: str, valid: set[str]) -> str:
        return re.sub(r"\[(S\d+)\]", lambda match: match.group(0) if match.group(1) in valid else "", text)

    def _sanitize_teaching(self, output: TeachingOutput, research: ResearchOutput) -> TeachingOutput:
        valid = {source.citation_id for source in research.sources}
        output.overview = self._remove_invalid_citations(output.overview, valid)
        output.summary = self._remove_invalid_citations(output.summary, valid)
        for concept in output.concepts:
            concept.citations = [citation for citation in concept.citations if citation in valid]
            concept.explanation = self._remove_invalid_citations(concept.explanation, valid)
            concept.example = self._remove_invalid_citations(concept.example, valid)
        return output

    def _fallback_teaching(self, state: StudyState) -> TeachingOutput:
        sources = state.research.sources if state.research else []
        citation = sources[0].citation_id if sources else ""
        suffix = f" [{citation}]" if citation else ""
        evidence = self._first_sentence(sources[0].excerpt) if sources else "该主题需要结合模型、工具、状态和反馈闭环来理解。"
        focus_map = [f"补强：{point}" for point in state.focus_points[:2]]
        return TeachingOutput(
            learning_map=(focus_map + ["理解核心机制", "用面试问题检验理解"])[:4]
            if focus_map else ["先建立问题定义", "理解核心机制", "分析工程权衡", "用面试问题检验理解"],
            overview=f"{state.topic} 的学习重点不是背术语，而是说明它解决什么问题、如何运行以及何时失效。{suffix}",
            concepts=[
                ConceptSection(title="问题与边界", explanation=f"先明确该机制的输入、输出和适用边界。{suffix}", citations=[citation] if citation else []),
                ConceptSection(title="核心流程", explanation=f"关键资料指出：{evidence}。{suffix}", example="用一次具体任务画出状态变化和决策步骤。", citations=[citation] if citation else []),
                ConceptSection(title="工程权衡", explanation="面试中应同时讨论效果、延迟、成本、可观测性和失败恢复。", example="比较简单基线与复杂方案，而不是默认复杂方案更好。"),
            ],
            misconceptions=["只给出定义，不解释机制和边界。", "把多次模型调用本身当作多 Agent 创新。", "只报告成功案例，不设计失败回退。"],
            summary=f"围绕“为什么需要、怎样工作、如何验证”三条线掌握 {state.topic}。",
        )

    @staticmethod
    def _fallback_interview(state: StudyState) -> InterviewOutput:
        topic = state.topic
        templates = [
            (f"请用自己的话定义 {topic}，并说明它试图解决什么问题？", ["定义", "目标", "适用场景"]),
            (f"请描述 {topic} 的完整运行流程，关键输入和输出分别是什么？", ["流程", "输入输出", "状态变化"]),
            (f"{topic} 在工程实现中最常见的失败模式有哪些，怎样检测和恢复？", ["失败模式", "检测", "恢复策略"]),
            (f"如果要把 {topic} 用于保研研学助手，你会怎样设计模块、数据和评估指标？", ["模块设计", "数据流", "评估指标"]),
            (f"请比较采用与不采用 {topic} 的方案，说明收益、成本、边界与实验设计。", ["基线", "收益成本", "适用边界", "对比实验"]),
        ]
        selected_types = state.question_types or ["综合问答"]
        return InterviewOutput(questions=[InterviewQuestion(
            id=f"q{index}", question=question, difficulty=index,
            question_type=selected_types[(index - 1) % len(selected_types)],
            rubric="覆盖必答点、论证清楚、有具体例子或权衡可得高分。",
            required_points=points,
            follow_up=f"能否给出一个具体案例来验证第 {index} 题的判断？",
        ) for index, (question, points) in enumerate(templates, 1)])

    def _fallback_evaluation(self, questions: list[InterviewQuestion],
                             answers: list[str]) -> EvaluationOutput:
        items = []
        weak_points: list[str] = []
        for index, question in enumerate(questions):
            answer = answers[index].strip() if index < len(answers) else ""
            answer_tokens = self._keywords(answer)
            hits, misses = [], []
            for point in question.required_points:
                point_tokens = self._keywords(point)
                if point.lower() in answer.lower() or (point_tokens and point_tokens & answer_tokens):
                    hits.append(point)
                else:
                    misses.append(point)
            if not answer:
                score = 0.0
            else:
                coverage = len(hits) / max(len(question.required_points), 1)
                score = min(20.0, round(4 + 14 * coverage + min(len(answer) / 200, 1) * 2, 1))
            weak_points.extend(misses)
            items.append(QuestionEvaluation(
                question_id=question.id, score=score, hits=hits, misses=misses,
                feedback="回答已覆盖主要要点。" if not misses else f"建议补充：{'、'.join(misses)}。",
            ))
        total = round(sum(item.score for item in items), 1)
        weak_points = list(dict.fromkeys(weak_points))
        return EvaluationOutput(
            items=items,
            total_score=total,
            weak_points=weak_points,
            suggestions=[f"围绕“{item}”补充定义、机制和案例。" for item in weak_points[:5]],
            summary="本次为规则回退评分；已按必答点覆盖和回答完整度计算。",
        )


class ResearchAgent:
    name = "research"

    def __init__(self, runtime: StudyAgents):
        self.runtime = runtime

    async def run(self, state: StudyState) -> ResearchOutput:
        return await self.runtime.research(state)


class TeachingAgent:
    name = "teaching"

    def __init__(self, runtime: StudyAgents):
        self.runtime = runtime

    async def run(self, state: StudyState) -> TeachingOutput:
        return await self.runtime.teaching(state)


class InterviewAgent:
    name = "interview"

    def __init__(self, runtime: StudyAgents):
        self.runtime = runtime

    async def run(self, state: StudyState) -> InterviewOutput:
        return await self.runtime.interview(state)


class EvaluationAgent:
    name = "evaluation"

    def __init__(self, runtime: StudyAgents):
        self.runtime = runtime

    async def run(self, state: StudyState, answers: list[str]) -> EvaluationOutput:
        return await self.runtime.evaluate(state, answers)


class Supervisor:
    name = "supervisor"

    def __init__(self, runtime: StudyAgents):
        self.runtime = runtime

    def build_report(self, state: StudyState, evaluation: EvaluationOutput | None = None,
                     mastery: dict | None = None) -> str:
        return self.runtime.build_report(state, evaluation, mastery)
