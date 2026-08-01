# AgentMate

面向计算机保研学生的 **AI Agent 专题研学与面试训练平台**。

固定 Supervisor 多 Agent 流水线，融合混合检索、带引用讲解、模拟面试、自动评分与薄弱点复习，覆盖从资料检索到学习报告的完整闭环。

![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35+-red)

## 效果数据

基于 6 个专题 × 4 题 = 24 题固定基准，对四种配置进行消融实验：

| 配置 | 必答点覆盖率 | 引用有效率 | 事实错误 | 平均延迟 |
|------|:---:|:---:|:---:|:---:|
| 单 LLM（无 RAG） | 76.0% | 0.0% | 1 | 6.6s |
| 单 Agent + 混合 RAG | **95.8%** | **100%** | **0** | 2.6s |
| 多 Agent（无 Reflexion） | 92.7% | 100% | 0 | 4.3s |
| 完整多 Agent + RAG + Reflexion | **95.8%** | **100%** | **0** | 7.9s |

> 混合 RAG 是主要质量增益来源；多 Agent 的核心价值在职责隔离、隐藏评分规则、阶段恢复与引用审计，而非无条件提升准确率。

## 架构

```
┌──────────────────────────────────────────────────────┐
│                Streamlit 四页前端                      │
│  研学工作台 │ 资料库 │ 实践评测 │ 学习报告              │
└──────────┬───────────────────────────┬───────────────┘
           │                           │
     ┌─────▼─────┐              ┌──────▼──────┐
     │  FastAPI   │              │  Evaluation  │
     │  任务 API  │              │    Agent     │
     └─────┬─────┘              └──────┬──────┘
           │                           │
     ┌─────▼───────────────────────────▼──────┐
     │         单并发异步后台任务队列            │
     └─────┬─────┬─────────┬─────────┬────────┘
           │     │         │         │
      Research Teaching  Interview Supervisor
      Agent    Agent     Agent      Agent
           │     │         │         │
     ┌─────▼─────▼─────────▼─────────▼────┐
     │    ChromaDB + BM25 + RRF 混合检索    │
     │            SQLite WAL                │
     └─────────────────────────────────────┘
```

## 功能概览

### 多 Agent 流水线

| Agent | 职责 | 输出 |
|-------|------|------|
| **Research** | 混合检索资料，分配 `[Sx]` 引用编号 | `ResearchOutput`（来源、要点、警告） |
| **Teaching** | 基于检索资料生成结构化讲解 | `TeachingOutput`（学习地图、概念、误区） |
| **Interview** | 生成 5 道递进面试题，隐藏评分规则 | `InterviewOutput`（题目、rubric、必答点） |
| **Evaluation** | 逐题评分，命中/遗漏/误解分析 | `EvaluationOutput`（分数、薄弱点、建议） |
| **Supervisor** | 校验引用有效性，生成最终报告 | Markdown 报告 |

Teaching Agent 内置 **Reflexion** 审校环节：生成讲解后由独立审校器检查引用有效性和覆盖度，不通过则修订后再次校验。

### 混合 RAG

- **ChromaDB 语义召回**：基于 `all-MiniLM-L6-v2` 本地 Embedding 的余弦相似度检索
- **BM25 关键词召回**：中英文分词 + 二元组，TF-IDF 加权
- **RRF 融合排序**：避免两路分数尺度不一致，按排名倒数分数聚合
- **主题相关性过滤**：确定性关键词匹配，防止返回主题无关的最近邻文档

### 学习闭环

```
选择专题 → 后台生成研学内容 → 阅读带引用讲解 → 5 题模拟面试
→ Evaluation Agent 评分 → 自动更新掌握度和薄弱点 → 针对性复习
```

- 掌握度只由**正式测评证据**更新，不支持手动打卡
- 薄弱点自动传入下一轮 Research、Teaching、Interview
- 支持多会话导师答疑，基于任务资料保留引用

### 工程可靠性

- 单并发异步队列，阶段级 90s 超时 + 1 次自动重试
- 重启自动标记中断任务，支持从失败阶段续跑
- SQLite WAL + 外键，任务、阶段、产物、评测、掌握度全持久化
- 论文检索失败回退本地资料，不阻断核心链路

## 快速开始

### 环境要求

Python 3.12+

### 安装

```bash
git clone https://github.com/jtq666/AgentMate.git
cd AgentMate
pip install -r requirements.txt
```

### 配置

复制 `.env.example` 为 `.env`，填入 OpenAI 兼容接口信息：

```env
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

### 启动

```bash
# 终端 1：后端
python run_server.py

# 终端 2：前端
streamlit run agentmate/frontend/app.py --server.port 8501
```

Windows 可双击 `start_backend.bat` 和 `start_frontend.bat`。

| 服务 | 地址 |
|------|------|
| 前端 | http://127.0.0.1:8501 |
| 后端 API | http://127.0.0.1:8000 |
| API 文档 | http://127.0.0.1:8000/docs |

## 内置专题

| 专题 | 检索查询 |
|------|---------|
| LLM Agent 基础 | Agent 智能体 定义 架构 自主决策 |
| ReAct | ReAct Thought Action Observation 推理 行动 观察 |
| 工具调用 | Agent 工具调用 Tool Calling Function Calling |
| 多 Agent 协作 | 多 Agent 多智能体 协作 通信 分工 |
| RAG | Agent RAG 检索增强生成 向量检索 |
| 记忆系统 | Agent 记忆 工作记忆 长期记忆 Memory |

支持自定义 AI Agent 相关主题（提交前检查范围与资料覆盖度）。

## API

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/study/topics/check` | 检查自定义主题范围与资料覆盖度 |
| POST | `/api/study/tasks` | 创建研学任务（异步，返回 202） |
| GET | `/api/study/tasks/{task_id}` | 查询任务阶段与产物 |
| POST | `/api/study/tasks/{task_id}/retry` | 从失败阶段重试 |
| POST | `/api/study/tasks/{task_id}/chat` | 基于任务资料带引用追问 |
| POST | `/api/study/tasks/{task_id}/assessments` | 提交 5 题答案进行评分 |
| GET | `/api/assessments/{assessment_id}` | 查询评分与掌握度 |
| GET | `/api/study/tasks/{task_id}/report` | 获取学习报告 |

## 测试

```bash
pip install -r requirements-dev.txt
pytest --cov=agentmate.study --cov-report=term-missing --cov-fail-under=80
```

## 对比实验

```bash
# 仅校验题集
python -m agentmate.benchmarks.run_benchmark

# 执行真实模型实验
python -m agentmate.benchmarks.run_benchmark --live
```

结果写入 `docs/evaluation/` 目录。

## 项目结构

```
agentmate/
├── api/              # FastAPI 后端
├── study/            # 领域模型、Agent、工作流、持久化
├── knowledge/        # 混合检索、论文 API、文档解析
├── frontend/         # Streamlit 四页前端
│   ├── app.py
│   ├── common.py
│   └── app_pages/    # 工作台、资料库、评测、报告
├── benchmarks/       # 24 题对比实验
└── data/             # 内置课程资料、SQLite、ChromaDB
```

## 技术栈

- **后端**：FastAPI + uvicorn + asyncio
- **前端**：Streamlit
- **检索**：ChromaDB（向量）+ BM25（关键词）+ RRF（融合）
- **Embedding**：sentence-transformers（all-MiniLM-L6-v2，本地）
- **数据库**：SQLite WAL
- **LLM**：任何 OpenAI 兼容接口

## License

MIT
