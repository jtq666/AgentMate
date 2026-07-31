"""
代码分析引擎

只做客观度量，不做模式匹配：
1. 函数/类/头文件解析
2. 圈复杂度 / 认知复杂度
3. 代码结构信息

Bug 检测交给 LLM Agent 做语义分析，不硬编码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FuncInfo:
    """函数级信息"""
    name: str
    lines: int = 0
    args: list[str] = field(default_factory=list)
    cyclomatic: int = 1
    has_docstring: bool = False
    complexity_level: str = "低"


@dataclass
class CodeMetrics:
    """代码度量指标"""
    language: str = "python"
    total_lines: int = 0
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    cyclomatic: int = 1
    cognitive: int = 0
    nesting: int = 0
    func_details: list[FuncInfo] = field(default_factory=list)  # 函数级分析

    def to_dict(self) -> dict:
        return {
            "language": self.language, "total_lines": self.total_lines,
            "functions": self.functions, "classes": self.classes,
            "cyclomatic": self.cyclomatic, "cognitive": self.cognitive,
            "nesting": self.nesting,
        }

    def summary(self) -> str:
        if self.cyclomatic <= 5:
            level = "低"
        elif self.cyclomatic <= 10:
            level = "中"
        else:
            level = "高"
        parts = [
            f"语言: {self.language}",
            f"行数: {self.total_lines}",
            f"函数: {', '.join(self.functions) if self.functions else '无'}",
            f"类: {', '.join(self.classes) if self.classes else '无'}",
            f"圈复杂度: {self.cyclomatic} ({level})",
            f"认知复杂度: {self.cognitive}",
            f"嵌套深度: {self.nesting}",
        ]
        return "\n".join(parts)


def analyze_code(code: str, language: str = "python") -> CodeMetrics:
    """分析代码，返回度量指标"""
    m = CodeMetrics(language=language, total_lines=code.count("\n") + 1)
    _parse_structure(code, m)
    _compute_complexity(code, m)
    return m


def detect_language(code: str) -> str:
    """自动检测编程语言"""
    cpp_hints = [
        r"#include\s*<", r"using\s+namespace", r"std::",
        r"\bcout\b", r"\bcin\b", r"\bnullptr\b",
        r"\bvector\s*<", r"\btemplate\s*<",
        r"\bint\s*\*\s*\w+",         # int* p
        r"\bnew\s+\w+",              # new int
        r"\bdelete\b",               # delete
        r"\bint\s+main\b",           # int main
        r"->",                       # p->func()
        r"\bprintf\b", r"\bscanf\b", # C functions
        r"::",                       # scope
    ]
    for h in cpp_hints:
        if re.search(h, code):
            return "cpp"
    java_hints = [r"\bpublic\s+class\b", r"\bSystem\.out", r"\bimport\s+java\."]
    for h in java_hints:
        if re.search(h, code):
            return "java"
    py_hints = [r"^\s*def\s+\w+", r"^\s*class\s+\w+", r"self\."]
    for h in py_hints:
        if re.search(h, code, re.MULTILINE):
            return "python"
    return "python"


# ==================== 内部实现 ====================

def _parse_structure(code: str, m: CodeMetrics):
    """提取函数/类/导入 + 函数级分析"""
    lines = code.split("\n")

    if m.language == "python":
        for match in re.finditer(r"^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", code, re.MULTILINE):
            name = match.group(1)
            args = [a.strip().split(":")[0].split("=")[0]
                    for a in match.group(2).split(",") if a.strip() and a.strip() != "self"]
            m.functions.append(name)
            # 函数级分析
            start_line = code[:match.start()].count("\n")
            # 找函数结束行（下一个 def 或 class 或文件末尾）
            end_line = len(lines)
            for j in range(start_line + 1, len(lines)):
                if re.match(r"^\s*(?:def|class)\s", lines[j]):
                    end_line = j
                    break
            func_body = "\n".join(lines[start_line:end_line])
            func_cc = 1 + sum(1 for kw in [r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b", r"\band\b", r"\bor\b"]
                              for _ in re.findall(kw, func_body))
            docstring = '"""' in func_body or "'''" in func_body
            level = "低" if func_cc <= 3 else "中" if func_cc <= 8 else "高"
            m.func_details.append(FuncInfo(
                name=name, lines=end_line - start_line, args=args,
                cyclomatic=func_cc, has_docstring=docstring, complexity_level=level,
            ))

        for match in re.finditer(r"^class\s+(\w+)", code, re.MULTILINE):
            m.classes.append(match.group(1))
        for match in re.finditer(r"^(?:from\s+\S+\s+)?import\s+(.+)$", code, re.MULTILINE):
            m.imports.append(match.group(0).strip())

    elif m.language == "cpp":
        for match in re.finditer(
            r"(?:[\w:*&<>]+\s+)+(\w+)\s*\(([^)]*)\)\s*(?:const\s*)?\{", code, re.MULTILINE
        ):
            name = match.group(1)
            if name not in ("if", "for", "while", "switch", "catch", "else", "class", "struct", "do"):
                m.functions.append(name)
                args = [a.strip().split()[-1].strip("*&")
                        for a in match.group(2).split(",") if a.strip()]
                start_line = code[:match.start()].count("\n")
                end_line = len(lines)
                brace_count = 0
                for j in range(start_line, len(lines)):
                    for ch in lines[j]:
                        if ch == '{': brace_count += 1
                        elif ch == '}': brace_count -= 1
                    if brace_count == 0 and j > start_line:
                        end_line = j + 1
                        break
                func_body = "\n".join(lines[start_line:end_line])
                func_cc = 1 + sum(1 for kw in [r"\bif\b", r"\bfor\b", r"\bwhile\b", r"\bcase\b"]
                                  for _ in re.findall(kw, func_body))
                level = "低" if func_cc <= 3 else "中" if func_cc <= 8 else "高"
                m.func_details.append(FuncInfo(
                    name=name, lines=end_line - start_line, args=args,
                    cyclomatic=func_cc, complexity_level=level,
                ))

        for match in re.finditer(r"(?:class|struct)\s+(\w+)", code):
            m.classes.append(match.group(1))
        for match in re.finditer(r"#include\s*[<\"](.+?)[>\"]", code):
            m.imports.append(match.group(1))

    elif m.language == "java":
        for match in re.finditer(r"(?:public|private|protected)\s+(?:static\s+)?\w+\s+(\w+)\s*\(([^)]*)\)", code):
            name = match.group(1)
            if name not in ("if", "for", "while", "main"):
                m.functions.append(name)
                args = [a.strip().split()[-1] for a in match.group(2).split(",") if a.strip()]
                m.func_details.append(FuncInfo(name=name, args=args))
        for match in re.finditer(r"class\s+(\w+)", code):
            m.classes.append(match.group(1))


