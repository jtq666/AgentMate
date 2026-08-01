"""研学工作台。"""

import streamlit as st

from agentmate.frontend.common import (
    ACTIVE_STATUSES,
    STAGE_LABELS,
    STATUS_LABELS,
    api_delete,
    api_get,
    api_patch,
    api_post,
    load_tasks,
    render_study_steps,
    task_label,
)
from agentmate.study.topic_scope import PRESET_TOPICS

st.markdown('<div class="agentmate-kicker">从这里开始</div>', unsafe_allow_html=True)
st.title("研学工作台")
st.caption("选择一个 AI Agent 专题，系统会为你准备学习材料、面试题和可下载报告。")

PRESETS = [*PRESET_TOPICS, "自定义主题"]
st.session_state.setdefault("create_topic", "LLM Agent 基础")
st.session_state.setdefault("create_custom_topic", "")
st.session_state.setdefault("create_goal", "准备面试")
st.session_state.setdefault("create_level", "进阶")
st.session_state.setdefault("create_papers", False)
st.session_state.setdefault("create_question_types", ["概念辨析", "系统设计", "项目深挖"])
st.session_state.setdefault("show_archived_tasks", False)
tasks = load_tasks(include_archived=st.session_state.show_archived_tasks)
render_study_steps(2 if tasks else 1)

def apply_recommended_setup():
    st.session_state.create_topic = "ReAct"
    st.session_state.create_custom_topic = ""
    st.session_state.create_goal = "准备面试"
    st.session_state.create_level = "进阶"
    st.session_state.create_papers = False
    st.session_state.create_question_types = ["概念辨析", "系统设计", "项目深挖"]
    st.session_state.pop("topic_check_result", None)


def clear_topic_feedback():
    st.session_state.pop("topic_check_result", None)


if st.session_state.get("show_beginner_guide", True) and not tasks:
    with st.container(border=True):
        st.subheader("第一次使用？3 分钟了解流程")
        st.write("无需先上传资料。直接使用推荐配置创建任务，生成完成后阅读讲解并参加 5 题模拟面试。")
        steps = st.columns(4)
        for column, number, title, detail in zip(
            steps,
            ["1", "2", "3", "4"],
            ["创建专题", "阅读讲解", "完成评测", "下载报告"],
            ["选主题和目标", "等待后台生成", "回答 5 道题", "复习薄弱点"],
        ):
            with column:
                st.markdown(f"### {number}　{title}")
                st.caption(detail)
        st.button(
            "一键填入推荐配置",
            icon=":material/auto_awesome:",
            on_click=apply_recommended_setup,
            help="自动选择 ReAct、准备面试、进阶难度。",
        )
elif st.session_state.get("show_beginner_guide", True):
    with st.expander("第一次使用？查看四步流程", icon=":material/help:"):
        st.write("选择专题并生成内容 → 阅读课程并向导师提问 → 完成 5 题面试 → 下载学习报告。")
        st.caption("你已有历史任务，可直接从下方“继续学习”选择。")
        st.button(
            "一键填入推荐配置",
            icon=":material/auto_awesome:",
            on_click=apply_recommended_setup,
            key="recommended-existing",
        )

