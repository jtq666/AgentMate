"""学习报告页面。"""

import streamlit as st

from agentmate.frontend.common import api_get, api_post, load_tasks, render_study_steps, task_label

st.markdown('<div class="agentmate-kicker">第 4 步</div>', unsafe_allow_html=True)
st.title("学习报告")
st.caption("查看掌握度与薄弱点，并下载带引用的 Markdown 研学记录。")
render_study_steps(4)

mastery_data, _ = api_get("/api/mastery?student_id=default", show_error=False)
records = mastery_data.get("records", []) if mastery_data else []
if records:
    st.subheader("专题掌握度")
    with st.container(border=True):
        for record in sorted(records, key=lambda item: item["mastery"]):
            st.progress(
                record["mastery"] / 100,
                text=f"{record['topic']}　{record['mastery']:.1f}%",
            )
        st.caption("掌握度范围固定为 0–100%，仅由正式测评证据更新。")
    weakest = min(records, key=lambda item: item["mastery"])
    with st.container(border=True):
        st.subheader(f"下一步建议：复习 {weakest['topic']}")
        st.caption(f"当前掌握度 {weakest['mastery']:.1f}% · 系统将围绕本次测评证据生成复习任务")
        for point in weakest.get("weak_points", [])[:4]:
            st.markdown(f"- {point}")
        if st.button(
            "根据薄弱点创建复习任务",
            icon=":material/replay:",
            type="primary",
        ):
            result, _ = api_post("/api/study/tasks", {
                "topic": weakest["topic"],
                "goal": "准备面试",
                "level": "进阶",
                "include_papers": False,
                "student_id": "default",
                "focus_points": weakest.get("weak_points", [])[:5],
            })
            if result:
                st.session_state.study_task_id = result["task_id"]
                st.toast("复习任务已创建，内容会重点覆盖薄弱点。", icon="✅")
                st.switch_page("app_pages/workbench.py")
else:
    st.info("完成一次实践评测后，这里会自动出现掌握度和薄弱点。", icon=":material/insights:")

tasks = [task for task in load_tasks(completed_only=True)]
if not tasks:
    if st.button("先创建研学任务", icon=":material/arrow_back:"):
        st.switch_page("app_pages/workbench.py")
    st.stop()

st.divider()
st.subheader("历史研学报告")
ids = [task["id"] for task in tasks]
default_id = st.session_state.get("study_task_id")
if default_id not in ids:
    default_id = ids[0]
task_id = st.selectbox("选择报告", ids, index=ids.index(default_id),
                       format_func=lambda value: task_label(next(task for task in tasks if task["id"] == value)))
report, _ = api_get(f"/api/study/tasks/{task_id}/report")
if report:
    markdown = report["markdown"]
    st.download_button(
        "下载 Markdown 学习报告",
        data=markdown.encode("utf-8"),
        file_name=f"AgentMate_{report['topic']}.md",
        mime="text/markdown",
        type="primary",
        icon=":material/download:",
    )
    source_count = len(report.get("sources", []))
    assessment = report.get("assessment")
    first, second = st.columns(2)
    first.metric("可追溯来源", source_count)
    second.metric("最近测评", f"{assessment['total_score']:.1f}/100" if assessment else "尚未测评")
    with st.expander("预览完整报告", expanded=True):
        st.markdown(markdown)
