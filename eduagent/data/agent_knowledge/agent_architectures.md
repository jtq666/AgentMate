# Agent 系统架构设计

## 单Agent vs 多Agent

### 单Agent
一个模型处理所有任务。简单但：
- 职责不清，一个Agent做太多事
- 难以扩展，加新能力需要重新调整个模型
- 工具管理混乱

### 多Agent
多个专业Agent各司其职。优势：
- 职责分离，每个Agent专注一个领域
- 可扩展，新Agent即插即用
- 独立优化，每个Agent可以有不同的工具和Prompt

## 工具注册机制

ToolRegistry 让 Agent 通过工具描述自主选择：
- 注册工具时提供名称、描述、参数说明
- LLM 读取所有工具描述后决定调用哪个
- 调用结果反馈给 LLM 影响下一步决策

类比：Function Calling。

## Agent 间通信

- **共享状态**：统一 AgentState 在 Agent 间传递
- **黑板模式**：一个 Agent 的结果写入共享区，另一个读取
- **消息传递**：结构化消息在 Agent 间传递

## 面试要点

1. 为什么需要多Agent？职责分离、可扩展、独立优化
2. ToolRegistry 的工作原理
3. Agent 间如何协作？共享状态 vs 消息传递
