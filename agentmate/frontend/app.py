"""AgentMate Streamlit 入口。"""

import streamlit as st

from agentmate.frontend.common import api_get

st.set_page_config(
    page_title="AgentMate｜AI Agent 专题研学",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="auto",
)

st.session_state.setdefault("show_beginner_guide", True)
st.session_state.setdefault("demo_mode", False)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #fbfcfe; }
[data-testid="stSidebar"] { border-right: 1px solid #e8edf4; }
.block-container { max-width: 1180px; padding-top: 3.25rem; padding-bottom: 4rem; }
.agentmate-kicker { display: none; }
.agentmate-muted { color: #64748b; }
[data-testid="stForm"] { background: #ffffff; }
</style>
""", unsafe_allow_html=True)

pages = [
    st.Page("app_pages/workbench.py", title="研学工作台", icon=":material/explore:", default=True),
    st.Page("app_pages/resources.py", title="资料库", icon=":material/library_books:"),
    st.Page("app_pages/assessment.py", title="实践评测", icon=":material/quiz:"),
    st.Page("app_pages/reports.py", title="学习报告", icon=":material/insights:"),
]

with st.sidebar:
    st.markdown("## 🧠 AgentMate")
    st.caption("AI Agent 专题研学与保研面试训练")
    st.toggle("显示新手引导", key="show_beginner_guide", help="随时重新查看完整使用流程。")
    st.toggle(
        "答辩演示模式",
        key="demo_mode",
        help="展示 Agent 分工、调用耗时、检索策略和引用校验等技术细节。",
    )
    st.divider()
    health, error = api_get("/health", timeout=3, show_error=False)
    if health:
        st.markdown(":green-badge[✓ 服务已就绪]")
        st.caption(f"知识块 {health.get('knowledge_chunks', 0)} · 队列 {health.get('queue_size', 0)}")
    else:
        st.error("后端尚未启动")
        st.caption(error or "请先运行 python run_server.py，再刷新页面。")

navigation = st.navigation(pages, position="top")
navigation.run()
