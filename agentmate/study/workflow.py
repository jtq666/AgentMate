"""固定 Supervisor 流水线与单并发后台任务队列。"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from agentmate.study.agents import StudyAgents
from agentmate.study.models import (
    InterviewOutput,
    ResearchOutput,
    StageStatus,
    StudyGoal,
    StudyLevel,
    StudyState,
    TaskStatus,
    TeachingOutput,
)
from agentmate.study.repository import STAGE_ORDER, StudyRepository

logger = logging.getLogger(__name__)


class StudyTaskManager:
    """进程内单消费者队列，保证本地最多运行一个模型链路。"""

    def __init__(self, repository: StudyRepository, agents: StudyAgents,
                 stage_timeout: int = 90, max_retries: int = 1):
        self.repository = repository
        self.agents = agents
        self.stage_timeout = stage_timeout
        self.max_retries = max_retries
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    def start(self) -> None:
        if not self.worker or self.worker.done():
            self.worker = asyncio.create_task(self._worker_loop(), name="agentmate-study-worker")

    async def shutdown(self) -> None:
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker

    async def submit_task(self, task_id: str) -> None:
        await self.queue.put(("task", task_id))

    async def submit_assessment(self, assessment_id: str) -> None:
        await self.queue.put(("assessment", assessment_id))

    async def _worker_loop(self) -> None:
        while True:
            kind, item_id = await self.queue.get()
            try:
                if kind == "task":
                    await self.run_task(item_id)
                else:
                    await self.run_assessment(item_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background %s job failed: %s", kind, item_id)
            finally:
                self.queue.task_done()

    def _load_state(self, task_id: str) -> StudyState:
        task = self.repository.get_task(task_id, include_internal=True)
        if not task:
            raise ValueError("研学任务不存在")
        return StudyState(
            task_id=task_id,
            student_id=task["student_id"],
            topic=task["topic"],
            goal=StudyGoal(task["goal"]),
            level=StudyLevel(task["level"]),
            include_papers=task["include_papers"],
            focus_points=task.get("focus_points", []),
            question_types=task.get("question_types", ["综合问答"]),
            research=ResearchOutput.model_validate(task["artifacts"]["research"])
            if task["artifacts"].get("research") else None,
            teaching=TeachingOutput.model_validate(task["artifacts"]["teaching"])
            if task["artifacts"].get("teaching") else None,
            interview=InterviewOutput.model_validate(task["artifacts"]["interview"])
            if task["artifacts"].get("interview") else None,
            report_markdown=task["artifacts"].get("report", {}).get("markdown", ""),
            warnings=(task["artifacts"].get("research") or {}).get("warnings", []),
        )

    async def run_task(self, task_id: str) -> None:
        state = self._load_state(task_id)
        self.repository.update_task_status(task_id, TaskStatus.RUNNING.value)
        task = self.repository.get_task(task_id, include_internal=True)
        completed = {stage["name"] for stage in task["stages"]
                     if stage["status"] == StageStatus.COMPLETED.value}
        try:
            for stage_name in STAGE_ORDER:
                if stage_name in completed:
                    continue
                await self._run_stage(state, stage_name)
            self.repository.update_task_status(task_id, TaskStatus.COMPLETED.value)
        except asyncio.CancelledError:
            self.repository.update_task_status(task_id, TaskStatus.INTERRUPTED.value,
                                               "服务停止导致任务中断，可重试。")
            raise
        except Exception as exc:
            self.repository.update_task_status(task_id, TaskStatus.FAILED.value, str(exc))

    async def _run_stage(self, state: StudyState, stage_name: str) -> None:
        task_id = state.task_id
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            self.repository.update_stage(
                task_id, stage_name, StageStatus.RUNNING.value,
                summary=f"{stage_name.title()} Agent 正在执行（第 {attempt + 1} 次）",
                increment_attempt=True,
            )
            try:
                result, summary = await asyncio.wait_for(
                    self._execute_stage(state, stage_name), timeout=self.stage_timeout
                )
                elapsed = int((time.perf_counter() - started) * 1000)
                if result is not None:
                    self.repository.save_artifact(task_id, stage_name if stage_name != "supervisor" else "report", result)
                self.repository.update_stage(
                    task_id, stage_name, StageStatus.COMPLETED.value,
                    summary=summary, duration_ms=elapsed,
                    metrics={"attempt": attempt + 1, "timeout_seconds": self.stage_timeout},
                )
                return
            except Exception as exc:
                last_error = exc
                elapsed = int((time.perf_counter() - started) * 1000)
                if attempt < self.max_retries:
                    self.repository.update_stage(
                        task_id, stage_name, StageStatus.QUEUED.value,
                        summary="阶段失败，准备自动重试", error=str(exc), duration_ms=elapsed,
                    )
                    continue
                self.repository.update_stage(
                    task_id, stage_name, StageStatus.FAILED.value,
                    summary="阶段执行失败", error=str(exc), duration_ms=elapsed,
                )
        raise RuntimeError(f"{stage_name} 阶段失败：{last_error}")

    async def _execute_stage(self, state: StudyState, stage_name: str):
        if stage_name == "research":
            state.research = await self.agents.research_agent.run(state)
            state.warnings = state.research.warnings
            self.repository.replace_sources(
                state.task_id, [source.model_dump(mode="json") for source in state.research.sources]
            )
            return state.research, f"检索到 {len(state.research.sources)} 条可追溯来源"
        if stage_name == "teaching":
            state.teaching = await self.agents.teaching_agent.run(state)
            return state.teaching, f"生成 {len(state.teaching.concepts)} 个核心概念"
        if stage_name == "interview":
            state.interview = await self.agents.interview_agent.run(state)
            if len(state.interview.questions) != 5:
                raise ValueError("Interview Agent 必须生成 5 道问题")
            return state.interview, "生成 5 道递进面试题（评分规则已隐藏）"
        if stage_name == "supervisor":
            valid = {source.citation_id for source in (state.research.sources if state.research else [])}
            if state.teaching:
                for concept in state.teaching.concepts:
                    concept.citations = [item for item in concept.citations if item in valid]
            state.report_markdown = self.agents.supervisor.build_report(state)
            return {"markdown": state.report_markdown, "valid_citations": sorted(valid)}, "引用校验通过并生成初始报告"
        raise ValueError(f"未知阶段：{stage_name}")

    async def run_assessment(self, assessment_id: str) -> None:
        assessment = self.repository.get_assessment(assessment_id)
        if not assessment:
            return
        self.repository.update_assessment(assessment_id, TaskStatus.RUNNING.value)
        try:
            state = self._load_state(assessment["task_id"])
            result = await asyncio.wait_for(
                self.agents.evaluation_agent.run(state, assessment["answers"]), timeout=self.stage_timeout
            )
            mastery = self.repository.update_mastery(
                assessment["student_id"], state.topic, result.total_score, result.weak_points
            )
            result_payload = result.model_dump(mode="json")
            result_payload["mastery"] = mastery
            self.repository.update_assessment(
                assessment_id, TaskStatus.COMPLETED.value, result_payload, result.total_score
            )
            report = self.agents.supervisor.build_report(state, result, mastery)
            self.repository.save_artifact(state.task_id, "report", {
                "markdown": report,
                "valid_citations": [source.citation_id for source in (state.research.sources if state.research else [])],
                "assessment_id": assessment_id,
            })
        except asyncio.CancelledError:
            self.repository.update_assessment(
                assessment_id, TaskStatus.INTERRUPTED.value, error="服务停止导致评测中断。"
            )
            raise
        except Exception as exc:
            self.repository.update_assessment(
                assessment_id, TaskStatus.FAILED.value, error=str(exc)
            )

    async def chat(self, task_id: str, message: str, session_id: str | None = None) -> dict:
        state = self._load_state(task_id)
        if not state.research:
            raise ValueError("Research 阶段尚未完成，暂时不能追问。")
        history = self.repository.list_messages(task_id, session_id=session_id)
        self.repository.add_message(task_id, "user", message, session_id=session_id)
        answer, citations = await asyncio.wait_for(
            self.agents.answer_task_chat(state, message, history), timeout=self.stage_timeout
        )
        self.repository.add_message(
            task_id, "assistant", answer, citations, session_id=session_id
        )
        return {"answer": answer, "citations": citations,
                "session_id": session_id,
                "messages": self.repository.list_messages(task_id, session_id=session_id)}
