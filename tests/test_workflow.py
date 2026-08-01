import asyncio

from agentmate.study.agents import StudyAgents
from agentmate.study.models import TaskStatus
from agentmate.study.repository import StudyRepository
from agentmate.study.workflow import StudyTaskManager


def test_fixed_pipeline_citations_and_private_rubric(tmp_path):
    from conftest import FakeKnowledgeBase

    async def scenario():
        repository = StudyRepository(tmp_path / "study.db")
        agents = StudyAgents(FakeKnowledgeBase(), enable_llm=False)
        manager = StudyTaskManager(repository, agents, stage_timeout=2, max_retries=0)
        task_id = repository.create_task("default", "ReAct", "准备面试", "进阶", False)
        await manager.run_task(task_id)
        public = repository.get_task(task_id)
        internal = repository.get_task(task_id, include_internal=True)
        assert public["status"] == TaskStatus.COMPLETED.value
        assert [stage["status"] for stage in public["stages"]] == ["completed"] * 4
        assert public["sources"][0]["citation_id"] == "S1"
        assert "rubric" not in public["artifacts"]["interview"]["questions"][0]
        assert "rubric" in internal["artifacts"]["interview"]["questions"][0]
        citations = internal["artifacts"]["teaching"]["concepts"][0]["citations"]
        assert set(citations) <= {"S1"}

    asyncio.run(scenario())


def test_assessment_updates_mastery_and_report(tmp_path):
    from conftest import FakeKnowledgeBase

    async def scenario():
        repository = StudyRepository(tmp_path / "study.db")
        manager = StudyTaskManager(
            repository, StudyAgents(FakeKnowledgeBase(), enable_llm=False),
            stage_timeout=2, max_retries=0,
        )
        task_id = repository.create_task("default", "ReAct", "准备面试", "进阶", False)
        await manager.run_task(task_id)
        assessment_id = repository.create_assessment(
            task_id, "default", ["定义、目标和适用场景，包含流程输入输出和工程权衡。"] * 5
        )
        await manager.run_assessment(assessment_id)
        assessment = repository.get_assessment(assessment_id)
        assert assessment["status"] == "completed"
        assert 0 <= assessment["total_score"] <= 100
        assert assessment["result"]["mastery"]["evidence_count"] == 1
        report = repository.get_artifact(task_id, "report")["markdown"]
        assert "本次得分" not in report
        assert "总分" in report
        assert "[S1]" in report

    asyncio.run(scenario())
