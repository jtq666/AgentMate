import time

from conftest import FakeKnowledgeBase
from fastapi.testclient import TestClient

from agentmate.api import main as api_main
from agentmate.study.agents import StudyAgents as RealStudyAgents


def test_study_api_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(api_main.settings.app, "study_db_path", str(tmp_path / "api.db"))
    monkeypatch.setattr(api_main.settings.app, "kb_persist_dir", str(tmp_path / "kb"))
    monkeypatch.setattr(api_main, "StudyAgents", lambda kb: RealStudyAgents(kb, enable_llm=False))
    import agentmate.knowledge.retriever as retriever
    monkeypatch.setattr(retriever, "KnowledgeBase", lambda **kwargs: FakeKnowledgeBase())

    with TestClient(api_main.app) as client:
        response = client.post("/api/study/tasks", json={
            "topic": "ReAct", "goal": "准备面试", "level": "进阶",
            "include_papers": False, "student_id": "default",
        })
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        deadline = time.time() + 3
        while time.time() < deadline:
            task = client.get(f"/api/study/tasks/{task_id}").json()
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed"
        assert len(task["artifacts"]["interview"]["questions"]) == 5
        assert "rubric" not in task["artifacts"]["interview"]["questions"][0]

        response = client.post(f"/api/study/tasks/{task_id}/assessments", json={
            "answers": ["定义、流程、输入输出、失败恢复、实验对比和工程权衡。"] * 5,
            "student_id": "default",
        })
        assert response.status_code == 202
        assessment_id = response.json()["assessment_id"]
        deadline = time.time() + 3
        while time.time() < deadline:
            assessment = client.get(f"/api/assessments/{assessment_id}").json()
            if assessment["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert assessment["status"] == "completed"
        report = client.get(f"/api/study/tasks/{task_id}/report?format=markdown")
        assert report.status_code == 200
        assert "# AgentMate 研学报告" in report.text


def test_assessment_requires_all_answers(tmp_path, monkeypatch):
    # Pydantic request validation protects answer hiding/submit-all semantics.
    import pytest

    from agentmate.api.main import AssessmentCreate

    with pytest.raises(ValueError):
        AssessmentCreate(answers=["only one"], student_id="default")


def test_api_rejects_out_of_scope_topic_without_creating_task(tmp_path, monkeypatch):
    monkeypatch.setattr(api_main.settings.app, "study_db_path", str(tmp_path / "scope.db"))
    monkeypatch.setattr(api_main.settings.app, "kb_persist_dir", str(tmp_path / "scope-kb"))
    monkeypatch.setattr(api_main, "StudyAgents", lambda kb: RealStudyAgents(kb, enable_llm=False))
    import agentmate.knowledge.retriever as retriever

    monkeypatch.setattr(retriever, "KnowledgeBase", lambda **kwargs: FakeKnowledgeBase())
    with TestClient(api_main.app) as client:
        check = client.post("/api/study/topics/check", json={"topic": "Transformer"})
        assert check.status_code == 200
        assert check.json()["status"] == "out_of_scope"

        before = client.get("/api/study/tasks").json()["tasks"]
        response = client.post("/api/study/tasks", json={
            "topic": "Transformer",
            "goal": "理解概念",
            "level": "进阶",
            "student_id": "default",
        })
        after = client.get("/api/study/tasks").json()["tasks"]

        assert response.status_code == 422
        assert response.json()["detail"]["status"] == "out_of_scope"
        assert len(after) == len(before)
