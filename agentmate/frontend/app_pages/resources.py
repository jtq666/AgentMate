"""资料库页面。"""

import base64
from datetime import date

import streamlit as st

from agentmate.frontend.common import (
    api_delete,
    api_get,
    api_patch,
    api_post,
    render_study_steps,
)

st.markdown('<div class="agentmate-kicker">可选工具</div>', unsafe_allow_html=True)
st.title("资料库")
st.caption("内置资料已经可以直接开始学习；这里用于补充你自己的讲义、笔记或论文。")
render_study_steps(1)

pending_topic = st.session_state.get("pending_resource_topic", "")
if pending_topic:
    st.info(
        f"正在为自定义主题“{pending_topic}”补充资料。请上传直接讲解该主题的讲义、笔记或论文。",
        icon=":material/library_add:",
    )
    if st.session_state.get("topic_material_ready") == pending_topic:
        st.success("资料已导入，可以返回工作台重新检查并创建任务。")
        if st.button(
            "返回工作台重新检查",
            icon=":material/arrow_back:",
            type="primary",
        ):
            st.session_state.create_topic = "自定义主题"
            st.session_state.create_custom_topic = pending_topic
            st.switch_page("app_pages/workbench.py")

if st.session_state.get("show_beginner_guide", True):
    st.info(
        "第一次使用可以跳过本页，直接去“研学工作台”创建 ReAct 任务。上传资料后，新任务会自动检索这些内容。",
        icon=":material/info:",
    )

stats, _ = api_get("/api/kb/stats", show_error=False)
if stats:
    st.markdown(
        f":blue-badge[{stats['total']} 个知识块]　"
        f":gray-badge[{len(stats.get('sources', {}))} 个资料来源]　"
        f":gray-badge[{len(stats.get('source_types', {}))} 种来源类型]"
    )

upload_tab, search_tab, paper_tab, manage_tab = st.tabs(["添加我的资料", "搜索已有资料", "查找论文", "管理资料"])

with upload_tab:
    with st.container(border=True):
        st.subheader("上传文件")
        st.caption("推荐方式 · 适合讲义、课程笔记和已下载论文")
        uploaded = st.file_uploader(
            "支持 Markdown、TXT、PDF、DOCX 等",
            type=["md", "txt", "pdf", "docx", "json", "csv"],
        )
        if uploaded and st.button(
            "导入这个文件",
            type="primary",
            icon=":material/upload:",
        ):
            payload = base64.b64encode(uploaded.getvalue()).decode("ascii")
            result, _ = api_post("/api/import/file", {
                "filename": uploaded.name, "content_base64": payload,
            }, timeout=60)
            if result:
                st.toast(f"{uploaded.name} 已导入 {result['imported']} 个知识块。", icon="✅")
                if pending_topic:
                    st.session_state.topic_material_ready = pending_topic
                    st.rerun()

    with st.expander("没有文件？直接粘贴文本", icon=":material/content_paste:"):
        st.subheader("粘贴文本")
        with st.form("import_text", border=False):
            title = st.text_input("资料标题", value=pending_topic)
            content = st.text_area("正文", height=220)
            if st.form_submit_button("导入这段文本", type="primary"):
                result, _ = api_post("/api/import/text", {"title": title or "用户资料", "content": content})
                if result:
                    st.toast(f"已导入 {result['imported']} 个知识块。", icon="✅")
                    if pending_topic:
                        st.session_state.topic_material_ready = pending_topic
                        st.rerun()

with search_tab:
    query = st.text_input("检索问题", placeholder="例如：ReAct 中 Observation 的作用")
    if st.button("执行 ChromaDB + BM25 + RRF 检索") and query.strip():
        result, _ = api_post("/api/kb/search", {"query": query, "top_k": 8})
        if result:
            st.caption(f"共返回 {result['total']} 条结果")
            for index, item in enumerate(result["results"], 1):
                with st.expander(f"{index}. {item['source']} · RRF {item['score']:.4f}"):
                    st.markdown(item["content"])
                    st.caption(f"document_id={item['document_id']} · {item['source_type']}")

