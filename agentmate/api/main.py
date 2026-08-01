"""AgentMate v1.0 FastAPI 后端。"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from agentmate.config import settings
from agentmate.study.agents import StudyAgents
from agentmate.study.migration import migrate_legacy_data
from agentmate.study.models import StudyGoal, StudyLevel, TaskStatus
from agentmate.study.repository import StudyRepository
from agentmate.study.topic_scope import check_topic
from agentmate.study.workflow import StudyTaskManager

logger = logging.getLogger(__name__)
_app_state: dict = {}
QUESTION_TYPES = {"综合问答", "概念辨析", "系统设计", "项目深挖", "论文追问"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from agentmate.knowledge.parser import parse_directory
    from agentmate.knowledge.retriever import KnowledgeBase

    kb = KnowledgeBase(persist_dir=settings.app.kb_persist_dir)
    course_dir = Path(__file__).resolve().parent.parent / "data" / "agent_knowledge"
    if course_dir.exists():
        for chunk in parse_directory(course_dir):
            kb.add(chunk.content, chunk.source, {
                "heading": chunk.heading,
                "source_type": "course",
            })
    repository = StudyRepository(settings.app.study_db_path)
    interrupted = repository.mark_unfinished_interrupted()
    migration = migrate_legacy_data(repository, course_dir.parent)
    agents = StudyAgents(kb)
    manager = StudyTaskManager(
        repository, agents,
        stage_timeout=settings.app.stage_timeout_seconds,
        max_retries=settings.app.stage_max_retries,
    )
    manager.start()
    _app_state.update({
        "kb": kb,
        "repository": repository,
        "manager": manager,
        "paper_searches": {},
        "startup": {"interrupted_tasks": interrupted, "migration": migration},
    })
    logger.info("AgentMate ready: %s chunks, %s interrupted tasks", kb.size, interrupted)
    try:
        yield
    finally:
        await manager.shutdown()
        _app_state.clear()


app = FastAPI(
    title="AgentMate API",
    description="AI Agent 专题研学与保研面试训练平台",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.app.cors_origins),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


def _repo() -> StudyRepository:
    if "repository" not in _app_state:
        raise HTTPException(status_code=503, detail="服务仍在初始化")
    return _app_state["repository"]


def _manager() -> StudyTaskManager:
    if "manager" not in _app_state:
        raise HTTPException(status_code=503, detail="服务仍在初始化")
    return _app_state["manager"]


def _kb():
    if "kb" not in _app_state:
        raise HTTPException(status_code=503, detail="服务仍在初始化")
    return _app_state["kb"]


def _normalize_student_id(value: str) -> str:
    value = (value or "default").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise HTTPException(status_code=400, detail="student_id 仅允许字母、数字、下划线和连字符")
    return value


class StudyTaskCreate(BaseModel):
    topic: str = Field(min_length=2, max_length=100)
    goal: StudyGoal = StudyGoal.INTERVIEW
    level: StudyLevel = StudyLevel.INTERMEDIATE
    include_papers: bool = False
    focus_points: list[str] = Field(default_factory=list, max_length=5)
    question_types: list[str] = Field(default_factory=lambda: ["综合问答"], min_length=1)
    student_id: str = "default"

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @field_validator("question_types")
    @classmethod
    def validate_question_types(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(values))
        if not set(cleaned).issubset(QUESTION_TYPES):
            raise ValueError("包含不支持的面试题型")
        return cleaned


class TopicCheckRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=100)

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()


class TaskChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ChatSessionCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=80)


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class StudyTaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class AssessmentCreate(BaseModel):
    answers: list[str] = Field(min_length=5, max_length=5)
    student_id: str = "default"

    @field_validator("answers")
    @classmethod
    def all_answers_required(cls, answers: list[str]) -> list[str]:
        cleaned = [answer.strip() for answer in answers]
        if any(not answer for answer in cleaned):
            raise ValueError("必须完成全部 5 道题后再提交")
        return cleaned


class ImportTextRequest(BaseModel):
    title: str = Field(default="用户资料", max_length=200)
    content: str = Field(min_length=1, max_length=1_000_000)


class ImportFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)


class DirectoryImportRequest(BaseModel):
    directory: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=20)


class PaperSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    min_citations: int = Field(default=0, ge=0)
    min_year: int = Field(default=2020, ge=1990, le=2100)
    max_year: int = Field(default=2100, ge=1990, le=2100)
    max_results: int = Field(default=8, ge=1, le=20)
    sources: list[str] = Field(
        default_factory=lambda: ["semantic_scholar", "arxiv"],
        min_length=1,
    )


class PaperImportRequest(BaseModel):
    search_id: str
    indices: list[int] = Field(default_factory=list, max_length=20)


class KnowledgeUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=150)


@app.get("/")
async def root():
    return {"name": "AgentMate", "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "knowledge_chunks": _app_state.get("kb").size if _app_state.get("kb") else 0,
        "queue_size": _app_state.get("manager").queue.qsize() if _app_state.get("manager") else 0,
        "pipeline": ["research", "teaching", "interview", "supervisor"],
    }


@app.post("/api/study/topics/check")
async def check_study_topic(request: TopicCheckRequest):
    return check_topic(_kb(), request.topic).model_dump()


@app.post("/api/study/tasks", status_code=202)
async def create_study_task(request: StudyTaskCreate):
    topic_check = check_topic(_kb(), request.topic)
    if topic_check.status != "supported":
        raise HTTPException(status_code=422, detail=topic_check.model_dump())
    student_id = _normalize_student_id(request.student_id)
    task_id = _repo().create_task(
        student_id,
        request.topic,
        request.goal.value,
        request.level.value,
        request.include_papers,
        [point.strip()[:300] for point in request.focus_points if point.strip()],
        request.question_types,
    )
    await _manager().submit_task(task_id)
    task = _repo().get_task(task_id)
    return {"task_id": task_id, "status": TaskStatus.QUEUED.value, "stages": task["stages"]}


@app.get("/api/study/tasks")
async def list_study_tasks(
    student_id: str = "default",
    status: str | None = None,
    topic: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    include_archived: bool = False,
):
    if status and status not in {item.value for item in TaskStatus}:
        raise HTTPException(status_code=400, detail="无效任务状态")
    return {
        "tasks": _repo().list_tasks(
            _normalize_student_id(student_id), status, topic, limit, include_archived
        )
    }


@app.get("/api/study/tasks/{task_id}")
async def get_study_task(task_id: str):
    task = _repo().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="研学任务不存在")
    task["messages"] = _repo().list_messages(task_id)
    return task


@app.patch("/api/study/tasks/{task_id}")
async def update_study_task(task_id: str, request: StudyTaskUpdate):
    task = _repo().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="研学任务不存在")
    if task["status"] in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
        raise HTTPException(status_code=409, detail="执行中的任务不能重命名或归档")
    _repo().update_task_metadata(task_id, title=request.title, archived=request.archived)
    return _repo().get_task(task_id)


@app.delete("/api/study/tasks/{task_id}")
async def delete_study_task(task_id: str):
    task = _repo().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="研学任务不存在")
    if task["status"] in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
        raise HTTPException(status_code=409, detail="执行中的任务不能删除")
    _repo().delete_task(task_id)
    return {"deleted": True, "task_id": task_id}


@app.post("/api/study/tasks/{task_id}/retry", status_code=202)
async def retry_study_task(task_id: str):
    stage = _repo().prepare_retry(task_id)
    if not stage:
        raise HTTPException(status_code=409, detail="只有失败或中断的任务可以重试")
    await _manager().submit_task(task_id)
    return {"task_id": task_id, "status": TaskStatus.QUEUED.value, "retry_from": stage}


@app.post("/api/study/tasks/{task_id}/chat")
async def task_chat(task_id: str, request: TaskChatRequest):
    task = _repo().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="研学任务不存在")
    session_id = request.session_id
    if session_id and not _repo().chat_session_exists(task_id, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    if not session_id:
        session_id = _repo().list_chat_sessions(task_id)[0]["id"]
    try:
        return await _manager().chat(task_id, request.message.strip(), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="任务追问超时，请稍后重试") from exc


@app.get("/api/study/tasks/{task_id}/chat/sessions")
async def list_chat_sessions(task_id: str):
    if not _repo().get_task(task_id):
        raise HTTPException(status_code=404, detail="研学任务不存在")
    return {"sessions": _repo().list_chat_sessions(task_id)}


@app.post("/api/study/tasks/{task_id}/chat/sessions")
async def create_chat_session(task_id: str, request: ChatSessionCreate):
    if not _repo().get_task(task_id):
        raise HTTPException(status_code=404, detail="研学任务不存在")
    session_id = _repo().create_chat_session(task_id, request.title)
    return {"session_id": session_id, "title": request.title}


@app.patch("/api/study/tasks/{task_id}/chat/sessions/{session_id}")
async def update_chat_session(
    task_id: str, session_id: str, request: ChatSessionUpdate
):
    if not _repo().update_chat_session(task_id, session_id, request.title):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "title": request.title}


@app.delete("/api/study/tasks/{task_id}/chat/sessions/{session_id}")
async def delete_chat_session(task_id: str, session_id: str):
    if not _repo().delete_chat_session(task_id, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True, "session_id": session_id}


@app.get("/api/study/tasks/{task_id}/chat/sessions/{session_id}/messages")
async def list_chat_session_messages(task_id: str, session_id: str):
    if not _repo().chat_session_exists(task_id, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"messages": _repo().list_messages(task_id, session_id=session_id)}


@app.post("/api/study/tasks/{task_id}/assessments", status_code=202)
async def create_assessment(task_id: str, request: AssessmentCreate):
    task = _repo().get_task(task_id, include_internal=True)
    if not task:
        raise HTTPException(status_code=404, detail="研学任务不存在")
    if task["status"] != TaskStatus.COMPLETED.value or not task["artifacts"].get("interview"):
        raise HTTPException(status_code=409, detail="研学内容尚未生成完成")
    student_id = _normalize_student_id(request.student_id)
    if student_id != task["student_id"]:
        raise HTTPException(status_code=403, detail="评测学生与任务学生不一致")
    assessment_id = _repo().create_assessment(task_id, student_id, request.answers)
    await _manager().submit_assessment(assessment_id)
    return {"assessment_id": assessment_id, "task_id": task_id, "status": TaskStatus.QUEUED.value}


@app.get("/api/assessments/{assessment_id}")
async def get_assessment(assessment_id: str):
    assessment = _repo().get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="评测不存在")
    return assessment


@app.get("/api/mastery")
async def get_mastery(student_id: str = "default"):
    return {"records": _repo().list_mastery(_normalize_student_id(student_id))}


@app.get("/api/study/tasks/{task_id}/report")
async def get_report(task_id: str, format: Literal["json", "markdown"] = "json"):
    task = _repo().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="研学任务不存在")
    report = task["artifacts"].get("report")
    if not report:
        raise HTTPException(status_code=409, detail="报告尚未生成")
    markdown = report.get("markdown", "")
    if format == "markdown":
        safe_topic = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", task["topic"])
        return PlainTextResponse(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''AgentMate_{safe_topic}.md"},
        )
    return {"task_id": task_id, "topic": task["topic"], "markdown": markdown,
            "sources": task["sources"], "assessment": _repo().latest_assessment_for_task(task_id)}


def _source_label(source: str) -> str:
    if source.startswith("user://"):
        return "用户文本：" + source.removeprefix("user://")
    if source.startswith("file://"):
        return source.removeprefix("file://")
    if source.startswith(("paper://", "arxiv://")):
        return "论文：" + source.split("://", 1)[1]
    return Path(source).name or source


@app.get("/api/kb/stats")
async def kb_stats():
    kb = _app_state["kb"]
    sources: dict[str, int] = {}
    types: dict[str, int] = {}
    for doc in kb._docs:
        label = _source_label(doc.get("source", "unknown"))
        source_type = doc.get("metadata", {}).get("source_type", "course")
        sources[label] = sources.get(label, 0) + 1
        types[source_type] = types.get(source_type, 0) + 1
    return {"total": kb.size, "sources": sources, "source_types": types}


@app.get("/api/kb/list")
async def kb_list():
    docs = []
    for index, doc in enumerate(_app_state["kb"]._docs):
        metadata = doc.get("metadata", {})
        docs.append({
            "id": index,
            "document_id": doc["id"],
            "source": metadata.get("heading") or _source_label(doc.get("source", "unknown")),
            "source_type": metadata.get("source_type", "course"),
            "heading": metadata.get("heading", ""),
            "task_id": metadata.get("task_id", ""),
            "content_preview": doc["content"][:240],
        })
    return {"total": len(docs), "docs": docs}


@app.post("/api/kb/search")
async def kb_search(request: SearchRequest):
    results = _app_state["kb"].search(request.query, request.top_k)
    return {"total": len(results), "results": [{
        "document_id": result.doc_id,
        "content": result.content,
        "source": result.source,
        "source_type": result.metadata.get("source_type", "course"),
        "score": result.score,
        "method": result.method,
    } for result in results]}


@app.post("/api/import/text")
async def import_text(request: ImportTextRequest):
    from agentmate.knowledge.parser import _split_paragraphs

    chunks = _split_paragraphs(request.content)
    ids = [_app_state["kb"].add(chunk, f"user://{request.title}", {
        "heading": request.title, "source_type": "user",
    }) for chunk in chunks]
    return {"imported": len(ids), "document_ids": ids, "total": _app_state["kb"].size}


@app.post("/api/import/file")
async def import_file(request: ImportFileRequest):
    from agentmate.knowledge.parser import parse_file

    safe_name = Path(request.filename).name
    try:
        raw = base64.b64decode(request.content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="文件编码无效") from exc
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件不能超过 10MB")
    with tempfile.TemporaryDirectory(prefix="agentmate_upload_") as temp_dir:
        path = Path(temp_dir) / safe_name
        path.write_bytes(raw)
        chunks = parse_file(path)
    ids = [_app_state["kb"].add(chunk.content, f"file://{safe_name}", {
        "heading": chunk.heading or safe_name, "source_type": "user",
    }) for chunk in chunks]
    return {"imported": len(ids), "document_ids": ids, "filename": safe_name,
            "total": _app_state["kb"].size}


def _resolve_import_directory(directory: str) -> Path:
    requested = Path(directory).expanduser().resolve()
    roots = [Path(root).expanduser().resolve() for root in settings.app.import_roots]
    if not requested.is_dir():
        raise HTTPException(status_code=400, detail="导入目录不存在")
    if not any(requested == root or root in requested.parents for root in roots):
        raise HTTPException(status_code=403, detail="目录不在 AGENTMATE_IMPORT_ROOTS 允许范围内")
    return requested


@app.post("/api/import")
async def import_directory(request: DirectoryImportRequest):
    from agentmate.knowledge.parser import parse_directory

    chunks = parse_directory(_resolve_import_directory(request.directory))
    for chunk in chunks:
        _app_state["kb"].add(chunk.content, chunk.source, {
            "heading": chunk.heading, "source_type": "user",
        })
    return {"imported": len(chunks), "total": _app_state["kb"].size}


@app.delete("/api/kb/delete/{doc_index}")
async def kb_delete(doc_index: int):
    removed = _app_state["kb"].delete_at(doc_index)
    if not removed:
        raise HTTPException(status_code=404, detail="资料不存在")
    return {"success": True, "removed": removed["source"], "remaining": _app_state["kb"].size}


@app.patch("/api/kb/{doc_index}")
async def kb_update(doc_index: int, request: KnowledgeUpdate):
    updated = _app_state["kb"].update_title_at(doc_index, request.title)
    if not updated:
        raise HTTPException(status_code=404, detail="资料不存在")
    return {"updated": True, "id": doc_index, "title": request.title}


@app.post("/api/papers/search")
async def papers_search(request: PaperSearchRequest):
    from agentmate.knowledge.paper_api import search_papers

    allowed_sources = {"semantic_scholar", "arxiv"}
    if request.min_year > request.max_year:
        raise HTTPException(status_code=422, detail="最早年份不能晚于最晚年份")
    if not set(request.sources).issubset(allowed_sources):
        raise HTTPException(status_code=422, detail="论文来源仅支持 Semantic Scholar 和 arXiv")
    papers = await asyncio.to_thread(
        search_papers, request.query.strip(), request.max_results,
        request.min_year, request.max_year, request.min_citations, request.sources,
    )
    papers.sort(key=lambda paper: paper.quality_score, reverse=True)
    search_id = uuid.uuid4().hex
    searches = _app_state["paper_searches"]
    searches[search_id] = papers
    while len(searches) > 100:
        searches.pop(next(iter(searches)))
    current_year = datetime.now(timezone.utc).year
    top_venues = ("NeurIPS", "ICML", "ICLR", "ACL", "EMNLP", "NAACL", "AAAI", "IJCAI")

    def reasons(paper) -> list[str]:
        items = []
        if paper.year and paper.year >= current_year - 2:
            items.append("近三年")
        if paper.citations >= 100:
            items.append("高引用")
        if any(venue.lower() in paper.venue.lower() for venue in top_venues):
            items.append("重要会议")
        if paper.source == "arxiv":
            items.append("最新预印本")
        return items or ["主题相关"]

    return {"search_id": search_id, "query": request.query, "total": len(papers), "papers": [{
        "index": index,
        "title": paper.title,
        "authors": paper.authors[:5],
        "abstract": paper.abstract[:500],
        "year": paper.year,
        "citations": paper.citations,
        "venue": paper.venue,
        "url": paper.url or paper.pdf_url,
        "arxiv_id": paper.arxiv_id,
        "source": paper.source,
        "has_pdf": bool(paper.pdf_url or paper.arxiv_id),
        "is_top_venue": any(venue.lower() in paper.venue.lower() for venue in top_venues),
        "recommendation_reasons": reasons(paper),
    } for index, paper in enumerate(papers, 1)]}


@app.post("/api/papers/import")
async def papers_import(request: PaperImportRequest):
    papers = _app_state["paper_searches"].get(request.search_id)
    if papers is None:
        raise HTTPException(status_code=404, detail="论文搜索结果不存在或已过期")
    imported = []
    for index in request.indices:
        if not 1 <= index <= len(papers):
            continue
        paper = papers[index - 1]
        document_id = _app_state["kb"].add(
            f"标题：{paper.title}\n作者：{', '.join(paper.authors)}\n摘要：{paper.abstract}",
            paper.url or f"paper://{paper.title}",
            {"heading": paper.title, "source_type": "paper"},
        )
        imported.append({"index": index, "title": paper.title, "document_id": document_id})
    return {"imported": len(imported), "papers": imported, "total": _app_state["kb"].size}
