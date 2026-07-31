"""
论文检索 API — arXiv + Semantic Scholar + 质量筛选

面试讲点：
- 工具使用：Agent 调用外部 API
- 质量评估：引用数、年份作为论文质量指标
- 批量筛选：用户可选择感兴趣的论文入库存
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
import json
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Paper:
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    year: int = 0
    citations: int = 0       # 引用数（质量指标）
    venue: str = ""           # 发表会议/期刊
    url: str = ""
    pdf_url: str = ""
    arxiv_id: str = ""
    source: str = "arxiv"
    selected: bool = False    # 用户是否选中入库

    @property
    def quality_score(self) -> int:
        """质量评分：引用数 + 顶级会议加分"""
        score = self.citations
        top_venues = ["NeurIPS", "ICML", "ICLR", "ACL", "EMNLP", "NAACL",
                       "CVPR", "ICCV", "AAAI", "IJCAI", "KDD", "WWW",
                       "SIGIR", "OSDI", "SOSP", "PLDI", "POPL", "ICSE"]
        if any(v in (self.venue or "") for v in top_venues):
            score += 50
        return score

    def to_markdown(self) -> str:
        quality = "⭐" if self.quality_score >= 100 else "●" if self.quality_score >= 10 else "○"
        lines = []
        lines.append(f"### {quality} {self.title}")
        lines.append(f"**作者**: {', '.join(self.authors[:5])}")
        details = []
        if self.year:
            details.append(f"📅 {self.year}")
        if self.citations:
            details.append(f"📊 引用 {self.citations}")
        if self.venue:
            details.append(f"📍 {self.venue}")
        lines.append(" | ".join(details))
        if self.abstract:
            lines.append(f"**摘要**: {self.abstract[:300]}")
        if self.arxiv_id:
            lines.append(f"**arXiv**: {self.arxiv_id}")
        return "\n".join(lines)


def search_semantic_scholar(query: str, max_results: int = 10,
                             min_year: int = 0, min_citations: int = 0) -> list[Paper]:
    """
    搜索 Semantic Scholar（推荐：有引用数、会议信息）
    """
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search?"
        f"query={urllib.parse.quote(query)}"
        f"&limit={max_results}"
        f"&fields=title,authors,abstract,year,citationCount,venue,externalIds,url"
    )
    if min_year:
        url += f"&year={min_year}-"
    import time as _time
    for attempt in range(5):
        try:
            import os
            headers = {"User-Agent": "EduAgent/1.0"}
            key = os.getenv("S2_API_KEY", "")
            if key: headers["x-api-key"] = key
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return _parse_semantic(data, min_citations)
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limit
                wait = 3 * (2 ** attempt)  # 3s, 6s, 12s, 24s, 48s
                logger.info(f"Semantic Scholar 限流，等待 {wait}s 重试...")
                _time.sleep(wait)
                continue
            logger.warning(f"Semantic Scholar HTTP {e.code}: {e}")
            break
        except Exception as e:
            if attempt < 4:
                _time.sleep(1)
                continue
            logger.warning(f"Semantic Scholar 搜索失败(重试5次): {e}")
    return []


def search_arxiv(query: str, max_results: int = 10) -> list[Paper]:
    """
    搜索 arXiv（备选：没有引用数，但有全文 PDF）
    """
    url = (
        f"http://export.arxiv.org/api/query?"
        f"search_query=all:{urllib.parse.quote(query)}"
        f"&start=0&max_results={max_results}&sortBy=relevance"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EduAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return _parse_arxiv_xml(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"arXiv 搜索失败: {e}")
        return []


def search_papers(query: str, max_results: int = 8,
                  min_year: int = 2020, min_citations: int = 0) -> list[Paper]:
    """
    统一搜索入口：Semantic Scholar 优先（有质量信息），arXiv 补充。

    Args:
        query: 搜索关键词
        max_results: 最大返回数
        min_year: 最早年份（默认 2020 排除过时论文）
        min_citations: 最少引用数
    """
    papers = search_semantic_scholar(query, max_results, min_year, min_citations)
    if len(papers) < 3:
        arxiv_papers = search_arxiv(query, max_results - len(papers))
        papers += arxiv_papers
    return papers[:max_results]


def _parse_semantic(data: dict, min_citations: int = 0) -> list[Paper]:
    papers = []
    for item in data.get("data", []):
        citations = item.get("citationCount", 0)
        if citations < min_citations:
            continue
        authors = [a.get("name", "") for a in item.get("authors", [])]
        year = item.get("year", 0) or 0
        venue = item.get("venue", "") or ""
        arxiv_id = ""
        ext_ids = item.get("externalIds", {}) or {}
        if "ArXiv" in ext_ids:
            arxiv_id = ext_ids["ArXiv"]
        papers.append(Paper(
            title=item.get("title", ""), authors=authors,
            abstract=item.get("abstract", "") or "",
            year=year, citations=citations, venue=venue,
            url=item.get("url", ""), arxiv_id=arxiv_id,
            source="semantic_scholar",
        ))
    return papers


def _parse_arxiv_xml(xml_text: str) -> list[Paper]:
    import xml.etree.ElementTree as ET
    papers = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(xml_text)
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            title_text = title.text.strip().replace("\n", " ") if title is not None else ""
            authors = [a.find("atom:name", ns).text
                      for a in entry.findall("atom:author", ns)
                      if a.find("atom:name", ns) is not None]
            abstract = entry.find("atom:summary", ns)
            abstract_text = abstract.text.strip().replace("\n", " ") if abstract is not None else ""
            url = entry.find("atom:id", ns)
            url_text = url.text.strip() if url is not None else ""
            arxiv_id = url_text.split("/abs/")[-1] if "/abs/" in url_text else url_text
            papers.append(Paper(
                title=title_text, authors=authors, abstract=abstract_text,
                url=url_text, pdf_url=url_text.replace("/abs/", "/pdf/") if url_text else "",
                arxiv_id=arxiv_id, source="arxiv",
            ))
    except Exception:
        pass
    return papers