with paper_tab:
    st.subheader("检索学术论文")
    st.caption("先限定范围，再从结果中按作者、会议和摘要继续筛选。")
    with st.form("paper_search", border=True):
        query = st.text_input(
            "论文主题",
            placeholder="例如：multi-agent collaboration large language models",
        )
        first, second = st.columns(2, vertical_alignment="bottom")
        with first:
            current_year = date.today().year
            year_range = st.slider(
                "发表年份",
                min_value=1990,
                max_value=current_year,
                value=(2020, current_year),
            )
            sources = st.pills(
                "检索来源",
                ["Semantic Scholar", "arXiv"],
                default=["Semantic Scholar", "arXiv"],
                selection_mode="multi",
                help="Semantic Scholar 适合按引用筛选；arXiv 适合查找较新的预印本。",
            )
        with second:
            min_citations = st.number_input(
                "最低引用数",
                min_value=0,
                max_value=100000,
                value=0,
                step=5,
                help="arXiv 不提供引用数；设置大于 0 时会过滤 arXiv 结果。",
            )
            max_results = st.select_slider(
                "最多返回",
                options=[5, 8, 10, 15, 20],
                value=10,
                format_func=lambda value: f"{value} 篇",
            )
        search_submitted = st.form_submit_button(
            "按条件搜索论文",
            icon=":material/search:",
            type="primary",
            width="stretch",
        )
        if search_submitted:
            if not query.strip():
                st.error("请输入论文主题。")
            elif not sources:
                st.error("请至少选择一个检索来源。")
            else:
                source_values = [
                    "semantic_scholar" if source == "Semantic Scholar" else "arxiv"
                    for source in sources
                ]
                with st.spinner("正在检索和整理论文……"):
                    result, _ = api_post("/api/papers/search", {
                        "query": query,
                        "min_year": year_range[0],
                        "max_year": year_range[1],
                        "min_citations": min_citations,
                        "max_results": max_results,
                        "sources": source_values,
                    }, timeout=90)
                if result:
                    st.session_state.paper_result = result
                    st.toast(f"找到 {result['total']} 篇论文。", icon="✅")
    result = st.session_state.get("paper_result")
    if result:
        st.subheader("检索结果")
        papers = result["papers"]
        available_sources = sorted({paper.get("source", "unknown") for paper in papers})
        filter_left, filter_right = st.columns([3, 2], vertical_alignment="bottom")
        with filter_left:
            result_keyword = st.text_input(
                "在结果中筛选",
                key=f"paper-keyword-{result['search_id']}",
                placeholder="输入作者、会议或标题关键词",
                icon=":material/filter_list:",
            )
        with filter_right:
            sort_by = st.segmented_control(
                "排序",
                ["综合质量", "最新发表", "引用最多"],
                default="综合质量",
                key=f"paper-sort-{result['search_id']}",
            )
        quick_filters = st.pills(
            "快捷筛选",
            ["近三年", "高引用", "重要会议", "有 PDF", "仅收藏"],
            selection_mode="multi",
            key=f"paper-quick-filter-{result['search_id']}",
        )
        with st.popover("更多筛选", icon=":material/tune:"):
            source_filter = st.multiselect(
                "论文来源",
                available_sources,
                default=available_sources,
                format_func=lambda value: {
                    "semantic_scholar": "Semantic Scholar",
                    "arxiv": "arXiv",
                }.get(value, value),
                key=f"paper-source-filter-{result['search_id']}",
            )
            require_abstract = st.toggle(
                "只看有摘要的论文",
                key=f"paper-abstract-filter-{result['search_id']}",
            )

        keyword = result_keyword.strip().lower()
        filtered = [
            paper for paper in papers
            if paper.get("source", "unknown") in source_filter
            and (not require_abstract or bool(paper.get("abstract")))
            and ("近三年" not in quick_filters or (paper.get("year") or 0) >= date.today().year - 2)
            and ("高引用" not in quick_filters or (paper.get("citations") or 0) >= 100)
            and ("重要会议" not in quick_filters or paper.get("is_top_venue", False))
            and ("有 PDF" not in quick_filters or paper.get("has_pdf", False))
            and (
                "仅收藏" not in quick_filters
                or st.session_state.get(
                    f"paper-favorite-{result['search_id']}-{paper['index']}", False
                )
            )
            and (
                not keyword
                or keyword in paper.get("title", "").lower()
                or keyword in paper.get("venue", "").lower()
                or any(keyword in author.lower() for author in paper.get("authors", []))
            )
        ]
        if sort_by == "最新发表":
            filtered.sort(key=lambda paper: paper.get("year") or 0, reverse=True)
        elif sort_by == "引用最多":
            filtered.sort(key=lambda paper: paper.get("citations") or 0, reverse=True)

        st.caption(f"当前显示 {len(filtered)} / {len(papers)} 篇 · 搜索主题：{result['query']}")
        for paper in filtered:
            with st.expander(f"{paper['index']}. {paper['title']} ({paper.get('year') or '年份未知'})"):
                author_text = "、".join(paper.get("authors", [])) or "作者未知"
                source_text = {
                    "semantic_scholar": "Semantic Scholar",
                    "arxiv": "arXiv",
                }.get(paper.get("source"), paper.get("source", "来源未知"))
                st.caption(
                    f"{author_text} · {paper.get('venue') or '未标注会议'} · "
                    f"引用 {paper.get('citations', 0)} · {source_text}"
                )
                reasons = paper.get("recommendation_reasons", ["主题相关"])
                st.markdown("　".join(f":blue-badge[{reason}]" for reason in reasons))
                st.write(paper.get("abstract") or "暂无摘要")
                with st.container(horizontal=True, vertical_alignment="center"):
                    if paper.get("url"):
                        st.link_button(
                            "打开论文",
                            paper["url"],
                            icon=":material/open_in_new:",
                        )
                    st.checkbox(
                        "加入资料库",
                        key=f"paper-{result['search_id']}-{paper['index']}",
                    )
                    st.checkbox(
                        "收藏论文",
                        key=f"paper-favorite-{result['search_id']}-{paper['index']}",
                    )
        if not filtered:
            st.info("没有符合当前筛选条件的论文，请减少筛选条件。")

        selected = [
            paper["index"]
            for paper in papers
            if st.session_state.get(f"paper-{result['search_id']}-{paper['index']}", False)
        ]
        if st.button(
            f"导入选中的 {len(selected)} 篇论文",
            icon=":material/library_add:",
            type="primary",
            disabled=not selected,
        ):
            imported, _ = api_post("/api/papers/import", {
                "search_id": result["search_id"], "indices": selected,
            })
            if imported:
                st.toast(f"已导入 {imported['imported']} 篇论文。", icon="✅")

