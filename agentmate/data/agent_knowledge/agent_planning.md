# Agent 规划能力

## 什么是 Agent Planning？

Agent 在行动之前先制定计划，然后逐步执行。
比 ReAct 更结构化：ReAct 是"走一步看一步"，Planning 是"先规划再走"。

## Plan-and-Execute 模式

```
用户请求 → LLM 生成执行计划(步骤列表)
        → 逐步执行每个步骤
        → 每步结果作为下一步输入
        → 动态调整（根据结果修正后续计划）
```

## 面试要点

1. ReAct vs Plan-and-Execute 的区别
2. 如何生成执行计划？LLM 基于可用工具生成
3. 执行中如何动态调整计划？观察反馈+
4. 步骤间有依赖怎么办？context 传递
