"""四个 Streamlit 页面共享的 API 与状态辅助。"""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

API_URL = os.getenv("AGENTMATE_API_URL", "http://127.0.0.1:8000").rstrip("/")
ACTIVE_STATUSES = {"queued", "running"}
STATUS_LABELS = {
    "queued": "排队中",
    "running": "执行中",
    "completed": "已完成",
    "failed": "失败",
    "interrupted": "已中断",
}
STAGE_LABELS = {
    "research": "查找可靠资料",
    "teaching": "生成学习讲解",
    "interview": "准备面试问题",
    "supervisor": "校验并汇总",
}


@st.cache_resource
def http_session() -> requests.Session:
    return requests.Session()


def api_request(method: str, path: str, *, timeout: int = 20,
                show_error: bool = True, **kwargs) -> tuple[Any | None, str | None]:
    try:
        response = http_session().request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
        if 200 <= response.status_code < 300:
            content_type = response.headers.get("content-type", "")
            return (response.json() if "json" in content_type else response.text), None
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        error = f"请求失败（{response.status_code}）：{detail}"
    except requests.RequestException as exc:
        error = f"无法连接后端：{exc}"
    if show_error:
        st.error(error)
    return None, error


def api_get(path: str, timeout: int = 20, show_error: bool = True):
    return api_request("GET", path, timeout=timeout, show_error=show_error)


def api_post(path: str, payload: dict, timeout: int = 30, show_error: bool = True):
    return api_request("POST", path, json=payload, timeout=timeout, show_error=show_error)


def api_patch(path: str, payload: dict, timeout: int = 20, show_error: bool = True):
    return api_request("PATCH", path, json=payload, timeout=timeout, show_error=show_error)


def api_delete(path: str, timeout: int = 20, show_error: bool = True):
    return api_request("DELETE", path, timeout=timeout, show_error=show_error)


def load_tasks(*, completed_only: bool = False, include_archived: bool = False) -> list[dict]:
    result, _ = api_get(
        f"/api/study/tasks?student_id=default&include_archived={str(include_archived).lower()}",
        show_error=False,
    )
    tasks = result.get("tasks", []) if result else []
    if completed_only:
        tasks = [task for task in tasks if task.get("status") == "completed"]
    return tasks


def task_label(task: dict) -> str:
    created = str(task.get("created_at", ""))[:16].replace("T", " ")
    return f"{task.get('title') or task.get('topic', '未命名')} · {created}"


def render_study_steps(current: int) -> None:
    """Render the user-facing study journey without exposing internal stages."""
    labels = ["准备资料", "专题学习", "模拟面试", "学习报告"]
    parts = []
    for index, label in enumerate(labels, 1):
        if index < current:
            parts.append(f":green-badge[✓ {label}]")
        elif index == current:
            parts.append(f":blue-badge[{index} {label}]")
        else:
            parts.append(f":gray-badge[{index} {label}]")
    st.markdown("　:material/arrow_forward:　".join(parts))