with manage_tab:
    listing, _ = api_get("/api/kb/list", show_error=False)
    if listing:
        type_filter = st.multiselect("来源类型", sorted({doc["source_type"] for doc in listing["docs"]}))
        name_filter = st.text_input(
            "按资料名称筛选",
            placeholder="输入文件名、课程名或论文标题",
            icon=":material/search:",
        )
        docs = [
            doc for doc in listing["docs"]
            if (not type_filter or doc["source_type"] in type_filter)
            and (
                not name_filter.strip()
                or name_filter.strip().lower() in doc["source"].lower()
            )
        ]
        page_size = 10
        page_count = max(1, (len(docs) + page_size - 1) // page_size)
        current_page = st.pagination(
            page_count,
            key="knowledge-page",
            width="content",
        )
        start = (current_page - 1) * page_size
        visible_docs = docs[start:start + page_size]
        st.caption(f"共 {len(docs)} 个知识块 · 第 {current_page}/{page_count} 页")
        for doc in visible_docs:
            left, right = st.columns([7, 2], vertical_alignment="center")
            with left:
                st.markdown(f"**{doc['source']}** · `{doc['source_type']}`")
                st.caption(doc["content_preview"])
            with right:
                with st.popover("管理", icon=":material/settings:"):
                    st.caption(f"文档 ID：{doc['document_id']}")
                    st.write(doc["content_preview"])
                    with st.form(f"rename-doc-{doc['id']}", border=False):
                        new_doc_title = st.text_input("资料名称", value=doc["source"])
                        if st.form_submit_button("保存名称"):
                            updated, _ = api_patch(
                                f"/api/kb/{doc['id']}", {"title": new_doc_title.strip()}
                            )
                            if updated:
                                st.rerun()
                    confirm_doc_delete = st.checkbox(
                        "确认删除",
                        key=f"confirm-delete-doc-{doc['id']}",
                    )
                    if st.button(
                        "永久删除",
                        icon=":material/delete:",
                        disabled=not confirm_doc_delete,
                        key=f"delete-doc-{doc['id']}",
                    ):
                        deleted, _ = api_delete(f"/api/kb/delete/{doc['id']}")
                        if deleted:
                            st.rerun()
