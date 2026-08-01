"""实践评测页面。"""

import streamlit as st

from agentmate.frontend.common import (
    STATUS_LABELS,
    api_get,
    api_post,
    load_tasks,
    render_study_steps,
    task_label,
)

st.markdown('<div class="agentmate-kicker">第 3 步</div>', unsafe_allow_html=True)
st.title("实践评测")
st.caption("像一次小型面试一样完成 5 道题，提交后才能看到评分和改进建议。")
render_study_steps(3)

if st.session_state.get("show_beginner_guide", True):
    st.info(
        "建议先读完工作台中的学习讲解再作答。每题可按“定义—机制—案例—权衡”组织，预计 15–25 分钟。",
        icon=":material/tips_and_updates:",
    )

tasks = load_tasks(completed_only=True)
tasks = [task for task in tasks if task.get("status") == "completed"]
if not tasks:
    st.info("还没有已完成的研学任务。请先在研学工作台生成学习内容。")
    if st.button("返回研学工作台", icon=":material/arrow_back:"):
        st.switch_page("app_pages/workbench.py")
    st.stop()

ids = [task["id"] for task in tasks]
default_id = st.session_state.get("study_task_id")
if default_id not in ids:
    default_id = ids[0]
task_id = st.selectbox("选择研学任务", ids, index=ids.index(default_id),
                       format_func=lambda value: task_label(next(task for task in tasks if task["id"] == value)))
st.session_state.study_task_id = task_id
task, _ = api_get(f"/api/study/tasks/{task_id}")
questions = (task or {}).get("artifacts", {}).get("interview", {}).get("questions", [])
if len(questions) != 5:
    st.warning("题目尚未准备完成。")
    st.stop()

st.subheader(f"{task['topic']} · 5 题模拟面试")
st.caption("每次专注一题；答案会自动保留在当前会话，最后统一提交评分。")
page_key = f"assessment-page-{task_id}"
st.session_state.setdefault(page_key, 0)
question_index = min(st.session_state[page_key], len(questions) - 1)
question = questions[question_index]
answer_keys = [f"answer-{task_id}-{item['id']}" for item in questions]
for key in answer_keys:
    st.session_state.setdefault(key, "")

st.progress((question_index + 1) / len(questions), text=f"第 {question_index + 1} / {len(questions)} 题")
with st.container(border=True):
    st.markdown(
        f":blue-badge[难度 {question['difficulty']}/5]　"
        f":gray-badge[{question['id'].upper()}]　"
        f":violet-badge[{question.get('question_type', '综合问答')}]"
    )
    st.subheader(question["question"])
    st.text_area(
        "你的回答",
        key=answer_keys[question_index],
        height=160,
        placeholder="建议按“定义—机制—案例—权衡”组织回答。",
    )
    st.caption("草稿会在前后切换题目时保留，但关闭浏览器前请完成提交。")

with st.container(horizontal=True, horizontal_alignment="distribute"):
    if st.button(
        "上一题",
        icon=":material/arrow_back:",
        disabled=question_index == 0,
        key=f"previous-{task_id}",
    ):
        st.session_state[page_key] = question_index - 1
        st.rerun()
    if question_index < len(questions) - 1:
        if st.button(
            "下一题",
            icon=":material/arrow_forward:",
            type="primary",
            key=f"next-{task_id}",
        ):
            st.session_state[page_key] = question_index + 1
            st.rerun()
    else:
        if st.button(
            "提交 5 题并开始评分",
            icon=":material/send:",
            type="primary",
            key=f"submit-{task_id}",
        ):
            answers = [st.session_state[key] for key in answer_keys]
            missing = [str(index) for index, answer in enumerate(answers, 1) if not answer.strip()]
            if missing:
                st.error(f"第 {'、'.join(missing)} 题还没有回答，请补充后再提交。")
            else:
                result, _ = api_post(f"/api/study/tasks/{task_id}/assessments", {
                    "answers": answers, "student_id": "default",
                })
                if result:
                    st.session_state.assessment_id = result["assessment_id"]
                    st.toast("答案已提交，正在后台评分。", icon="✅")


@st.fragment(run_every="2s")
def render_assessment_result():
    assessment_id = st.session_state.get("assessment_id")
    if not assessment_id:
        return
    assessment, _ = api_get(f"/api/assessments/{assessment_id}", show_error=False)
    if not assessment:
        return
    status = assessment["status"]
    if status in {"queued", "running"}:
        st.info(f"评测状态：{STATUS_LABELS[status]}。完成后会自动更新此处。")
        return
    if status in {"failed", "interrupted"}:
        st.error(assessment.get("error") or "评测失败，请重新提交。")
        return
    result = assessment.get("result") or {}
    score = result.get("total_score", 0)
    mastery = result.get("mastery", {})
    first, second = st.columns(2)
    first.metric("本次得分", f"{score:.1f}/100")
    second.metric("专题掌握度", f"{mastery.get('mastery', 0):.1f}%")
    st.markdown(result.get("summary", ""))
    for item in result.get("items", []):
        with st.expander(f"{item['question_id'].upper()} · {item['score']:.1f}/20"):
            st.write(item.get("feedback", ""))
            if item.get("hits"):
                st.success("命中：" + "、".join(item["hits"]))
            if item.get("misses"):
                st.warning("遗漏：" + "、".join(item["misses"]))
            if item.get("misconceptions"):
                st.error("错误概念：" + "、".join(item["misconceptions"]))
            review_points = item.get("misses", []) + item.get("misconceptions", [])
            if review_points and st.button(
                "让研学导师讲解本题遗漏",
                icon=":material/school:",
                key=f"review-{assessment_id}-{item['question_id']}",
            ):
                prompt = (
                    f"我在 {item['question_id'].upper()} 中遗漏或答错了以下内容："
                    f"{'；'.join(review_points)}。请结合本专题资料逐点讲解，"
                    "给出一个正确示例和面试回答建议，并保留引用。"
                )
                answer, _ = api_post(
                    f"/api/study/tasks/{assessment['task_id']}/chat",
                    {"message": prompt},
                    timeout=100,
                )
                if answer:
                    st.session_state.study_task_id = assessment["task_id"]
                    st.switch_page("app_pages/workbench.py")
    if result.get("suggestions"):
        st.subheader("针对性复习建议")
        for suggestion in result["suggestions"]:
            st.markdown(f"- {suggestion}")
    if st.button("下一步：查看学习报告", icon=":material/arrow_forward:", type="primary"):
        st.switch_page("app_pages/reports.py")


render_assessment_result()
