"""
EduAgent 测试套件
"""

import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print("  [PASS] %s %s" % (name, detail))
        passed += 1
    else:
        print("  [FAIL] %s %s" % (name, detail))
        failed += 1


def main():
    print("=" * 50)
    print("  EduAgent v2 测试套件")
    print("=" * 50)

    # ===== 1. 三层记忆 =====
    print("\n--- 三层记忆系统 ---")
    from agentmate.memory import MemoryManager
    mm = MemoryManager(student_id="test_student")

    mm.remember("什么是递归？", "user", 0.5)
    mm.remember("递归是函数调用自身", "assistant", 0.6)
    mm.remember("快速排序怎么做", "user", 0.5)
    mm.remember("快排用分治思想", "assistant", 0.6)
    test("工作记忆写入", mm.working.size == 4, "(%d条)" % mm.working.size)

    ctx = mm.get_context()
    test("上下文组装", len(ctx) > 0, "(%d条)" % len(ctx))

    recall = mm.recall("递归")
    test("记忆召回", len(recall) > 0, "(%d条)" % len(recall))

    stats = mm.get_stats()
    test("记忆统计", "working" in stats and "short_term" in stats)

    # 测试溢出压缩
    for i in range(15):
        mm.remember("测试消息%d" % i, "user", 0.3)
    test("短期记忆压缩", mm.short_term._summaries is not None)

    # ===== 2. 代码分析 =====
    print("\n--- 代码分析引擎 ---")
    from agentmate.code_engine.analyzer import analyze_code, detect_language
    code = '''#include <iostream>
using namespace std;

int divide(int a, int b) {
    return a / b;
}

void process() {
    FILE* f = fopen("test.txt", "r");
    int x = 0;
    if (x > 0) { for(int i=0;i<10;i++){} }
}

int* dangling() {
    int x = 42;
    return &x;
}

int main() {
    int arr[10];
    arr[10] = 0;
    return 0;
}
'''
    r = analyze_code(code, language="cpp")
    test("语言检测", detect_language(code) == "cpp")
    test("函数提取", len(r.functions) >= 2, "(%s)" % r.functions)
    test("圈复杂度", r.cyclomatic > 1, "(%d)" % r.cyclomatic)
    test("认知复杂度", r.cognitive > 0, "(%d)" % r.cognitive)
    test("嵌套深度", r.nesting > 0, "(%d)" % r.nesting)

    # ===== 3. 知识检索 =====
    print("\n--- 知识检索 (RAG) ---")
    from agentmate.knowledge.retriever import KnowledgeBase
    kb = KnowledgeBase()
    kb.add("递归是函数调用自身的编程技术")
    kb.add("快速排序使用分治思想，平均时间复杂度O(nlogn)")
    kb.add("链表通过指针连接节点")
    kb.add("哈希表通过哈希函数实现O(1)查找")
    test("知识库大小", kb.size >= 4, "(%d)" % kb.size)

    results = kb.search("什么是递归")
    test("向量检索", len(results) > 0, "(%d条)" % len(results))

    bm25 = kb.bm25_search("递归")
    test("BM25检索", len(bm25) > 0, "(%d条)" % len(bm25))

    rrf = kb.search("排序算法")
    test("RRF融合", len(rrf) > 0, "(%d条)" % len(rrf))

    # ===== 4. 意图路由（LLM驱动，测试回退规则）=====
    print("\n--- 意图路由 ---")
    from agentmate.agents.coordinator import AgentCoordinator
    c = AgentCoordinator()
    test("分类-出题", c._rule_fallback("出一道面试题", "") == "practice")
    test("分类-概念", c._rule_fallback("什么是ReAct", "") == "concept_qa")
    test("分类-教学", c._rule_fallback("我不太懂", "") == "teaching")
    test("分类-论文", c._rule_fallback("搜索论文", "") == "paper_search")

    # ===== 5. 文档解析 =====
    print("\n--- 文档解析 ---")
    from agentmate.knowledge.parser import parse_file, parse_directory
    from pathlib import Path
    data_dir = Path(__file__).parent.parent / "data" / "agent_knowledge"
    if data_dir.exists():
        chunks = parse_directory(data_dir)
        test("目录解析", len(chunks) > 5, "(%d个分块)" % len(chunks))

        md_chunks = parse_file(data_dir / "react_and_reasoning.md")
        test("单文件解析", len(md_chunks) > 3, "(%d个分块)" % len(md_chunks))
    else:
        test("数据目录", False, "(不存在)")

    # ===== 6. Agent 基类 =====
    print("\n--- Agent 基类 ---")
    from agentmate.agents.base import AgentState, BaseAgent
    state = AgentState(user_query="测试", code="x = 1")
    state.log("test", "message")
    test("AgentState", len(state.execution_log) == 1)

    # ===== 结果 =====
    print("\n" + "=" * 50)
    print("  结果: %d 通过, %d 失败" % (passed, failed))
    print("=" * 50)


if __name__ == "__main__":
    main()
