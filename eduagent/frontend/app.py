"""
EduAgent — AI Agent 研究助手 前端
"""

import streamlit as st
import requests
import re
import json
import os

st.set_page_config(page_title="EduAgent - AI Agent 研究助手", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.stApp { font-family: 'Segoe UI', -apple-system, sans-serif; }
section[data-testid="stSidebar"] { background: #f8f9fa; border-right: 1px solid #e9ecef; }
section[data-testid="stSidebar"] h1 { color: #1a1a2e; }
section[data-testid="stSidebar"] .stRadio label { color: #333; font-size: 0.9rem; padding: 8px 12px; border-radius: 8px; }
section[data-testid="stSidebar"] .stRadio label:hover { background: #e9ecef; }
.main-title { font-size: 1.8rem; font-weight: 700; color: #1a1a2e; }
.sub-title { color: #6c757d; font-size: 0.9rem; margin-bottom: 1.2rem; }
.stat-box { text-align: center; padding: 1rem; border-radius: 10px; background: #f8f9fa; border: 1px solid #e9ecef; }
.stat-num { font-size: 1.8rem; font-weight: 700; color: #2563eb; }
.stat-label { font-size: 0.8rem; color: #6c757d; }
.chat-user { background: #e3f2fd; border-radius: 12px 12px 0 12px; padding: 10px 14px; margin: 4px 0; }
.chat-bot { background: #f1f3f4; border-radius: 12px 12px 12px 0; padding: 10px 14px; margin: 4px 0; }
</style>
""", unsafe_allow_html=True)

API = "http://localhost:8000"

def api_post(path, data, timeout=180):
    try:
        r = requests.post(f"{API}{path}", json=data, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except: return None

def api_get(path):
    try:
        r = requests.get(f"{API}{path}", timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

def api_delete(path):
    try:
        r = requests.delete(f"{API}{path}", timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

def check_api():
    try: return requests.get(f"{API}/health", timeout=3).status_code == 200
    except: return False

# ==================== 侧边栏 ====================
with st.sidebar:
    st.markdown("## 🧠 EduAgent")
    st.markdown("<p style='color:#6c757d;font-size:0.85rem'>AI Agent 研究助手</p>", unsafe_allow_html=True)
    st.markdown("---")
    page = st.radio("导航", [
        "💬 概念问答", "🏋️ 面试模拟", "🔬 论文检索", "📚 知识库", "🧠 学习进度",
    ], label_visibility="collapsed")
    st.markdown("---")
    if check_api():
        st.markdown('<span style="color:#2e7d32;font-size:0.85rem">● 服务运行中</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="color:#c62828;font-size:0.85rem">● 服务未启动</span>', unsafe_allow_html=True)

if not check_api():
    st.markdown('<p class="main-title">🧠 EduAgent — AI Agent 研究助手</p>', unsafe_allow_html=True)
    st.warning("后端服务未启动\n\n请运行：`python run_server.py`")
    st.stop()


# ==================== 概念问答 ====================
if page == "💬 概念问答":
    st.markdown('<p class="main-title">💬 Agent 概念问答</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">基于课程文档 + LLM 知识回答 · ReAct 引导式学习</p>', unsafe_allow_html=True)

    chat_file = "eduagent/data/chat_history.json"

    # 新用户引导
    if "chat_msgs" not in st.session_state or not st.session_state.get("chat_msgs"):
        st.info("👋 **欢迎！** 我是你的 AI Agent 学习助手。\n\n试试问我：\n- 「我想系统学习AI Agent，从哪开始？」\n- 「什么是ReAct？」\n- 「出一道面试题」")

    # 加载历史消息（刷新后恢复）
    if "chat_msgs" not in st.session_state:
        if os.path.exists(chat_file):
            try:
                with open(chat_file, "r", encoding="utf-8") as f:
                    st.session_state.chat_msgs = json.load(f)[-20:]  # 最近20条
            except Exception:
                st.session_state.chat_msgs = []
        else:
            st.session_state.chat_msgs = []

    for msg in st.session_state.chat_msgs:
        cls = "chat-user" if msg["role"] == "user" else "chat-bot"
        icon = "🧑" if msg["role"] == "user" else "🤖"
        st.markdown(f'<div class="{cls}">{icon} {msg["content"]}</div>', unsafe_allow_html=True)

    if query := st.chat_input("问概念，如「什么是ReAct？」或「多Agent系统我不太懂」..."):
        st.session_state.chat_msgs.append({"role": "user", "content": query})
        st.markdown(f'<div class="chat-user">🧑 {query}</div>', unsafe_allow_html=True)

        with st.spinner("🤖 思考中..."):
            result = api_post("/api/chat", {"query": query})
        if result:
            st.markdown(f'<div class="chat-bot">🤖 {result["response"]}</div>', unsafe_allow_html=True)
            if result.get("trajectory"):
                with st.expander("🧠 Agent 思考过程"):
                    st.markdown(result["trajectory"])
            stats = result.get("memory_stats", {})
            st.caption(f"意图: {result.get('intent','')} | 记忆: 工作{stats.get('working',0)} · 短期{stats.get('short_term',0)} · 长期{stats.get('long_term',0)}")
            st.session_state.chat_msgs.append({"role": "assistant", "content": result["response"]})

        # 自动保存
        try:
            os.makedirs(os.path.dirname(chat_file), exist_ok=True)
            with open(chat_file, "w", encoding="utf-8") as f:
                json.dump([{"role": m["role"], "content": m["content"][:200]} for m in st.session_state.chat_msgs[-20:]], f, ensure_ascii=False)
        except Exception:
            pass


# ==================== 面试模拟 ====================
elif page == "🏋️ 面试模拟":
    st.markdown('<p class="main-title">🏋️ 面试模拟</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">AI 根据薄弱点出题 · 模拟保研面试问答</p>', unsafe_allow_html=True)

    interview_file = "eduagent/data/interview_history.json"

    if "interview_chat" not in st.session_state:
        if os.path.exists(interview_file):
            try:
                with open(interview_file, "r", encoding="utf-8") as f:
                    st.session_state.interview_chat = json.load(f)[-20:]
            except Exception:
                st.session_state.interview_chat = []
        else:
            st.session_state.interview_chat = []

    for msg in st.session_state.interview_chat:
        cls = "chat-user" if msg["role"] == "user" else "chat-bot"
        icon = "🧑" if msg["role"] == "user" else "🤖"
        st.markdown(f'<div class="{cls}">{icon} {msg["content"]}</div>', unsafe_allow_html=True)

    if query := st.chat_input("说话，如「出一道面试题」「ReAct 的面试题」「推荐题目」..."):
        st.session_state.interview_chat.append({"role": "user", "content": query})
        st.markdown(f'<div class="chat-user">🧑 {query}</div>', unsafe_allow_html=True)

        with st.spinner("🤖 准备中..."):
            result = api_post("/api/chat", {"query": query, "intent_hint": "practice"})
        if result:
            st.markdown(f'<div class="chat-bot">🤖 {result["response"]}</div>', unsafe_allow_html=True)
            st.session_state.interview_chat.append({"role": "assistant", "content": result["response"]})

        try:
            os.makedirs(os.path.dirname(interview_file), exist_ok=True)
            with open(interview_file, "w", encoding="utf-8") as f:
                json.dump([{"role": m["role"], "content": m["content"][:200]} for m in st.session_state.interview_chat[-20:]], f, ensure_ascii=False)
        except Exception:
            pass


# ==================== 论文检索 ====================
elif page == "🔬 论文检索":
    st.markdown('<p class="main-title">🔬 论文检索</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Semantic Scholar + arXiv · 质量筛选 · 选导入</p>', unsafe_allow_html=True)

    # 筛选条件
    c1, c2, c3 = st.columns(3)
    with c1:
        min_citations = st.number_input("最少引用数", min_value=0, value=5, step=5)
    with c2:
        min_year = st.number_input("最早年份", min_value=2015, max_value=2026, value=2022, step=1)
    with c3:
        max_results = st.number_input("返回数量", min_value=3, max_value=20, value=8)

    query = st.text_input("搜索关键词", placeholder="如：multi-agent reinforcement learning、ReAct reasoning agents...")
    search_btn = st.button("🔬 搜索论文", type="primary", use_container_width=True)

    if search_btn and query.strip():
        with st.spinner("🔬 检索中..."):
            result = api_post("/api/papers/search", {
                "query": query,
                "min_citations": min_citations,
                "min_year": min_year,
                "max_results": max_results,
            }, timeout=60)
        if result:
            st.session_state.paper_results = result
            st.session_state.selected_papers = set()
            # 检查是否所有论文都无引用数据（Semantic Scholar 限流）
            papers = result.get("papers", [])
            if papers and all(p.get("year", 0) == 0 for p in papers):
                st.warning("⚠️ Semantic Scholar API 暂时限流，已切换到 arXiv 搜索（引用数和年份不可用）。稍后重试可恢复正常。")

    # 显示搜索结果
    if "paper_results" in st.session_state:
        pr = st.session_state.paper_results
        st.markdown(f"**搜索词**: `{pr.get('query','')}` | 找到 {pr.get('total',0)} 篇")
        st.markdown("---")

        papers = pr.get("papers", [])
        selected = []

        for p in papers:
            idx = p["index"]
            c1, c2 = st.columns([0.05, 0.95])
            with c1:
                checked = st.checkbox("", key=f"paper_{idx}",
                    value=idx in st.session_state.get("selected_papers", set()))
                if checked:
                    st.session_state.setdefault("selected_papers", set()).add(idx)
                else:
                    st.session_state.setdefault("selected_papers", set()).discard(idx)
            with c2:
                quality = p.get("quality", "○")
                st.markdown(f"""**{quality} #{idx} {p['title']}**
{p.get('authors_str', ', '.join(p.get('authors',[])))} | 📅 {p.get('year','?')} | 📊 引用 {p.get('citations',0)} | 📍 {p.get('venue','N/A')}
{p.get('abstract','')[:200]}...""")

        # 导入按钮
        selected_indices = sorted(st.session_state.get("selected_papers", set()))
        if selected_indices:
            st.markdown("---")
            st.markdown(f"已选择 {len(selected_indices)} 篇：#{', #'.join(map(str, selected_indices))}")
            if st.button("📥 导入选中的论文", type="primary"):
                with st.spinner("导入中..."):
                    r = api_post("/api/papers/import", {"indices": selected_indices})
                if r:
                    st.success(f"✅ 已导入 {r.get('imported',0)} 篇论文到知识库")
                    st.session_state.pop("paper_results", None)
                    st.session_state.pop("selected_papers", None)
                    st.rerun()
        elif papers:
            st.info("👆 勾选感兴趣的论文，然后点击导入")


# ==================== 知识库 ====================
elif page == "📚 知识库":
    st.markdown('<p class="main-title">📚 知识库管理</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">导入 AI Agent 论文/笔记，让 AI 基于你的资料回答<br>支持格式：.md .txt .pdf .docx .json .html .csv .py .cpp .java</p>', unsafe_allow_html=True)

    if "kb_action" not in st.session_state:
        st.session_state.kb_action = None

    if st.session_state.kb_action == "clear":
        api_delete("/api/kb/clear")
        st.session_state.kb_action = None
    elif st.session_state.kb_action and st.session_state.kb_action.startswith("del_"):
        doc_id = st.session_state.kb_action.split("_")[1]
        api_delete(f"/api/kb/delete/{doc_id}")
        st.session_state.kb_action = None

    kb = api_get("/api/kb/stats")
    kb_list_data = api_get("/api/kb/list")
    paper_count = 0
    if kb_list_data:
        paper_count = sum(1 for d in kb_list_data.get("docs", []) if d.get("source","").startswith("paper://"))

    if kb:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f'<div class="stat-box"><div class="stat-num">{kb.get("total",0)}</div><div class="stat-label">文档块总数</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="stat-box"><div class="stat-num">{paper_count}</div><div class="stat-label">论文块数</div></div>', unsafe_allow_html=True)

    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📝 粘贴文本", "📄 上传文件", "📁 导入目录"])

    with tab1:
        title = st.text_input("标题", placeholder="例如：ReAct 论文笔记")
        text = st.text_area("粘贴内容", height=200, label_visibility="collapsed")
        if st.button("📥 导入", type="primary", key="imp_text"):
            if text.strip():
                r = api_post("/api/import/text", {"title": title or "用户输入", "content": text})
                if r and r.get("imported", 0) > 0: st.success(f"导入 {r['imported']} 个文档块")

    with tab2:
        uploaded_files = st.file_uploader(
            "上传文件", type=["md", "txt", "pdf", "docx", "json", "html", "csv", "py", "cpp", "java", "c", "h", "yaml", "yml"],
            accept_multiple_files=True, label_visibility="collapsed",
        )
        if uploaded_files and st.button("📥 导入选中的文件", type="primary", key="imp_file"):
            total = 0
            for f in uploaded_files:
                content = f.read().decode("utf-8", errors="ignore")
                r = api_post("/api/import/file", {"filename": f.name, "content": content})
                if r: total += r.get("imported", 0)
            if total > 0: st.success(f"✅ 导入 {total} 个文档块（{len(uploaded_files)} 个文件）")

    with tab3:
        dir_path = st.text_input("目录路径", placeholder="F:\\agent\\knowledge")
        if st.button("📥 导入目录", type="primary", key="imp_dir"):
            if dir_path.strip():
                r = api_post("/api/import", {"directory": dir_path.strip()})
                if r: st.success(f"导入 {r.get('imported',0)} 个文档块")

    # 文档列表
    st.markdown("---")
    st.markdown("#### 📋 文档管理")
    kb_list = api_get("/api/kb/list")
    if kb_list and kb_list.get("docs"):
        for doc in kb_list["docs"][:30]:
            c1, c2 = st.columns([6, 1])
            with c1:
                h = doc.get("heading", "") or doc.get("source", "")
                st.markdown(f"📄 **{h}** — {doc.get('content_preview','')[:40]}...")
            with c2:
                if st.button("🗑️", key=f"del_{doc['id']}"):
                    st.session_state.kb_action = f"del_{doc['id']}"
        if st.button("⚠️ 清空知识库"):
            st.session_state.kb_action = "clear"


# ==================== 学习进度 ====================
elif page == "🧠 学习进度":
    st.markdown('<p class="main-title">🧠 学习进度</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">看看 Agent 记住了什么</p>', unsafe_allow_html=True)

    data = api_get("/api/memory?student_id=default")
    if not data:
        st.info("暂无记忆数据，去概念问答聊几句再来")
        st.stop()

    s = data.get("stats", {})

    # 三层记忆卡片
    st.markdown("### 三层记忆")
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("📋 工作记忆", s.get("working", 0), help="当前对话窗口中的记忆")
    with c2: st.metric("📝 短期记忆", s.get("short_term", 0), help="对话溢出的压缩摘要")
    with c3: st.metric("💾 长期记忆", s.get("long_term", 0), help="持久化存储，跨会话保留")

    st.markdown("---")

    # 最近记忆内容
    recent = data.get("recent_memories", [])
    if recent:
        st.markdown("### 📜 Agent 还记得这些")
        for m in recent[-8:]:
            imp = m.get("importance", 0)
            icon = "🔴" if imp >= 0.7 else "🟡" if imp >= 0.4 else "⚪"
            # 取前80字符或第一个句号处截断
            content = m.get('content','')
            # 找第一个句号/问号/感叹号截断
            cut = 100
            for sep in ['。','？','！','\n']:
                idx = content.find(sep, 0, 100)
                if idx > 0:
                    cut = idx + 1
                    break
            display = content[:cut].strip()
            st.markdown(f"{icon} {display}")
    else:
        st.markdown("### 📜 Agent 还记得这些")
        st.info("短期记忆暂无（对话量不够，还没触发压缩）。去概念问答多聊几轮。")

    st.markdown("---")

    st.markdown("---")
    st.caption("💡 去概念问答多聊几轮，再回来看记忆的变化。刷新页面长期记忆不会丢。")
