# Agent 工具使用

## 什么是 Tool Use？

Agent 不只是聊天，还能调用外部工具完成具体任务。
类比 OpenAI 的 Function Calling——LLM 通过工具描述自主选择调用。

## ToolRegistry 模式

1. 注册工具：名称、描述、参数、执行函数
2. LLM 读取所有工具描述
3. LLM 决定调用哪个工具及传什么参数
4. 执行工具函数，返回结果给 LLM
5. LLM 根据结果决定下一步

## 面试要点

1. ToolRegistry vs Function Calling 的异同
2. 如何让 LLM 自主选择工具？提供工具描述
3. 工具调用的结果如何融入 LLM 上下文？Observation 注入
4. 如何避免 LLM 幻觉调用不存在的工具？注册校验