def _compute_complexity(code: str, m: CodeMetrics):
    """计算圈复杂度 + 认知复杂度"""
    keywords = [r"\bif\b", r"\bfor\b", r"\bwhile\b", r"\bcatch\b",
                r"\b\?\s*:", r"&&", r"\|\|"]
    if m.language == "python":
        keywords += [r"\belif\b", r"\band\b", r"\bor\b", r"\bexcept\b"]
    elif m.language == "cpp":
        keywords += [r"\belse\s+if\b", r"\bcase\b"]
    elif m.language == "java":
        keywords += [r"\belse\s+if\b", r"\bcase\b"]

    for kw in keywords:
        m.cyclomatic += len(re.findall(kw, code))

    # 认知复杂度
    level = 0
    for line in code.split("\n"):
        s = line.strip()
        if re.search(r"\b(if|elif|else if|for|while|try|catch)\b", s):
            level += 1
            m.cognitive += level
        if re.search(r"\b(break|continue|return|throw|raise)\b", s):
            m.cognitive += 1

    # 嵌套深度
    depth = 0
    for ch in code:
        if ch in "({[":
            depth += 1
            m.nesting = max(m.nesting, depth)
        elif ch in ")}]":
            depth = max(0, depth - 1)


def generate_metrics_report(metrics: CodeMetrics) -> str:
    """生成度量报告文本"""
    return f"""## 代码度量

{metrics.summary()}

---
*注：以上为客观度量指标。Bug 检测和逻辑分析由 AI Agent 完成。*"""
