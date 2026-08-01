"""SQLite 业务数据层。

每次操作使用独立连接，便于 FastAPI 请求与后台工作线程安全共享。数据库
启用 WAL 和外键约束；JSON 只用于结构化产物，不替代可查询的业务字段。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentmate.study.models import StageStatus, TaskStatus

STAGE_ORDER = ("research", "teaching", "interview", "supervisor")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class StudyRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS study_tasks (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            goal TEXT NOT NULL,
            level TEXT NOT NULL,
            include_papers INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_student_created
            ON study_tasks(student_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON study_tasks(status);

        CREATE TABLE IF NOT EXISTS task_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES study_tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            position INTEGER NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(task_id, name)
        );

        CREATE TABLE IF NOT EXISTS task_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES study_tasks(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            content_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(task_id, kind)
        );

        CREATE TABLE IF NOT EXISTS task_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES study_tasks(id) ON DELETE CASCADE,
            citation_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            source_type TEXT NOT NULL,
            excerpt TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            UNIQUE(task_id, citation_id)
        );

        CREATE TABLE IF NOT EXISTS assessment_attempts (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES study_tasks(id) ON DELETE CASCADE,
            student_id TEXT NOT NULL,
            status TEXT NOT NULL,
            answers_json TEXT NOT NULL,
            result_json TEXT,
            total_score REAL,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_assessments_task
            ON assessment_attempts(task_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS mastery_records (
            student_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            mastery REAL NOT NULL,
            weak_points_json TEXT NOT NULL DEFAULT '[]',
            evidence_count INTEGER NOT NULL DEFAULT 0,
            last_assessed_at TEXT NOT NULL,
            PRIMARY KEY(student_id, topic)
        );

        CREATE TABLE IF NOT EXISTS task_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES study_tasks(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            citations_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES study_tasks(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_task
            ON chat_sessions(task_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS migration_log (
            name TEXT PRIMARY KEY,
            details_json TEXT NOT NULL DEFAULT '{}',
            completed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS legacy_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            source_path TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            archived_at TEXT NOT NULL
        );
        """
        with self._write_lock, self._connect() as conn:
            conn.executescript(schema)
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(study_tasks)").fetchall()
            }
            if "focus_points_json" not in columns:
                conn.execute(
                    "ALTER TABLE study_tasks ADD COLUMN focus_points_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "question_types_json" not in columns:
                conn.execute(
                    "ALTER TABLE study_tasks ADD COLUMN question_types_json TEXT NOT NULL "
                    "DEFAULT '[\"综合问答\"]'"
                )
            if "title" not in columns:
                conn.execute("ALTER TABLE study_tasks ADD COLUMN title TEXT NOT NULL DEFAULT ''")
            if "archived" not in columns:
                conn.execute(
                    "ALTER TABLE study_tasks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                )
            message_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(task_messages)").fetchall()
            }
            if "session_id" not in message_columns:
                conn.execute("ALTER TABLE task_messages ADD COLUMN session_id TEXT")
            legacy_tasks = conn.execute(
                "SELECT DISTINCT task_id FROM task_messages WHERE session_id IS NULL"
            ).fetchall()
            for row in legacy_tasks:
                session_id = uuid.uuid4().hex
                now = utc_now()
                conn.execute(
                    "INSERT INTO chat_sessions(id,task_id,title,created_at,updated_at) "
                    "VALUES (?,?,?,?,?)",
                    (session_id, row["task_id"], "历史对话", now, now),
                )
                conn.execute(
                    "UPDATE task_messages SET session_id=? WHERE task_id=? AND session_id IS NULL",
                    (session_id, row["task_id"]),
                )

    def create_task(self, student_id: str, topic: str, goal: str, level: str,
                    include_papers: bool, focus_points: list[str] | None = None,
                    question_types: list[str] | None = None) -> str:
        task_id = uuid.uuid4().hex
        now = utc_now()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO study_tasks("
                "id,student_id,topic,goal,level,include_papers,status,error,"
                "created_at,updated_at,started_at,completed_at,focus_points_json"
                ",question_types_json) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?)",
                (task_id, student_id, topic, goal, level, int(include_papers),
                 TaskStatus.QUEUED.value, now, now, _json(focus_points or []),
                 _json(question_types or ["综合问答"])),
            )
            conn.executemany(
                "INSERT INTO task_stages(task_id,name,position,status) VALUES (?,?,?,?)",
                [(task_id, name, index, StageStatus.QUEUED.value)
                 for index, name in enumerate(STAGE_ORDER)],
            )
        return task_id

    def get_task(self, task_id: str, include_internal: bool = False) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM study_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            stages = [dict(item) for item in conn.execute(
                "SELECT name,status,summary,error,attempts,duration_ms,metrics_json,started_at,completed_at "
                "FROM task_stages WHERE task_id=? ORDER BY position", (task_id,)
            ).fetchall()]
            artifacts = {
                item["kind"]: _loads(item["content_json"], {})
                for item in conn.execute(
                    "SELECT kind,content_json FROM task_artifacts WHERE task_id=?", (task_id,)
                ).fetchall()
            }
            sources = [dict(item) for item in conn.execute(
                "SELECT citation_id,document_id,title,source,source_type,excerpt,url "
                "FROM task_sources WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()]
        for stage in stages:
            stage["metrics"] = _loads(stage.pop("metrics_json"), {}) if include_internal else {}
        if not include_internal and "interview" in artifacts:
            public_questions = []
            for question in artifacts["interview"].get("questions", []):
                public_questions.append({key: value for key, value in question.items()
                                         if key not in {"rubric", "required_points", "follow_up"}})
            artifacts["interview"] = {"questions": public_questions}
        result = dict(row)
        result["include_papers"] = bool(result["include_papers"])
        result["focus_points"] = _loads(result.pop("focus_points_json", "[]"), [])
        result["question_types"] = _loads(
            result.pop("question_types_json", None), ["综合问答"]
        )
        result["title"] = result.get("title") or result["topic"]
        result["archived"] = bool(result.get("archived", 0))
        result["stages"] = stages
        result["artifacts"] = artifacts
        result["sources"] = sources
        return result

    def list_tasks(self, student_id: str = "default", status: str | None = None,
                   topic: str | None = None, limit: int = 50,
                   include_archived: bool = False) -> list[dict]:
        clauses, params = ["student_id=?"], [student_id]
        if not include_archived:
            clauses.append("archived=0")
        if status:
            clauses.append("status=?")
            params.append(status)
        if topic:
            clauses.append("topic LIKE ?")
            params.append(f"%{topic}%")
        params.append(max(1, min(limit, 200)))
        query = f"SELECT * FROM study_tasks WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?"
        with self._connect() as conn:
            results = []
            for row in conn.execute(query, params).fetchall():
                item = dict(row)
                item["include_papers"] = bool(item["include_papers"])
                item["focus_points"] = _loads(item.pop("focus_points_json", "[]"), [])
                item["question_types"] = _loads(
                    item.pop("question_types_json", None), ["综合问答"]
                )
                item["title"] = item.get("title") or item["topic"]
                item["archived"] = bool(item.get("archived", 0))
                results.append(item)
            return results

    def update_task_metadata(
        self, task_id: str, *, title: str | None = None, archived: bool | None = None
    ) -> bool:
        assignments, params = [], []
        if title is not None:
            assignments.append("title=?")
            params.append(title.strip())
        if archived is not None:
            assignments.append("archived=?")
            params.append(int(archived))
        if not assignments:
            return self.get_task(task_id) is not None
        assignments.append("updated_at=?")
        params.append(utc_now())
        params.append(task_id)
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE study_tasks SET {', '.join(assignments)} WHERE id=?", params
            )
            return cursor.rowcount > 0

    def delete_task(self, task_id: str) -> bool:
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM study_tasks WHERE id=?", (task_id,))
            return cursor.rowcount > 0

    def update_task_status(self, task_id: str, status: str, error: str | None = None) -> None:
        now = utc_now()
        fields = ["status=?", "error=?", "updated_at=?"]
        params: list[Any] = [status, error, now]
        if status == TaskStatus.RUNNING.value:
            fields.append("started_at=COALESCE(started_at, ?)")
            params.append(now)
        if status == TaskStatus.COMPLETED.value:
            fields.append("completed_at=?")
            params.append(now)
        params.append(task_id)
        with self._write_lock, self._connect() as conn:
            conn.execute(f"UPDATE study_tasks SET {', '.join(fields)} WHERE id=?", params)

    def update_stage(self, task_id: str, name: str, status: str, summary: str = "",
                     error: str | None = None, duration_ms: int | None = None,
                     metrics: dict | None = None, increment_attempt: bool = False) -> None:
        now = utc_now()
        assignments = ["status=?", "summary=?", "error=?", "duration_ms=?", "metrics_json=?"]
        params: list[Any] = [status, summary, error, duration_ms, _json(metrics or {})]
        if increment_attempt:
            assignments.append("attempts=attempts+1")
        if status == StageStatus.RUNNING.value:
            assignments.append("started_at=?")
            params.append(now)
        if status in {StageStatus.COMPLETED.value, StageStatus.FAILED.value}:
            assignments.append("completed_at=?")
            params.append(now)
        params.extend([task_id, name])
        with self._write_lock, self._connect() as conn:
            conn.execute(
                f"UPDATE task_stages SET {', '.join(assignments)} WHERE task_id=? AND name=?", params
            )

    def save_artifact(self, task_id: str, kind: str, content: Any) -> None:
        if hasattr(content, "model_dump"):
            content = content.model_dump(mode="json")
        now = utc_now()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO task_artifacts(task_id,kind,content_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(task_id,kind) DO UPDATE SET "
                "content_json=excluded.content_json, updated_at=excluded.updated_at",
                (task_id, kind, _json(content), now, now),
            )

    def get_artifact(self, task_id: str, kind: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_json FROM task_artifacts WHERE task_id=? AND kind=?", (task_id, kind)
            ).fetchone()
        return _loads(row[0], None) if row else None

    def replace_sources(self, task_id: str, sources: list[dict]) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute("DELETE FROM task_sources WHERE task_id=?", (task_id,))
            conn.executemany(
                "INSERT INTO task_sources(task_id,citation_id,document_id,title,source,source_type,excerpt,url) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [(task_id, item["citation_id"], item["document_id"], item["title"],
                  item["source"], item.get("source_type", "course"), item.get("excerpt", ""),
                  item.get("url", "")) for item in sources],
            )

    def create_assessment(self, task_id: str, student_id: str, answers: list[str]) -> str:
        assessment_id = uuid.uuid4().hex
        now = utc_now()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO assessment_attempts(id,task_id,student_id,status,answers_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (assessment_id, task_id, student_id, TaskStatus.QUEUED.value,
                 _json(answers), now, now),
            )
        return assessment_id

    def get_assessment(self, assessment_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM assessment_attempts WHERE id=?", (assessment_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["answers"] = _loads(result.pop("answers_json"), [])
        result["result"] = _loads(result.pop("result_json"), None)
        return result

    def latest_assessment_for_task(self, task_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM assessment_attempts WHERE task_id=? AND status=? "
                "ORDER BY completed_at DESC LIMIT 1",
                (task_id, TaskStatus.COMPLETED.value),
            ).fetchone()
        return self.get_assessment(row["id"]) if row else None

    def update_assessment(self, assessment_id: str, status: str, result: Any = None,
                          total_score: float | None = None, error: str | None = None) -> None:
        now = utc_now()
        result_data = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        completed = now if status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value} else None
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "UPDATE assessment_attempts SET status=?,result_json=?,total_score=?,error=?,updated_at=?,"
                "completed_at=COALESCE(?,completed_at) WHERE id=?",
                (status, _json(result_data) if result_data is not None else None,
                 total_score, error, now, completed, assessment_id),
            )

    def update_mastery(self, student_id: str, topic: str, score: float,
                       weak_points: list[str]) -> dict:
        now = utc_now()
        with self._write_lock, self._connect() as conn:
            old = conn.execute(
                "SELECT mastery,evidence_count FROM mastery_records WHERE student_id=? AND topic=?",
                (student_id, topic),
            ).fetchone()
            count = int(old["evidence_count"]) + 1 if old else 1
            mastery = round((float(old["mastery"]) * 0.6 + score * 0.4) if old else score, 2)
            conn.execute(
                "INSERT INTO mastery_records(student_id,topic,mastery,weak_points_json,evidence_count,last_assessed_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(student_id,topic) DO UPDATE SET "
                "mastery=excluded.mastery,weak_points_json=excluded.weak_points_json,"
                "evidence_count=excluded.evidence_count,last_assessed_at=excluded.last_assessed_at",
                (student_id, topic, mastery, _json(weak_points), count, now),
            )
        return {"student_id": student_id, "topic": topic, "mastery": mastery,
                "weak_points": weak_points, "evidence_count": count, "last_assessed_at": now}

    def list_mastery(self, student_id: str = "default") -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mastery_records WHERE student_id=? ORDER BY last_assessed_at DESC",
                (student_id,),
            ).fetchall()
        return [dict(row) | {"weak_points": _loads(row["weak_points_json"], [])}
                for row in rows]

    def create_chat_session(self, task_id: str, title: str = "新对话") -> str:
        session_id = uuid.uuid4().hex
        now = utc_now()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_sessions(id,task_id,title,created_at,updated_at) "
                "VALUES (?,?,?,?,?)",
                (session_id, task_id, title.strip() or "新对话", now, now),
            )
        return session_id

    def list_chat_sessions(self, task_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,title,created_at,updated_at FROM chat_sessions "
                "WHERE task_id=? ORDER BY updated_at DESC",
                (task_id,),
            ).fetchall()
        if not rows:
            self.create_chat_session(task_id, "默认对话")
            return self.list_chat_sessions(task_id)
        return [dict(row) for row in rows]

    def update_chat_session(self, task_id: str, session_id: str, title: str) -> bool:
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE chat_sessions SET title=?,updated_at=? WHERE id=? AND task_id=?",
                (title.strip() or "未命名对话", utc_now(), session_id, task_id),
            )
            return cursor.rowcount > 0

    def delete_chat_session(self, task_id: str, session_id: str) -> bool:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM task_messages WHERE task_id=? AND session_id=?",
                (task_id, session_id),
            )
            cursor = conn.execute(
                "DELETE FROM chat_sessions WHERE id=? AND task_id=?", (session_id, task_id)
            )
            return cursor.rowcount > 0

    def chat_session_exists(self, task_id: str, session_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM chat_sessions WHERE id=? AND task_id=?",
                (session_id, task_id),
            ).fetchone() is not None

    def add_message(self, task_id: str, role: str, content: str,
                    citations: list[str] | None = None,
                    session_id: str | None = None) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO task_messages("
                "task_id,role,content,citations_json,created_at,session_id"
                ") VALUES (?,?,?,?,?,?)",
                (task_id, role, content, _json(citations or []), utc_now(), session_id),
            )
            if session_id:
                conn.execute(
                    "UPDATE chat_sessions SET updated_at=? WHERE id=?",
                    (utc_now(), session_id),
                )

    def list_messages(
        self, task_id: str, limit: int = 30, session_id: str | None = None
    ) -> list[dict]:
        session_clause = " AND session_id=?" if session_id else ""
        params: list[Any] = [task_id]
        if session_id:
            params.append(session_id)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role,content,citations_json,created_at FROM task_messages "
                f"WHERE task_id=?{session_clause} ORDER BY id DESC LIMIT ?", params,
            ).fetchall()
        return [dict(row) | {"citations": _loads(row["citations_json"], [])}
                for row in reversed(rows)]

    def mark_unfinished_interrupted(self) -> int:
        now = utc_now()
        with self._write_lock, self._connect() as conn:
            task_cursor = conn.execute(
                "UPDATE study_tasks SET status=?,error=?,updated_at=? WHERE status IN (?,?)",
                (TaskStatus.INTERRUPTED.value, "服务重启导致任务中断，可点击重试继续。", now,
                 TaskStatus.QUEUED.value, TaskStatus.RUNNING.value),
            )
            conn.execute(
                "UPDATE task_stages SET status=?,error=? WHERE status=?",
                (StageStatus.INTERRUPTED.value, "服务重启导致阶段中断。", StageStatus.RUNNING.value),
            )
            conn.execute(
                "UPDATE assessment_attempts SET status=?,error=?,updated_at=? WHERE status IN (?,?)",
                (TaskStatus.INTERRUPTED.value, "服务重启导致评测中断，请重新提交。", now,
                 TaskStatus.QUEUED.value, TaskStatus.RUNNING.value),
            )
            return task_cursor.rowcount

    def prepare_retry(self, task_id: str) -> str | None:
        task = self.get_task(task_id, include_internal=True)
        if not task or task["status"] not in {TaskStatus.FAILED.value, TaskStatus.INTERRUPTED.value}:
            return None
        failed_position = None
        for index, stage in enumerate(task["stages"]):
            if stage["status"] in {StageStatus.FAILED.value, StageStatus.INTERRUPTED.value}:
                failed_position = index
                break
        if failed_position is None:
            failed_position = next((i for i, s in enumerate(task["stages"])
                                    if s["status"] != StageStatus.COMPLETED.value), 0)
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "UPDATE study_tasks SET status=?,error=NULL,updated_at=?,completed_at=NULL WHERE id=?",
                (TaskStatus.QUEUED.value, utc_now(), task_id),
            )
            conn.execute(
                "UPDATE task_stages SET status=?,error=NULL,summary='',duration_ms=NULL,completed_at=NULL "
                "WHERE task_id=? AND position>=?",
                (StageStatus.QUEUED.value, task_id, failed_position),
            )
        return task["stages"][failed_position]["name"]

    def migration_done(self, name: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM migration_log WHERE name=?", (name,)).fetchone() is not None

    def record_migration(self, name: str, details: dict) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO migration_log(name,details_json,completed_at) VALUES (?,?,?)",
                (name, _json(details), utc_now()),
            )

    def archive_legacy(self, kind: str, source_path: str, payload: Any) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO legacy_records(kind,source_path,payload_json,archived_at) VALUES (?,?,?,?)",
                (kind, source_path, _json(payload), utc_now()),
            )
