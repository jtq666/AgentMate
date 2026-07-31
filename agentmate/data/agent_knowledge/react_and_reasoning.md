# ReAct 推理与行动

## 什么是 ReAct？

ReAct（Reasoning + Acting）是让 Agent 结合推理和行动的一种范式。
核心思想：Agent 不只是一次性给答案，而是通过：
- **Thought（思考）**：分析当前情况，决定下一步
- **Action（行动）**：执行操作（调用工具、查询知识库）
- **Observation（观察）**：观察操作结果
- 循环上述步骤直到得出答案

## 为什么需要 ReAct？

1. 复杂问题需要多步推理，单步回答不够
2. Agent 需要根据中间结果调整策略
3. 需要访问外部信息（工具调用）

## 实现方式

```
for step in range(max_steps):
    thought = llm.think("基于已有信息，下一步做什么？")
    if thought == "信息足够，可以回答":
        return llm.answer()
    action = parse_action(thought)  # 需要调用哪个工具
    observation = tool_call(action)
    context += observation  # 新信息加入上下文
```

## 面试要点

1. ReAct 和普通 LLM 问答的区别：ReAct 有自主的工具调用循环
2. ToolRegistry：Agent 通过工具描述自主选择工具
3. 多步推理 vs 单步回答：复杂问题的优势
4. 如何防止 Agent 陷入无限循环：max_steps 限制
