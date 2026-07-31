"""
EduAgent 完整演示
"""

import sys
import os
import io
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def section(title):
    print("\n" + "=" * 60)
    print("  %s" % title)
    print("=" * 60)


async def main():
    print("🎓 EduAgent v2 - 智能编程助教 完整演示\n")

    # ===== 1. 三层记忆 =====
    section("1. 三层记忆系统")
    from agentmate.memory import MemoryManager

    mm = MemoryManager(student_id="demo_student")
    conversations = [
        ("什么是递归？", "user", 0.8),
        ("递归是函数调用自身的技术", "assistant", 0.8),
        ("帮我看看代码", "user", 0.7),
        ("你的代码有除零风险", "assistant", 0.8),
        ("快排为什么比冒泡快", "user", 0.7),
        ("快排O(nlogn)冒泡O(n²)", "assistant", 0.8),
        ("链表怎么反转", "user", 0.6),
        ("链表反转用双指针", "assistant", 0.7),
        ("哈希表原理", "user", 0.6),
        ("哈希函数映射到桶", "assistant", 0.7),
        ("递归还是不太懂", "user", 0.5),
        ("给你举个阶乘的例子", "assistant", 0.8),
    ]
    for content, role, imp in conversations:
        mm.remember(content, role, importance=imp)

    print("  工作记忆: %d 条" % mm.working.size)
    print("  短期记忆: %d 条摘要" % len(mm.short_term._summaries))
    print("  长期记忆: %d 条" % len(mm.long_term._memories))

    print("\n  召回 '递归' 相关记忆:")
    for m in mm.recall("递归"):
        print("    [%s] %s" % (m["source"], m["content"][:40]))

    print("\n  学生画像:")
    profile = mm.long_term.get_profile("demo_student")
    print("    总记忆: %d 条" % profile["total"])
    if profile.get("topics"):
        print("    话题分布: %s" % profile["topics"])

    # ===== 2. 代码分析 =====
    section("2. 代码分析引擎")
    from agentmate.code_engine.analyzer import analyze_code, generate_report

    code = '''def divide(a, b):
    return a / b

def process(data):
    f = open('test.txt', 'r')
    result = data == None
    return result
'''
    r = analyze_code(code)
    print("  函数: %s" % r.functions)
    print("  圈复杂度: %d" % r.cyclomatic)
    print("  认知复杂度: %d" % r.cognitive)
    print("  Bug数量: %d" % len(r.bugs))
    for b in r.bugs:
        print("    [%s] L%d: %s" % (b["severity"], b["line"], b["message"]))

    # ===== 3. 知识检索 =====
    section("3. 知识检索 (RAG)")
    from agentmate.knowledge.retriever import KnowledgeBase
    from agentmate.knowledge.parser import parse_directory
    from pathlib import Path

    kb = KnowledgeBase()
    data_dir = Path(__file__).parent.parent / "data" / "sample_courses"
    if data_dir.exists():
        chunks = parse_directory(data_dir)
        for c in chunks:
            kb.add(c.content, c.source)
        print("  知识库: %d 个文档块" % kb.size)

        print("\n  检索 '递归':")
        for r in kb.search("递归", top_k=2):
            print("    [%.3f] %s..." % (r.score, r.content[:50]))

        print("\n  检索 '排序算法':")
        for r in kb.search("排序算法", top_k=2):
            print("    [%.3f] %s..." % (r.score, r.content[:50]))
    else:
        print("  数据目录不存在")

    # ===== 4. 意图路由 =====
    section("4. 意图路由")
    from agentmate.agents.coordinator import AgentCoordinator
    c = AgentCoordinator()
    queries = [
        "帮我看看这段代码有没有bug",
        "什么是递归",
        "我不懂二分查找",
        "```python\ndef f(): pass\n```",
    ]
    for q in queries:
        intent = c.classify_intent(q)
        print("  '%s' -> %s" % (q[:25], intent))

    # ===== 5. Agent 系统（接 LLM）=====
    section("5. Agent 系统 (ReAct + RAG)")
    from agentmate.agents.coordinator import AgentCoordinator
    from agentmate.agents.code_review import CodeReviewAgent
    from agentmate.agents.concept_qa import ConceptQAAgent
    from agentmate.agents.teaching import TeachingAgent
    from agentmate.agents.base import AgentState

    coordinator = AgentCoordinator()
    coordinator.register(CodeReviewAgent())
    coordinator.register(ConceptQAAgent(kb))
    coordinator.register(TeachingAgent())

    # 测试代码审查
    print("\n  [Code Review Agent]")
    state = AgentState(user_query="帮我审查这段代码")
    state.code = "def divide(a,b): return a/b\ndef f(): open('x.txt')"
    state = await coordinator.run(state)
    print("  回复: %s..." % state.response[:100])

    # 测试概念问答
    print("\n  [Concept QA Agent]")
    state2 = AgentState(user_query="什么是递归？")
    state2.intent = "concept_qa"
    state2 = await coordinator.run(state2)
    print("  回复: %s..." % state2.response[:100])

    # 测试教学
    print("\n  [Teaching Agent (ReAct)]")
    state3 = AgentState(user_query="二分查找我不太懂")
    state3.intent = "teaching"
    state3.memory_context = mm.recall("二分查找")
    state3 = await coordinator.run(state3)
    print("  回复: %s..." % state3.response[:150])
    if state3.teaching_thoughts:
        print("  ReAct思考步骤: %d" % len(state3.teaching_thoughts))

    section("演示完成 ✅")


if __name__ == "__main__":
    asyncio.run(main())
