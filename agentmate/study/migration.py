"""旧数据的一次性、非破坏迁移。"""

from __future__ import annotations

import json
from pathlib import Path

from agentmate.study.repository import StudyRepository

MIGRATION_NAME = "legacy_json_archive_v1"


def migrate_legacy_data(repository: StudyRepository, data_dir: str | Path) -> dict:
    """归档旧聊天和手动计划原文，不把手动状态转换为掌握度。"""
    if repository.migration_done(MIGRATION_NAME):
        return {"status": "already_completed"}
    root = Path(data_dir)
    targets = [
        ("chat_history", root / "chat_history.json"),
        ("interview_history", root / "interview_history.json"),
    ]
    targets.extend(("manual_learning_plan", path) for path in (root / "memory").glob("*/learning_plan.json"))
    imported = 0
    skipped = []
    for kind, path in targets:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            repository.archive_legacy(kind, str(path), payload)
            imported += 1
        except Exception as exc:
            skipped.append({"path": str(path), "error": str(exc)})
    details = {"archived_files": imported, "skipped": skipped,
               "mastery_imported": False, "original_files_preserved": True}
    repository.record_migration(MIGRATION_NAME, details)
    return details
