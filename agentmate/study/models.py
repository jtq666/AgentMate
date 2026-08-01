"""研学任务的领域模型与各 Agent 的结构化输出。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class StageStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class StudyGoal(str, Enum):
    UNDERSTAND = "理解概念"
    INTERVIEW = "准备面试"
    REVIEW = "研究综述"


class StudyLevel(str, Enum):
    BEGINNER = "入门"
    INTERMEDIATE = "进阶"
    ADVANCED = "深入"


class SourceRef(BaseModel):
    citation_id: str
    document_id: str
    title: str
    source: str
    source_type: str = "course"
    excerpt: str = ""
    url: str = ""


class ResearchOutput(BaseModel):
    sources: list[SourceRef] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)


class ConceptSection(BaseModel):
    title: str
    explanation: str
    example: str = ""
    citations: list[str] = Field(default_factory=list)


class TeachingOutput(BaseModel):
    learning_map: list[str] = Field(default_factory=list)
    overview: str = ""
    concepts: list[ConceptSection] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    summary: str = ""


class InterviewQuestion(BaseModel):
    id: str
    question: str
    difficulty: int = Field(ge=1, le=5)
    question_type: str = "综合问答"
    rubric: str
    required_points: list[str] = Field(default_factory=list)
    follow_up: str = ""


class InterviewOutput(BaseModel):
    questions: list[InterviewQuestion] = Field(default_factory=list)


class QuestionEvaluation(BaseModel):
    question_id: str
    score: float = Field(ge=0, le=20)
    hits: list[str] = Field(default_factory=list)
    misses: list[str] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    feedback: str = ""


class EvaluationOutput(BaseModel):
    items: list[QuestionEvaluation] = Field(default_factory=list)
    total_score: float = Field(ge=0, le=100)
    weak_points: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str = ""


class StudyState(BaseModel):
    task_id: str
    student_id: str = "default"
    topic: str
    goal: StudyGoal
    level: StudyLevel
    include_papers: bool = False
    focus_points: list[str] = Field(default_factory=list)
    question_types: list[str] = Field(default_factory=lambda: ["综合问答"])
    research: ResearchOutput | None = None
    teaching: TeachingOutput | None = None
    interview: InterviewOutput | None = None
    report_markdown: str = ""
    warnings: list[str] = Field(default_factory=list)
