"""
FastAPI 后端
"""
from __future__ import annotations

import os
# 确保 .env 加载
from pathlib import Path
from dotenv import load_dotenv
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)


# ==================== 全局组件 ====================

_app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """初始化所有组件"""
    logger.info("EduAgent 启动中...")

    try:
        from eduagent.memory import MemoryManager
        from eduagent.agents.coordinator import AgentCoordinator
        from eduagent.agents.concept_qa import ConceptQAAgent
        from eduagent.agents.teaching import TeachingAgent
        from eduagent.agents.practice_agent import PracticeAgent
        from eduagent.agents.paper_search import PaperSearchAgent
        from eduagent.knowledge.retriever import KnowledgeBase
        from eduagent.knowledge.parser import parse_directory
        from pathlib import Path

        # 知识库（Agent领域知识）
        kb = KnowledgeBase()
        data_dir = Path(__file__).parent.parent / "data" / "agent_knowledge"
        if data_dir.exists():
            chunks = parse_directory(data_dir)
            for c in chunks:
                kb.add(c.content, c.source, {"heading": c.heading})
            logger.info(f"知识库加载: {kb.size} 个文档块")

        # Agent 协调器
        coordinator = AgentCoordinator()
        coordinator.register(ConceptQAAgent(kb))
        coordinator.register(TeachingAgent(knowledge_base=kb))
        coordinator.register(PracticeAgent())
        coordinator.register(PaperSearchAgent(kb))

        # 记忆
        memory_dir = str(Path(__file__).parent.parent / "data" / "memory")
        _app_state["memories"] = {}
        _app_state["memory_dir"] = memory_dir

        mem_path = Path(memory_dir)
        if mem_path.exists():
            for f in mem_path.glob("*/memories.json"):
                student_id = f.parent.name
                mm = MemoryManager(student_id=student_id, storage_dir=memory_dir)
                _app_state["memories"][student_id] = mm
                logger.info(f"加载学生记忆: {student_id} ({len(mm.long_term._memories)} 条)")

        if "default" not in _app_state["memories"]:
            _app_state["memories"]["default"] = MemoryManager(
                student_id="default", storage_dir=memory_dir)

        _app_state["coordinator"] = coordinator
        _app_state["kb"] = kb

        logger.info("EduAgent 启动完成")
    except Exception as e:
        logger.error(f"启动失败: {e}")
        import traceback
        traceback.print_exc()

    yield
    logger.info("EduAgent 关闭")


