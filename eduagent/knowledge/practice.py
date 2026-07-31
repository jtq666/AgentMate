"""
练习题系统

功能：
1. 内置题库（按知识点分类）
2. 根据学生薄弱点推荐题目
3. LLM 自动生成新题目
4. 提交答案后自动批改

面试深度点：
- 题目推荐算法（基于学生画像 + 知识点掌握度）
- 自适应难度调整
- 答题记录追踪
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Problem:
    """一道题目"""
    id: str
    title: str
    description: str
    topic: str          # 知识点
    difficulty: str     # easy / medium / hard
    starter_code: str = ""
    test_input: str = ""
    expected_output: str = ""
    hint: str = ""
    explanation: str = ""


@dataclass
class Submission:
    """学生提交"""
    problem_id: str
    code: str
    output: str = ""
    expected: str = ""
    passed: bool = False
    timestamp: float = 0.0


# ==================== 题库 ====================

PROBLEM_BANK: list[Problem] = [
    Problem(
        id="cpp_001", title="Hello World",
        description="编写一个C++程序，输出 Hello World!",
        topic="基础语法", difficulty="easy",
        starter_code='#include <iostream>\nusing namespace std;\nint main(){\n    // 在这里编写代码\n    return 0;\n}',
        expected_output="Hello World!",
        hint="使用 cout 输出字符串",
    ),
    Problem(
        id="cpp_002", title="两数之和",
        description="给定一个整数数组和一个目标值，找出数组中和为目标值的两个数的下标。",
        topic="数组", difficulty="easy",
        starter_code='vector<int> twoSum(vector<int>& nums, int target) {\n    // 实现你的代码\n}',
        hint="可以用哈希表优化到 O(n)",
    ),
    Problem(
        id="cpp_003", title="反转链表",
        description="反转一个单链表。",
        topic="链表", difficulty="medium",
        starter_code='struct ListNode {\n    int val;\n    ListNode* next;\n    ListNode(int x) : val(x), next(nullptr) {}\n};\nListNode* reverseList(ListNode* head) {\n    // 实现你的代码\n}',
        hint="用三个指针：prev, curr, next",
    ),
    Problem(
        id="cpp_004", title="二分查找",
        description="在有序数组中查找目标值，返回下标。",
        topic="搜索", difficulty="easy",
        starter_code='int binarySearch(vector<int>& arr, int target) {\n    // 实现你的代码\n}',
        hint="注意 left <= right 还是 left < right",
    ),
    Problem(
        id="cpp_005", title="快速排序",
        description="实现快速排序算法。",
        topic="排序", difficulty="medium",
        starter_code='void quickSort(vector<int>& arr, int lo, int hi) {\n    // 实现你的代码\n}',
        hint="选择基准元素，分区，递归",
    ),
    Problem(
        id="cpp_006", title="二叉树层序遍历",
        description="实现二叉树的层序遍历（BFS）。",
        topic="树", difficulty="medium",
        starter_code='struct TreeNode {\n    int val;\n    TreeNode *left, *right;\n};\nvector<vector<int>> levelOrder(TreeNode* root) {\n    // 实现你的代码\n}',
        hint="用队列，逐层处理",
    ),
    Problem(
        id="cpp_007", title="最长不重复子串",
        description="给定一个字符串，找出最长的不含重复字符的子串长度。",
        topic="字符串", difficulty="medium",
        starter_code='int lengthOfLongestSubstring(string s) {\n    // 实现你的代码\n}',
        hint="滑动窗口 + 哈希表",
    ),
    Problem(
        id="cpp_008", title="0-1背包",
        description="给定物品重量和价值，以及背包容量，求最大价值。",
        topic="动态规划", difficulty="hard",
        starter_code='int knapsack(vector<int>& wt, vector<int>& val, int W) {\n    // 实现你的代码\n}',
        hint="dp[i][w] = 前i个物品容量w的最大价值",
    ),
    Problem(
        id="cpp_009", title="LRU缓存",
        description="设计一个LRU缓存，支持get和put操作，时间复杂度O(1)。",
        topic="设计", difficulty="hard",
        starter_code='class LRUCache {\npublic:\n    LRUCache(int capacity) {}\n    int get(int key) {}\n    void put(int key, int value) {}\n};',
        hint="双向链表 + 哈希表",
    ),
    Problem(
        id="cpp_010", title="斐波那契数列",
        description="计算斐波那契数列第n项。",
        topic="递归", difficulty="easy",
        starter_code='int fibonacci(int n) {\n    // 实现你的代码\n}',
        hint="注意递归终止条件，考虑动态规划优化",
    ),
    Problem(
        id="cpp_011", title="合并两个有序链表",
        description="将两个有序链表合并为一个新的有序链表。",
        topic="链表", difficulty="easy",
        starter_code='ListNode* mergeTwoLists(ListNode* l1, ListNode* l2) {\n    // 实现你的代码\n}',
        hint="比较两个链表头节点，选小的接入结果",
    ),
    Problem(
        id="cpp_012", title="最大子数组和",
        description="找到一个连续子数组，使其和最大。",
        topic="动态规划", difficulty="medium",
        starter_code='int maxSubArray(vector<int>& nums) {\n    // 实现你的代码\n}',
        hint="Kadane算法：dp[i] = max(nums[i], dp[i-1]+nums[i])",
    ),
]


# ==================== 题库管理 ====================

class ProblemBank:
    """题库管理"""

    def __init__(self):
        self._problems = {p.id: p for p in PROBLEM_BANK}

    def get_all(self) -> list[Problem]:
        return list(self._problems.values())

    def get_by_topic(self, topic: str) -> list[Problem]:
        return [p for p in self._problems.values() if p.topic == topic]

    def get_by_difficulty(self, difficulty: str) -> list[Problem]:
        return [p for p in self._problems.values() if p.difficulty == difficulty]

    def get_random(self, n: int = 1, topic: str = None, difficulty: str = None) -> list[Problem]:
        """随机获取题目，可按知识点和难度筛选"""
        candidates = list(self._problems.values())
        if topic:
            candidates = [p for p in candidates if p.topic == topic]
        if difficulty:
            candidates = [p for p in candidates if p.difficulty == difficulty]
        return random.sample(candidates, min(n, len(candidates)))

    def recommend(self, weak_topics: list[str], n: int = 3) -> list[Problem]:
        """
        根据薄弱知识点推荐题目。

        推荐策略：
        1. 薄弱知识点的题目优先
        2. 从 easy 到 hard 渐进
        """
        recommended = []

        # 先推荐薄弱知识点的 easy 题
        for topic in weak_topics:
            easy = [p for p in self._problems.values()
                    if p.topic == topic and p.difficulty == "easy" and p.id not in [r.id for r in recommended]]
            recommended.extend(easy[:1])

        # 再推荐 medium
        for topic in weak_topics:
            medium = [p for p in self._problems.values()
                      if p.topic == topic and p.difficulty == "medium" and p.id not in [r.id for r in recommended]]
            recommended.extend(medium[:1])

        # 最后补充
        remaining = [p for p in self._problems.values() if p.id not in [r.id for r in recommended]]
        recommended.extend(random.sample(remaining, min(n - len(recommended), len(remaining))))

        return recommended[:n]


# ==================== 答题记录 ====================

class PracticeTracker:
    """答题追踪"""

    def __init__(self, storage_dir: str = "eduagent/data/practice"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, list[dict]] = {}
        self._load()

    def record_submission(self, student_id: str, submission: Submission):
        """记录提交"""
        if student_id not in self._records:
            self._records[student_id] = []
        self._records[student_id].append({
            "problem_id": submission.problem_id,
            "code": submission.code[:500],
            "passed": submission.passed,
            "timestamp": submission.timestamp or time.time(),
        })
        self._save()

    def get_student_stats(self, student_id: str) -> dict:
        """获取学生答题统计"""
        records = self._records.get(student_id, [])
        if not records:
            return {"total": 0, "passed": 0, "topics": {}}

        total = len(records)
        passed = sum(1 for r in records if r["passed"])

        # 按题目统计
        topic_stats = {}
        for r in records:
            problem = PROBLEM_BANK_MAP.get(r["problem_id"])
            if problem:
                topic = problem.topic
                if topic not in topic_stats:
                    topic_stats[topic] = {"total": 0, "passed": 0}
                topic_stats[topic]["total"] += 1
                if r["passed"]:
                    topic_stats[topic]["passed"] += 1

        return {
            "total": total,
            "passed": passed,
            "accuracy": passed / total if total > 0 else 0,
            "topics": topic_stats,
        }

    def get_weak_topics(self, student_id: str) -> list[str]:
        """获取薄弱知识点"""
        stats = self.get_student_stats(student_id)
        weak = []
        for topic, s in stats.get("topics", {}).items():
            if s["passed"] / s["total"] < 0.6:
                weak.append(topic)
        return weak

    def _save(self):
        path = self._dir / "records.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)

    def _load(self):
        path = self._dir / "records.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._records = json.load(f)


# 快速查找
PROBLEM_BANK_MAP = {p.id: p for p in PROBLEM_BANK}
