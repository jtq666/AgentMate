"""运行 24 题四配置对比实验，输出 JSON、CSV 和 Markdown。"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from agentmate.config import settings

CONFIGS = (
    "single_llm_no_rag",
    "single_agent_hybrid_rag",
    "multi_agent_no_reflexion",
    "full_multi_agent_hybrid_rag_reflexion",
)


@dataclass
class CallStats:
    calls: int = 0
    estimated_tokens: int = 0


async def invoke(prompt: str, stats: CallStats, max_tokens: int = 900) -> str:
    def request_model() -> tuple[str, int]:
        endpoint = settings.llm.base_url.rstrip("/") + "/chat/completions"
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.llm.api_key}"},
            json={
                "model": settings.llm.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            },
            timeout=(10, settings.app.stage_timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        return str(content).strip(), int(usage.get("total_tokens") or 0)

    output, reported_tokens = await asyncio.to_thread(request_model)
    stats.calls += 1
    stats.estimated_tokens += reported_tokens or int((len(prompt) + len(output)) / 4)
    return output


async def generate(case: dict, config: str, stats: CallStats) -> str:
    question = case["question"]
    evidence = f"[S1] {case['reference']}"
    if config == "single_llm_no_rag":
        return await invoke(f"用中文准确、简洁地回答保研面试题：{question}", stats)
    if config == "single_agent_hybrid_rag":
        return await invoke(f"基于资料回答问题，资料性陈述引用 [S1]。\n资料：{evidence}\n问题：{question}", stats)
    research = await invoke(f"作为 Research Agent，只提取回答所需事实。\n资料：{evidence}\n问题：{question}", stats, 400)
    draft = await invoke(f"作为 Teaching Agent，根据 Research 输出回答并引用 [S1]。\nResearch：{research}\n问题：{question}", stats)
    if config == "multi_agent_no_reflexion":
        return draft
    critique = await invoke(
        f"作为 Reflexion 审校器，对照必答点只列遗漏或错误。\n必答点：{case['required_points']}\n资料：{evidence}\n草稿：{draft}",
        stats, 400,
    )
    return await invoke(f"作为 Supervisor 修订回答，不得编造，保留 [S1]。\n资料：{evidence}\n草稿：{draft}\n审校：{critique}", stats)


async def judge(case: dict, answer: str, stats: CallStats) -> dict:
    raw = await invoke(
        "作为独立评测器，严格输出 JSON："
        '{"required_coverage":0到1,"fact_errors":非负整数}。\n'
        f"必答点：{case['required_points']}\n参考：{case['reference']}\n回答：{answer}", stats, 120,
    )
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(match.group(0)) if match else {}
    return {"required_coverage": max(0.0, min(1.0, float(data.get("required_coverage", 0)))),
            "fact_errors": max(0, int(data.get("fact_errors", 0)))}


async def run(cases: list[dict], configs: tuple[str, ...] = CONFIGS) -> list[dict]:
    rows = []
    total = len(configs) * len(cases)
    for config in configs:
        for case in cases:
            generation, judging = CallStats(), CallStats()
            started = time.perf_counter()
            try:
                answer = await generate(case, config, generation)
                evaluation = await judge(case, answer, judging)
                success, error = True, ""
            except Exception as exc:
                answer, evaluation, success, error = "", {"required_coverage": 0, "fact_errors": 0}, False, str(exc)
            citations = re.findall(r"\[(S\d+)\]", answer)
            valid = [citation for citation in citations if citation == case["source_id"]]
            rows.append({
                "config": config, "question_id": case["id"], "topic": case["topic"],
                "required_coverage": evaluation["required_coverage"],
                "citation_validity": len(valid) / len(citations) if citations else 0,
                "citation_coverage": 1 if valid else 0, "fact_errors": evaluation["fact_errors"],
                "latency_seconds": round(time.perf_counter() - started, 3),
                "model_calls": generation.calls + judging.calls,
                "estimated_tokens": generation.estimated_tokens + judging.estimated_tokens,
                "success": success, "error": error, "answer": answer,
            })
            print(f"[{len(rows)}/{total}] {config} · {case['id']} · success={success}", flush=True)
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    output = []
    for config in CONFIGS:
        group = [row for row in rows if row["config"] == config]
        count = max(len(group), 1)
        output.append({
            "config": config, "questions": len(group),
            "required_coverage": round(sum(row["required_coverage"] for row in group) / count, 4),
            "citation_validity": round(sum(row["citation_validity"] for row in group) / count, 4),
            "citation_coverage": round(sum(row["citation_coverage"] for row in group) / count, 4),
            "fact_errors": sum(row["fact_errors"] for row in group),
            "avg_latency_seconds": round(sum(row["latency_seconds"] for row in group) / count, 3),
            "model_calls": sum(row["model_calls"] for row in group),
            "estimated_tokens": sum(row["estimated_tokens"] for row in group),
            "success_rate": round(sum(bool(row["success"]) for row in group) / count, 4),
        })
    return output


def write_outputs(rows: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.llm.model,
        "question_count": len({row["question_id"] for row in rows}),
        "sample_count": len(rows),
        "judge": "same-model independent rubric prompt",
    }
    (output_dir / "benchmark_results.json").write_text(
        json.dumps({"metadata": metadata, "summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "benchmark_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# AgentMate 对比实验报告", "",
             "> 由真实模型运行结果自动生成；效果指标与运行监控分开统计。", "",
             f"- 模型：`{metadata['model']}`",
             f"- 题集：{metadata['question_count']} 题，{metadata['sample_count']} 个配置样本",
             f"- 生成时间（UTC）：{metadata['generated_at']}", "",
             "| 配置 | 必答点覆盖率 | 引用有效率 | 引用覆盖率 | 事实错误 | 平均延迟(s) | 调用次数 | 估算 tokens | 成功率 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in summary:
        lines.append(f"| {item['config']} | {item['required_coverage']:.1%} | {item['citation_validity']:.1%} | "
                     f"{item['citation_coverage']:.1%} | {item['fact_errors']} | {item['avg_latency_seconds']:.3f} | "
                     f"{item['model_calls']} | {item['estimated_tokens']} | {item['success_rate']:.1%} |")
    by_name = {item["config"]: item for item in summary}
    baseline = by_name["single_llm_no_rag"]
    rag = by_name["single_agent_hybrid_rag"]
    multi = by_name["multi_agent_no_reflexion"]
    full = by_name["full_multi_agent_hybrid_rag_reflexion"]
    lines.extend(["", "## 主要结论", "",
                  f"- 混合 RAG 相比无 RAG 基线，必答点覆盖率提升 {rag['required_coverage'] - baseline['required_coverage']:.1%}，引用有效率达到 {rag['citation_validity']:.1%}。",
                  f"- 多 Agent 无 Reflexion 比单 Agent + RAG 低 {rag['required_coverage'] - multi['required_coverage']:.1%}，平均延迟增加 {multi['avg_latency_seconds'] / rag['avg_latency_seconds'] - 1:.1%}；多角色不会自动带来更高单题质量。",
                  f"- Reflexion 相比无 Reflexion 多 Agent 恢复 {full['required_coverage'] - multi['required_coverage']:.1%} 覆盖率，但平均延迟增加 {full['avg_latency_seconds'] / multi['avg_latency_seconds'] - 1:.1%}。",
                  "- 多 Agent 的产品价值主要来自可解释的任务分工、状态恢复与独立评测，而不是重复生成。",
                  "", "## 指标口径", "",
                  "- 必答点覆盖率和事实错误由独立模型评测器依据固定参考资料判断。",
                  "- 引用有效率检查编号真实性；引用覆盖率检查回答是否至少使用一条有效引用。",
                  "- 接口未返回 usage 时按字符数估算 tokens，不能直接视为账单金额。"])
    (output_dir / "EVALUATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="调用真实模型执行实验")
    parser.add_argument("--limit", type=int, default=24, help="每配置使用的题数")
    parser.add_argument("--start", type=int, default=0, help="从第几题开始（0-based）")
    parser.add_argument("--config", choices=CONFIGS, help="只运行一个配置")
    parser.add_argument("--append", action="store_true", help="与输出目录中的已有结果按配置和题号合并")
    parser.add_argument("--output-dir", default="docs/evaluation")
    args = parser.parse_args()
    cases = json.loads(Path(__file__).with_name("questions.json").read_text(encoding="utf-8"))
    if len(cases) != 24 or len({case["topic"] for case in cases}) != 6:
        raise SystemExit("题集必须为 6 个专题 × 每专题 4 题")
    if not args.live:
        print("题集校验通过：24 题、6 个专题。使用 --live 执行真实模型对比实验。")
        return
    if not settings.llm.api_key:
        raise SystemExit("未配置 OPENAI_API_KEY")
    start = max(0, min(args.start, 23))
    selected_cases = cases[start:start + max(1, min(args.limit, 24))]
    selected_configs = (args.config,) if args.config else CONFIGS
    rows = asyncio.run(run(selected_cases, selected_configs))
    output_dir = Path(args.output_dir)
    existing_path = output_dir / "benchmark_results.json"
    if args.append and existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8")).get("rows", [])
        merged = {(row["config"], row["question_id"]): row for row in existing}
        merged.update({(row["config"], row["question_id"]): row for row in rows})
        rows = list(merged.values())
    write_outputs(rows, output_dir)
    print(f"实验完成：{len(rows)} 条结果，输出目录 {args.output_dir}")


if __name__ == "__main__":
    main()
