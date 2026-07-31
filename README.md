# AgentMate — AI Agent 研究助手

> 基于多Agent协作的 AI Agent 学习系统，帮助你从零到一掌握 Agent 技术，准备保研/考研面试。

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org) [![ChromaDB](https://img.shields.io/badge/ChromaDB-1.5-green)](https://trychroma.com) [![Streamlit](https://img.shields.io/badge/Streamlit-1.0-red)](https://streamlit.io)

## 核心特点

- **全部由 LLM 驱动**：意图分类、语言判断、题目选择、话题提取均由 LLM 自主决策，零硬编码规则
- **真正的多Agent协作**：5 个 Agent 各有不同工具，通过 ToolRegistry 自主选择调用
- **ChromaDB 语义检索**：RAG 知识库 + 长期记忆均为向量检索，非关键词匹配
- **三层记忆系统**：工作记忆(滑动窗口) → 短期记忆(LLM压缩) → 长期记忆(ChromaDB语义召回)
- **ReAct + Reflexion**：Agent 多步推理 + 自我反思修正

## 架构

```
用户输入
  │
  ▼
┌──────────────────────────────┐
│    Memory Manager (三层)      │
│  工作→短期(LLM摘要)           │
│    →长期(ChromaDB语义召回)    │
├──────────────────────────────┤
│  Coordinator (LLM意图路由)   │
├──────┬──────┬──────┬─────────┤
│Teaching│Concept│Practice│Paper│
│ Agent  │  QA   │ Agent  │Search│
│(ReAct) │ (RAG) │(个性化)│(API) │
└──────┴──────┴──────┴─────────┘
```

## 功能模块

| 模块 | 说明 | 技术 |
|------|------|------|
| 💬 概念问答 | RAG检索 + ReAct引导式教学 + Reflexion反思 | ChromaDB + BM25 + RRF |
| 🏋️ 面试模拟 | 根据学习历史个性化出题 | 记忆驱动的LLM出题 |
| 🔬 论文检索 | 搜索 Semantic Scholar/arXiv 高质量论文 | 外部API工具调用 |
| 📚 知识库 | 导入课程文档，支持 PDF/DOCX/MD/TXT | 语义分块 + 向量存储 |
| 🧠 学习进度 | 三层记忆可视化，查看Agent记住了什么 | ChromaDB语义召回 |

## 快速开始

### 1. 配置

```bash
git clone git@github.com:jtq666/edu-agent.git
cd edu-agent
cp .env.example .env
# 编辑 .env 填入你的 DeepSeek API Key
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动

**后端：**
```bash
python run_server.py
```

**前端：**
```bash
streamlit run agentmate/frontend/app.py
```

浏览器打开 http://localhost:8501

### 4. 导入知识库

前端 → 📚 知识库 → 📁 导入目录 → `agentmate/data/agent_knowledge`

### 5. 开始使用

- 💬 概念问答 → 问 "什么是ReAct？"
- 🏋️ 面试模拟 → "出一道面试题"
- 🔬 论文检索 → 搜索论文 → 勾选导入
- 🧠 学习进度 → 查看记忆

## 项目结构

```
agentmate/
├── config.py              # 全局配置
├── memory.py              # 三层记忆系统(ChromaDB语义召回)
├── agents/
│   ├── base.py            # Agent基类 + 共享状态
│   ├── arch.py            # ToolRegistry / ReAct / Plan-and-Execute / Reflexion
│   ├── coordinator.py     # LLM驱动的意图路由
│   ├── teaching.py        # ReAct教学Agent(Reflexion)
│   ├── concept_qa.py      # RAG概念问答Agent
│   ├── practice_agent.py  # 记忆驱动的面试出题Agent
│   └── paper_search.py    # 论文检索Agent(arXiv/S2 API)
├── code_engine/
│   └── analyzer.py        # 代码复杂度分析
├── knowledge/
│   ├── parser.py          # 文档解析(PDF/DOCX/MD/TXT)
│   ├── retriever.py       # ChromaDB + BM25 + RRF检索
│   ├── practice.py        # 练习题库
│   └── paper_api.py       # arXiv + Semantic Scholar API
├── api/
│   └── main.py            # FastAPI后端
├── frontend/
│   └── app.py             # Streamlit前端
├── data/
│   └── agent_knowledge/   # AI Agent领域课程文档
└── tests/
    └── test_all.py        # 21项单元测试
```

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangChain + 自研 ToolRegistry |
| 推理模式 | ReAct / Reflexion / Plan-and-Execute |
| 向量检索 | ChromaDB + BM25 + RRF 融合 |
| Embedding | all-MiniLM-L6-v2 (本地) |
| 知识库解析 | PDF (pdfplumber/PyMuPDF) + DOCX (python-docx) + MD |
| 论文检索 | Semantic Scholar API + arXiv API |
| 后端 | FastAPI |
| 前端 | Streamlit |
| LLM | DeepSeek-Chat (可替换任意 OpenAI 兼容 API) |

## Agent 架构深度

### ToolRegistry 工具注册

```python
# 每个Agent注册自己的工具，LLM根据描述自主选择
ToolRegistry.register("retrieve_knowledge", "从课程知识库检索相关文档", kb.search)
ToolRegistry.register("query_memory", "查询学生历史记录", memory.recall)
```

### ReAct 多步推理

```
Thought → 分析当前情况
Action → 调用工具
Observation → 观察结果
→ 循环直到得出答案
```

### Reflexion 自我反思

```
生成回答 → 自我评审 → 不满意 → 修正重新生成
```

### 三层记忆

| 层级 | 作用 | 生命周期 | 实现 |
|------|------|---------|------|
| 工作记忆 | 当前对话窗口 | 当前对话 | 滑动窗口 + Token管理 |
| 短期记忆 | 溢出对话压缩 | 当前会话 | LLM摘要压缩 |
| 长期记忆 | 跨会话持久化 | 永久 | ChromaDB语义召回 |

## License

MIT