creation_area = (
    st.expander("创建另一个专题任务", expanded=False)
    if tasks
    else st.container(border=True)
)
with creation_area:
    st.subheader("1　创建研学任务")
    st.info(
        "当前仅支持 AI Agent 相关专题。内置专题可以直接使用；自定义专题会先检查范围和资料覆盖度。",
        icon=":material/info:",
    )
    topic_option = st.selectbox(
        "我想学习",
        PRESETS,
        key="create_topic",
        on_change=clear_topic_feedback,
    )
    with st.form("create_study_task", border=False):
        first, second = st.columns([2, 1])
        with first:
            if topic_option == "自定义主题":
                custom_topic = st.text_input(
                    "自定义 AI Agent 主题",
                    placeholder="例如：Agent 的长期记忆评估、MCP 工具生态",
                    help="只支持与 AI Agent 直接相关的主题，提交前会检查资料是否足够。",
                    key="create_custom_topic",
                )
            else:
                custom_topic = ""
                st.markdown(f":blue-badge[内置课程]　**{topic_option}**")
                st.caption("内置专题已经配有可追溯资料，可以直接生成。")
        with second:
            goal = st.selectbox("这次的目标", ["准备面试", "理解概念", "研究综述"], key="create_goal")
            level = st.selectbox("内容难度", ["入门", "进阶", "深入"], key="create_level")
            include_papers = st.checkbox(
                "额外补充论文（可选）",
                key="create_papers",
                help="会联网检索最多 3 篇论文，失败时仍会使用本地资料继续。",
            )
        question_types = st.pills(
            "模拟面试题型",
            ["综合问答", "概念辨析", "系统设计", "项目深挖", "论文追问"],
            selection_mode="multi",
            key="create_question_types",
            help="5 道题会在所选题型中递进生成。",
        )
        submitted = st.form_submit_button(
            "开始生成研学内容", icon=":material/play_arrow:", type="primary", width="stretch"
        )
        if submitted:
            topic = custom_topic.strip() if topic_option == "自定义主题" else topic_option
            if len(topic) < 2:
                st.error("请输入至少 2 个字符的主题。")
            elif not question_types:
                st.error("请至少选择一种模拟面试题型。")
            else:
                topic_check, _ = api_post("/api/study/topics/check", {"topic": topic})
                if topic_check:
                    st.session_state.topic_check_result = {**topic_check, "topic": topic}
                    if topic_check["status"] == "supported":
                        result, _ = api_post("/api/study/tasks", {
                            "topic": topic,
                            "goal": goal,
                            "level": level,
                            "include_papers": include_papers,
                            "student_id": "default",
                            "question_types": question_types,
                        })
                        if result:
                            st.session_state.study_task_id = result["task_id"]
                            st.session_state.pop("topic_check_result", None)
                            st.session_state.pop("pending_resource_topic", None)
                            st.toast("主题检查通过，正在后台生成内容。", icon="✅")
                            st.rerun()

    topic_feedback = st.session_state.get("topic_check_result")
    if topic_feedback:
        if topic_feedback["status"] == "out_of_scope":
            st.error(topic_feedback["message"], icon=":material/block:")
            suggestions = "　".join(
                f":gray-badge[{item}]" for item in topic_feedback.get("suggested_topics", [])
            )
            st.markdown(f"可以选择：{suggestions}")
        elif topic_feedback["status"] == "needs_sources":
            st.warning(topic_feedback["message"], icon=":material/library_add:")
            if st.button(
                "前往资料库上传相关资料",
                icon=":material/arrow_forward:",
                type="primary",
            ):
                st.session_state.pending_resource_topic = topic_feedback["topic"]
                st.session_state.topic_material_ready = ""
                st.switch_page("app_pages/resources.py")

if tasks:
    ids = [task["id"] for task in tasks]
    current_id = st.session_state.get("study_task_id")
    if current_id not in ids:
        current_id = ids[0]
    st.subheader("2　查看学习内容")
    select_col, manage_col = st.columns([5, 1], vertical_alignment="bottom")
    with select_col:
        selected_id = st.selectbox(
            "继续学习",
            ids,
            index=ids.index(current_id),
            format_func=lambda task_id: task_label(next(task for task in tasks if task["id"] == task_id)),
        )
    with manage_col:
        st.toggle("显示归档", key="show_archived_tasks")
    st.session_state.study_task_id = selected_id
    selected_task = next(task for task in tasks if task["id"] == selected_id)
    with st.popover("管理当前任务", icon=":material/settings:"):
        with st.form(f"rename-task-{selected_id}", border=False):
            new_title = st.text_input(
                "任务名称",
                value=selected_task.get("title") or selected_task["topic"],
            )
            if st.form_submit_button("保存名称", icon=":material/save:"):
                updated, _ = api_patch(
                    f"/api/study/tasks/{selected_id}", {"title": new_title.strip()}
                )
                if updated:
                    st.toast("任务名称已保存。", icon="✅")
                    st.rerun()
        archive_label = "恢复任务" if selected_task.get("archived") else "归档任务"
        if st.button(archive_label, icon=":material/archive:", key=f"archive-{selected_id}"):
            updated, _ = api_patch(
                f"/api/study/tasks/{selected_id}",
                {"archived": not selected_task.get("archived", False)},
            )
            if updated:
                st.session_state.pop("study_task_id", None)
                st.rerun()
        confirm_delete = st.checkbox(
            "我确认永久删除该任务及其评测和对话",
            key=f"confirm-delete-{selected_id}",
        )
        if st.button(
            "永久删除",
            icon=":material/delete:",
            disabled=not confirm_delete,
            key=f"delete-{selected_id}",
        ):
            deleted, _ = api_delete(f"/api/study/tasks/{selected_id}")
            if deleted:
                st.session_state.pop("study_task_id", None)
                st.rerun()
