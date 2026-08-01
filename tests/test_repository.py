from agentmate.study.models import StageStatus, TaskStatus
from agentmate.study.repository import StudyRepository


def test_task_schema_and_artifacts(tmp_path):
    repository = StudyRepository(tmp_path / "study.db")
    task_id = repository.create_task(
        "alice", "ReAct", "准备面试", "进阶", True,
        ["Observation 反馈", "工程权衡"], ["概念辨析", "系统设计"]
    )
    task = repository.get_task(task_id)
    assert task["status"] == TaskStatus.QUEUED.value
    assert task["focus_points"] == ["Observation 反馈", "工程权衡"]
    assert task["question_types"] == ["概念辨析", "系统设计"]
    assert [stage["name"] for stage in task["stages"]] == [
        "research", "teaching", "interview", "supervisor"
    ]
    repository.update_stage(task_id, "research", StageStatus.COMPLETED.value, "done")
    repository.save_artifact(task_id, "research", {"sources": [{"citation_id": "S1"}]})
    assert repository.get_artifact(task_id, "research")["sources"][0]["citation_id"] == "S1"
    assert repository.update_task_metadata(task_id, title="ReAct 冲刺", archived=True)
    assert repository.get_task(task_id)["title"] == "ReAct 冲刺"
    assert repository.list_tasks("alice") == []
    assert repository.list_tasks("alice", include_archived=True)[0]["archived"] is True


def test_chat_session_crud(tmp_path):
    repository = StudyRepository(tmp_path / "sessions.db")
    task_id = repository.create_task("alice", "RAG", "理解概念", "入门", False)
    session_id = repository.create_chat_session(task_id, "向量检索答疑")
    repository.add_message(task_id, "user", "什么是召回率？", session_id=session_id)
    assert repository.list_messages(task_id, session_id=session_id)[0]["content"] == "什么是召回率？"
    assert repository.update_chat_session(task_id, session_id, "检索指标")
    assert repository.list_chat_sessions(task_id)[0]["title"] == "检索指标"
    assert repository.delete_chat_session(task_id, session_id)
    assert repository.list_messages(task_id, session_id=session_id) == []


def test_mastery_uses_assessment_evidence(tmp_path):
    repository = StudyRepository(tmp_path / "study.db")
    first = repository.update_mastery("alice", "ReAct", 60, ["Observation"])
    second = repository.update_mastery("alice", "ReAct", 90, [])
    assert first["mastery"] == 60
    assert second["mastery"] == 72
    assert second["evidence_count"] == 2


def test_restart_marks_unfinished_tasks(tmp_path):
    repository = StudyRepository(tmp_path / "study.db")
    task_id = repository.create_task("alice", "RAG", "理解概念", "入门", False)
    repository.update_task_status(task_id, TaskStatus.RUNNING.value)
    repository.update_stage(task_id, "research", StageStatus.RUNNING.value)
    assert repository.mark_unfinished_interrupted() == 1
    task = repository.get_task(task_id)
    assert task["status"] == TaskStatus.INTERRUPTED.value
    assert task["stages"][0]["status"] == StageStatus.INTERRUPTED.value
    assert repository.prepare_retry(task_id) == "research"