app = FastAPI(title="EduAgent API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup_event():
    """备份：确保 _app_state 在 lifespan 未运行时也能初始化"""
    if "coordinator" not in _app_state:
        logger.info("startup_event: 补充初始化 _app_state")
        try:
            from eduagent.memory import MemoryManager
            from eduagent.agents.coordinator import AgentCoordinator
            from eduagent.agents.concept_qa import ConceptQAAgent
            from eduagent.agents.teaching import TeachingAgent
            from eduagent.agents.practice_agent import PracticeAgent
            from eduagent.agents.paper_search import PaperSearchAgent
            from eduagent.knowledge.retriever import KnowledgeBase
            from eduagent.knowledge.parser import parse_directory
            from pathlib import Path

            kb = KnowledgeBase()
            data_dir = Path(__file__).parent.parent / "data" / "agent_knowledge"
            if data_dir.exists():
                chunks = parse_directory(data_dir)
                for c in chunks:
                    kb.add(c.content, c.source, {"heading": c.heading})

            coordinator = AgentCoordinator()
            coordinator.register(ConceptQAAgent(kb))
            coordinator.register(TeachingAgent(knowledge_base=kb))
            coordinator.register(PracticeAgent())
            coordinator.register(PaperSearchAgent(kb))

            memory_dir = str(Path(__file__).parent.parent / "data" / "memory")
            _app_state["memories"] = {}
            _app_state["memory_dir"] = memory_dir
            _app_state["memories"]["default"] = MemoryManager(
                student_id="default", storage_dir=memory_dir)

            _app_state["coordinator"] = coordinator
            _app_state["kb"] = kb
            logger.info("startup_event: _app_state 初始化完成")
        except Exception as e:
            logger.error(f"startup_event 失败: {e}")


# ==================== 数据模型 ====================

class ChatRequest(BaseModel):
    query: str
    code: str = ""
    language: str = "python"
    student_id: str = "default"
    intent_hint: str = ""  # 前端期望的意图，如 "practice"

class ChatResponse(BaseModel):
    response: str
    intent: str
    memory_stats: dict = {}
    execution_log: list = []
    trajectory: str = ""  # Agent 执行轨迹（可视化）

class MemoryResponse(BaseModel):
    stats: dict
    profile: dict
    recent_memories: list = []

class ImportRequest(BaseModel):
    directory: str


# ==================== 路由 ====================

@app.get("/")
async def root():
    return {"name": "EduAgent API", "version": "0.2.0", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    from eduagent.agents.base import AgentState
    from eduagent.memory import MemoryManager

    if "coordinator" not in _app_state:
        return ChatResponse(response="服务未初始化，请重启服务", intent="error")

    coordinator = _app_state["coordinator"]

    student_id = req.student_id or "default"
    if student_id not in _app_state.get("memories", {}):
        _app_state.setdefault("memories", {})[student_id] = MemoryManager(
            student_id=student_id,
            storage_dir=_app_state["memory_dir"],
        )
    memory = _app_state["memories"][student_id]

    memory_ctx = memory.recall(req.query)

    state = AgentState(
        user_query=req.query,
        code=req.code,
        language=req.language,
        student_id=student_id,
        memory_context=memory_ctx,
    )

    # 前端意图提示：如果用户从特定页面发起请求，直接路由到对应 Agent
    if req.intent_hint:
        state.intent = req.intent_hint

    state = await coordinator.run(state)

    memory.remember(req.query, "user")
    memory.remember(state.response, "assistant")

    return ChatResponse(
        response=state.response,
        intent=state.intent,
        memory_stats=memory.get_stats(),
        execution_log=state.execution_log,
        trajectory=state.trajectory.to_display() if state.trajectory else "",
    )

@app.get("/api/memory", response_model=MemoryResponse)
async def get_memory(student_id: str = "default"):
    memories = _app_state.get("memories", {})
    memory = memories.get(student_id, memories.get("default"))
    if not memory:
        return MemoryResponse(stats={"working": 0, "short_term": 0, "long_term": 0},
                             profile={"student_id": student_id, "total": 0})
    try:
        profile = memory.long_term.get_profile(student_id)
        # 合并工作记忆和短期记忆
        recent_items = list(memory.working._buffer)[-10:]
        short_items = memory.short_term._items[-5:] if memory.short_term._items else []
        all_recent = [
            {"content": m.content[:150] if hasattr(m, 'content') else str(m.get("content", ""))[:150],
             "importance": m.importance if hasattr(m, 'importance') else float(m.get("importance", 0.5))}
            for m in recent_items + list(short_items)
        ][-8:]
        return MemoryResponse(
            stats=memory.get_stats(),
            profile=profile if profile else {"student_id": student_id, "total": 0},
            recent_memories=all_recent,
        )
    except Exception as e:
        return MemoryResponse(stats=memory.get_stats(),
                             profile={"student_id": student_id, "total": 0})

@app.post("/api/import")
async def import_docs(req: ImportRequest):
    from eduagent.knowledge.parser import parse_directory
    kb = _app_state["kb"]
    try:
        chunks = parse_directory(req.directory)
        for c in chunks:
            kb.add(c.content, c.source, {"heading": c.heading})
        return {"imported": len(chunks), "total": kb.size}
    except Exception as e:
        logger.error(f"导入失败: {e}")
        return {"imported": 0, "total": kb.size, "error": str(e)}


class ImportTextRequest(BaseModel):
    title: str = "用户输入"
    content: str = ""

class ImportFileRequest(BaseModel):
    filename: str = ""
    content: str = ""

@app.post("/api/import/text")
async def import_text(req: ImportTextRequest):
    """导入一段文本到知识库"""
    kb = _app_state["kb"]
    if not req.content.strip():
        return {"imported": 0, "total": kb.size, "error": "内容为空"}
    from eduagent.knowledge.parser import _split_paragraphs
    paragraphs = _split_paragraphs(req.content)
    for p in paragraphs:
        kb.add(p, f"user://{req.title}", {"heading": req.title})
    return {"imported": len(paragraphs), "total": kb.size}


@app.post("/api/import/file")
async def import_file(req: ImportFileRequest):
    """导入上传的文件内容到知识库"""
    kb = _app_state["kb"]
    if not req.content.strip():
        return {"imported": 0, "total": kb.size, "error": "文件内容为空"}
    from eduagent.knowledge.parser import _split_paragraphs
    paragraphs = _split_paragraphs(req.content)
    for p in paragraphs:
        kb.add(p, f"file://{req.filename}", {"heading": req.filename})
    return {"imported": len(paragraphs), "total": kb.size, "filename": req.filename}


@app.get("/api/kb/stats")
async def kb_stats():
    """知识库统计"""
    kb = _app_state["kb"]
    # 统计来源分布
    sources = {}
    for doc in kb._docs:
        src = doc.get("source", "unknown")
        # 简化来源名
        if src.startswith("file://"):
            src = src.replace("file://", "")
        elif src.startswith("user://"):
            src = src.replace("user://", "文本输入: ")
        elif src.startswith("paper://"):
            src = "📄 论文: " + src.replace("paper://", "")[:80]
        elif src.startswith("arxiv://"):
            src = "📄 arXiv: " + src.replace("arxiv://", "")[:80]
        elif "/" in src:
            src = src.split("/")[-1]
        elif "\\" in src:
            src = src.split("\\")[-1]
        sources[src] = sources.get(src, 0) + 1
    return {"total": kb.size, "sources": sources}


@app.get("/api/kb/list")
async def kb_list():
    """列出所有文档"""
    kb = _app_state["kb"]
    docs = []
    for i, doc in enumerate(kb._docs):
        src = doc.get("source", "unknown")
        if src.startswith("file://"):
            src = src.replace("file://", "")
        elif src.startswith("user://"):
            src = src.replace("user://", "文本输入: ")
        elif src.startswith("paper://"):
            src = "📄 论文: " + src.replace("paper://", "")[:80]
        elif src.startswith("arxiv://"):
            src = "📄 arXiv: " + src.replace("arxiv://", "")[:80]
        elif "\\" in src:
            src = src.split("\\")[-1]
        elif "/" in src:
            src = src.split("/")[-1]
        docs.append({
            "id": i,
            "source": src,
            "content_preview": doc["content"][:100],
            "heading": doc.get("metadata", {}).get("heading", ""),
        })
    return {"total": len(docs), "docs": docs}


@app.delete("/api/kb/delete/{doc_id}")
async def kb_delete(doc_id: int):
    """删除指定文档"""
    kb = _app_state["kb"]
    if 0 <= doc_id < len(kb._docs):
        removed = kb._docs.pop(doc_id)
        # 重建 BM25 索引
        kb._doc_freqs = {}
        kb._total_docs = len(kb._docs)
        for doc in kb._docs:
            tokens = set(kb._tokenize(doc.get("content", "")))
            for t in tokens:
                kb._doc_freqs[t] = kb._doc_freqs.get(t, 0) + 1
        return {"success": True, "removed": removed.get("source", ""), "remaining": kb.size}
    return {"success": False, "error": "文档ID不存在"}


@app.delete("/api/kb/clear")
async def kb_clear():
    """清空知识库"""
    kb = _app_state["kb"]
    kb._docs.clear()
    kb._doc_freqs.clear()
    kb._total_docs = 0
    return {"success": True, "message": "知识库已清空"}


@app.post("/api/kb/search")
async def kb_search(req: ImportTextRequest):
    """在知识库中搜索"""
    kb = _app_state["kb"]
    results = kb.search(req.content, top_k=10)
    return {
        "total": len(results),
        "results": [{"content": r.content[:200], "source": r.source, "score": r.score} for r in results],
    }


# ==================== 启动 ====================

# ==================== 论文检索专用 API ====================

class PaperSearchRequest(BaseModel):
    query: str = ""
    min_citations: int = 0
    min_year: int = 2020
    max_results: int = 8

class PaperImportRequest(BaseModel):
    indices: list[int] = []  # 要导入的论文序号（1-based）


@app.post("/api/papers/search")
async def search_papers_api(req: PaperSearchRequest):
    """搜索论文（返回结构化JSON）"""
    from eduagent.knowledge.paper_api import search_papers as search_papers_func
    from eduagent.agents.paper_search import PaperSearchAgent
    from langchain_openai import ChatOpenAI
    from eduagent.config import settings

    # LLM 提取搜索词
    try:
        llm = ChatOpenAI(model=settings.llm.model, temperature=0, max_tokens=100,
                         api_key=settings.llm.api_key, base_url=settings.llm.base_url)
        prompt = f"""提取论文搜索关键词（英文）。只输出关键词：
用户: {req.query}"""
        resp = await llm.ainvoke(prompt)
        search_query = resp.content.strip()
    except Exception:
        search_query = req.query

    papers = search_papers_func(search_query, max_results=req.max_results,
                                min_year=req.min_year, min_citations=req.min_citations)
    papers.sort(key=lambda p: p.quality_score, reverse=True)

    # 暂存搜索结果供后续导入
    _app_state["_last_papers"] = papers

    return {
        "query": search_query,
        "total": len(papers),
        "papers": [
            {
                "index": i + 1,
                "title": p.title,
                "authors": p.authors[:5],
                "abstract": p.abstract[:300],
                "year": p.year,
                "citations": p.citations,
                "venue": p.venue or "",
                "quality": "⭐" if p.quality_score >= 100 else "●" if p.quality_score >= 10 else "○",
                "arxiv_id": p.arxiv_id,
            }
            for i, p in enumerate(papers)
        ],
    }


@app.post("/api/papers/import")
async def import_papers_api(req: PaperImportRequest):
    """导入选中的论文到知识库"""
    kb = _app_state["kb"]
    papers = _app_state.get("_last_papers", [])
    imported = []
    for i in req.indices:
        if 1 <= i <= len(papers):
            p = papers[i - 1]
            content = f"标题: {p.title}\n作者: {', '.join(p.authors)}\n摘要: {p.abstract}"
            kb.add(content, f"paper://{p.title[:50]}", {"heading": p.title})
            imported.append(f"#{i} {p.title[:60]}")
    return {"imported": len(imported), "papers": imported, "total_kb": kb.size}


if __name__ == "__main__":
    import uvicorn
    from eduagent.config import settings
    uvicorn.run("eduagent.api.main:app", host=settings.app.host, port=settings.app.port, reload=True)