else:
    st.info("还没有任务。完成上方配置并点击“开始生成研学内容”即可。", icon=":material/lightbulb:")
    st.stop()


@st.dialog("AI 研学导师", width="medium", icon=":material/school:")
def show_tutor_answer(title: str, result: dict):
    st.markdown(f":blue-badge[{title}]")
    with st.container(height=440, border=False):
        st.markdown(result.get("answer", "导师暂时没有返回内容。"))
    if result.get("citations"):
        st.markdown(" ".join(f":gray-badge[{item}]" for item in result["citations"]))
    st.caption("引用均来自当前任务资料 · 关闭右上角 × 继续学习")


@st.fragment(run_every="2s")
def render_task(task_id: str):
    task, _ = api_get(f"/api/study/tasks/{task_id}", show_error=False)
    if not task:
        st.error("任务读取失败，请检查后端服务。")
        return
    status = task["status"]
    sessions_result, _ = api_get(
        f"/api/study/tasks/{task_id}/chat/sessions", show_error=False
    )
    chat_sessions = sessions_result.get("sessions", []) if sessions_result else []
    session_state_key = f"chat-session-{task_id}"
    session_ids = [session["id"] for session in chat_sessions]
    if session_ids and st.session_state.get(session_state_key) not in session_ids:
        st.session_state[session_state_key] = session_ids[0]
    active_session_id = st.session_state.get(session_state_key)

    def send_tutor_question(message: str) -> dict | None:
        payload = {"message": message}
        if active_session_id:
            payload["session_id"] = active_session_id
        with st.spinner("研学导师正在结合本专题资料回答……"):
            result, _ = api_post(
                f"/api/study/tasks/{task_id}/chat",
                payload,
                timeout=100,
            )
        if result:
            st.toast("研学导师已回答。", icon="✅")
        return result

    completed_count = sum(stage["status"] == "completed" for stage in task["stages"])
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader(task["topic"])
        st.badge(
            STATUS_LABELS.get(status, status),
            color="green" if status == "completed" else "blue",
        )
    st.markdown(
        f":blue-badge[{task.get('goal', '研学')}]　"
        f":gray-badge[{task.get('level', '进阶')}]　"
        f":gray-badge[{'包含论文' if task.get('include_papers') else '本地资料'}]"
    )
    if status != "completed":
        st.progress(completed_count / 4, text=f"内容准备进度 {completed_count}/4")

    if status in {"failed", "interrupted"}:
        st.error(task.get("error") or "任务未完成")
        if st.button("从失败阶段重试", key=f"retry-{task_id}"):
            result, _ = api_post(f"/api/study/tasks/{task_id}/retry", {})
            if result:
                st.success(f"已从 {result['retry_from']} 阶段重新排队。")
                st.rerun(scope="fragment")
    elif status in ACTIVE_STATUSES:
        st.info("正在后台准备内容，本页会自动更新。你可以稍候，也可以先浏览资料库。")

    teaching = task["artifacts"].get("teaching")
    if not teaching:
        stage_columns = st.columns(4)
        for column, stage in zip(stage_columns, task["stages"]):
            with column:
                st.markdown(f"**{STAGE_LABELS[stage['name']]}**")
                st.caption(stage.get("summary") or STATUS_LABELS.get(stage["status"], stage["status"]))
        return

    tab_names = ["课程章节", "常见误区", "导师答疑", "引用资料"]
    if st.session_state.get("demo_mode", False):
        tab_names.append("技术演示")
    tabs = st.tabs(
        tab_names,
        key=f"study-tabs-{task_id}",
    )
    course_tab, mistakes_tab, tutor_tab, sources_tab = tabs[:4]
    demo_tab = tabs[4] if len(tabs) > 4 else None

    with course_tab:
        with st.expander("学习目标与整体认识", icon=":material/map:"):
            for index, item in enumerate(teaching.get("learning_map", []), 1):
                st.markdown(f"**{index}.** {item}")
            st.markdown(teaching.get("overview", ""))

        concepts = teaching.get("concepts", [])
        if concepts:
            chapter_key = f"chapter-{task_id}"
            st.session_state.setdefault(chapter_key, 0)
            chapter_index = min(st.session_state[chapter_key], len(concepts) - 1)

            concept = concepts[chapter_index]
            title = concept.get("title", "核心概念")
            st.progress(
                (chapter_index + 1) / len(concepts),
                text=f"第 {chapter_index + 1} / {len(concepts)} 节",
            )
            with st.container(border=True):
                st.header(title)
                st.markdown(concept.get("explanation", ""))
                if concept.get("example"):
                    st.markdown("#### 具体例子")
                    st.info(concept["example"], icon=":material/lightbulb:")
                if concept.get("citations"):
                    st.caption("本节依据：" + " ".join(concept["citations"]))
                with st.container(horizontal=True):
                    if st.button(
                        "没听懂，换个例子",
                        icon=":material/lightbulb:",
                        key=f"example-{task_id}-{chapter_index}",
                    ):
                        result = send_tutor_question(
                            f"我没有完全理解“{title}”。请换一个更贴近本科生的例子解释，"
                            "分步骤说明，并保留资料引用。"
                        )
                        if result:
                            show_tutor_answer("导师换了一个例子", result)
                    if st.button(
                        "生成面试表达",
                        icon=":material/record_voice_over:",
                        key=f"interview-help-{task_id}-{chapter_index}",
                    ):
                        result = send_tutor_question(
                            f"请把“{title}”整理成一段适合保研面试的 1 分钟回答，"
                            "包含定义、机制、例子和工程权衡，并保留资料引用。"
                        )
                        if result:
                            show_tutor_answer("1 分钟面试表达", result)

            with st.container(horizontal=True, horizontal_alignment="distribute"):
                if st.button(
                    "上一节",
                    icon=":material/arrow_back:",
                    disabled=chapter_index == 0,
                    key=f"previous-chapter-{task_id}",
                ):
                    st.session_state[chapter_key] = chapter_index - 1
                    st.rerun(scope="fragment")
                if chapter_index < len(concepts) - 1:
                    if st.button(
                        "下一节",
                        icon=":material/arrow_forward:",
                        type="primary",
                        key=f"next-chapter-{task_id}",
                    ):
                        st.session_state[chapter_key] = chapter_index + 1
                        st.rerun(scope="fragment")
                elif task["artifacts"].get("interview"):
                    if st.button(
                        "完成学习，进入模拟面试",
                        icon=":material/arrow_forward:",
                        type="primary",
                        key=f"assessment-{task_id}",
                    ):
                        st.switch_page("app_pages/assessment.py")
        if teaching.get("summary"):
            with st.expander("本专题总结", icon=":material/checklist:"):
                st.markdown(teaching["summary"])

    with mistakes_tab:
        st.subheader("面试中容易答错的地方")
        st.caption("把这些误区当作答题前的检查清单。")
        for index, item in enumerate(teaching.get("misconceptions", []), 1):
            st.warning(f"**误区 {index}**　{item}", icon=":material/warning:")

    with tutor_tab:
        st.subheader("向 AI 研学导师提问")
        st.caption("导师只使用当前专题资料回答，并保留引用。")
        session_col, manage_session_col = st.columns([5, 1], vertical_alignment="bottom")
        with session_col:
            if chat_sessions:
                active_session_id = st.selectbox(
                    "当前会话",
                    session_ids,
                    key=session_state_key,
                    format_func=lambda value: next(
                        session["title"] for session in chat_sessions if session["id"] == value
                    ),
                )
        with manage_session_col:
            with st.popover("管理会话", icon=":material/forum:"):
                with st.form(f"new-session-{task_id}", border=False):
                    new_session_title = st.text_input(
                        "新会话名称", placeholder="例如：工具选择答疑"
                    )
                    if st.form_submit_button("创建会话", icon=":material/add:"):
                        created, _ = api_post(
                            f"/api/study/tasks/{task_id}/chat/sessions",
                            {"title": new_session_title.strip() or "新对话"},
                        )
                        if created:
                            st.session_state[session_state_key] = created["session_id"]
                            st.rerun(scope="fragment")
                if active_session_id:
                    current_title = next(
                        (
                            session["title"]
                            for session in chat_sessions
                            if session["id"] == active_session_id
                        ),
                        "当前会话",
                    )
                    with st.form(f"rename-session-{active_session_id}", border=False):
                        renamed_title = st.text_input("重命名", value=current_title)
                        if st.form_submit_button("保存会话名称"):
                            updated, _ = api_patch(
                                f"/api/study/tasks/{task_id}/chat/sessions/{active_session_id}",
                                {"title": renamed_title.strip()},
                            )
                            if updated:
                                st.rerun(scope="fragment")
                    confirm_session_delete = st.checkbox(
                        "确认删除当前会话",
                        key=f"confirm-session-delete-{active_session_id}",
                    )
                    if st.button(
                        "删除会话",
                        icon=":material/delete:",
                        disabled=not confirm_session_delete,
                        key=f"delete-session-{active_session_id}",
                    ):
                        deleted, _ = api_delete(
                            f"/api/study/tasks/{task_id}/chat/sessions/{active_session_id}"
                        )
                        if deleted:
                            st.session_state.pop(session_state_key, None)
                            st.rerun(scope="fragment")

        messages_result, _ = (
            api_get(
                f"/api/study/tasks/{task_id}/chat/sessions/{active_session_id}/messages",
                show_error=False,
            )
            if active_session_id
            else (None, None)
        )
        recent_messages = (
            messages_result.get("messages", [])[-8:]
            if messages_result
            else task.get("messages", [])[-8:]
        )
        for message in recent_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        with st.form(f"tutor-{task_id}", border=False):
            tutor_question = st.text_input(
                "你的问题",
                key=f"tutor-question-{task_id}",
                placeholder=f"例如：请用更简单的例子解释 {task['topic']}",
                label_visibility="collapsed",
            )
            ask_tutor = st.form_submit_button(
                "向研学导师提问",
                icon=":material/forum:",
                type="primary",
            )
        if ask_tutor:
            if not tutor_question.strip():
                st.warning("请先输入你没理解的问题。")
            else:
                result = send_tutor_question(tutor_question)
                if result:
                    show_tutor_answer("研学导师回答", result)

    with sources_tab:
        st.subheader("本任务引用资料")
        st.caption("课程中的 [S1]、[S2] 等编号都可以在这里追溯。")
        if task.get("sources"):
            for source in task["sources"]:
                with st.expander(f"[{source['citation_id']}] {source['title']}"):
                    st.caption(f"来源类型：{source['source_type']}")
                    st.write(source.get("excerpt", "")[:500])
                    if source.get("url"):
                        st.link_button("打开来源", source["url"])
        else:
            st.info("当前任务没有可展示的引用资料。")

    if demo_tab is not None:
        with demo_tab:
            st.subheader("多 Agent 执行过程")
            st.caption("本区域用于项目答辩，不影响普通学习流程。")
            stage_columns = st.columns(4)
            for column, stage in zip(stage_columns, task["stages"]):
                with column:
                    st.markdown(f"**{STAGE_LABELS[stage['name']]}**")
                    st.caption(
                        stage.get("summary")
                        or STATUS_LABELS.get(stage["status"], stage["status"])
                    )
            with st.expander("查看工程实现证据", icon=":material/account_tree:"):
                st.markdown(
                    "ChromaDB + BM25 + RRF 混合检索；Pydantic 结构化状态；"
                    "SQLite WAL 持久化；引用校验；单并发后台队列与失败阶段重试。"
                )
                for stage in task["stages"]:
                    duration = (
                        f"{stage['duration_ms']} ms"
                        if stage.get("duration_ms") is not None
                        else "—"
                    )
                    st.code(
                        f"{stage['name']}: {stage['status']} | "
                        f"attempts={stage['attempts']} | duration={duration}"
                    )
                    if stage.get("error"):
                        st.error(stage["error"])

render_task(selected_id)
