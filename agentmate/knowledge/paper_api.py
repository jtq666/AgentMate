"""Semantic Scholar 与 arXiv 论文检索。"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Paper:
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    year: int = 0
    citations: int = 0
    venue: str = ""
    url: str = ""
    pdf_url: str = ""
    arxiv_id: str = ""
    source: str = "arxiv"

    @property
    def quality_score(self) -> int:
        top_venues = {"NeurIPS", "ICML", "ICLR", "ACL", "EMNLP", "NAACL", "AAAI", "IJCAI"}
        return self.citations + (50 if any(name in self.venue for name in top_venues) else 0)


def search_semantic_scholar(query: str, max_results: int = 10,
                             min_year: int = 0, max_year: int = 0,
                             min_citations: int = 0) -> list[Paper]:
    fields = "title,authors,abstract,year,citationCount,venue,externalIds,url"
    url = ("https://api.semanticscholar.org/graph/v1/paper/search?"
           f"query={urllib.parse.quote(query)}&limit={max_results}&fields={fields}")
    if min_year or max_year:
        url += f"&year={min_year or 1900}-{max_year or 2100}"
    headers = {"User-Agent": "AgentMate/1.0"}
    if os.getenv("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=15) as response:
                return _parse_semantic(json.loads(response.read().decode("utf-8")), min_citations)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            logger.warning("Semantic Scholar HTTP %s", exc.code)
            break
        except Exception as exc:
            logger.warning("Semantic Scholar search failed: %s", exc)
            break
    return []


def search_arxiv(query: str, max_results: int = 10) -> list[Paper]:
    url = ("https://export.arxiv.org/api/query?"
           f"search_query=all:{urllib.parse.quote(query)}&start=0&max_results={max_results}&sortBy=relevance")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "AgentMate/1.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return _parse_arxiv_xml(response.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("arXiv search failed: %s", exc)
        return []


def search_papers(
    query: str,
    max_results: int = 8,
    min_year: int = 2020,
    max_year: int = 2100,
    min_citations: int = 0,
    sources: list[str] | None = None,
) -> list[Paper]:
    selected_sources = set(sources or ["semantic_scholar", "arxiv"])
    papers = []
    if "semantic_scholar" in selected_sources:
        papers = search_semantic_scholar(
            query, max_results, min_year, max_year, min_citations
        )
    if "arxiv" in selected_sources:
        known_titles = {paper.title.lower() for paper in papers}
        for paper in search_arxiv(query, max_results):
            in_year_range = not paper.year or min_year <= paper.year <= max_year
            if (
                paper.title.lower() not in known_titles
                and in_year_range
                and paper.citations >= min_citations
            ):
                papers.append(paper)
                known_titles.add(paper.title.lower())
    deduplicated: dict[str, Paper] = {}
    for paper in papers:
        key = re.sub(r"[^a-z0-9]+", "", paper.title.lower())
        previous = deduplicated.get(key)
        if not previous or (paper.quality_score, len(paper.abstract)) > (
            previous.quality_score,
            len(previous.abstract),
        ):
            deduplicated[key] = paper
    return list(deduplicated.values())[:max_results]


def _parse_semantic(data: dict, min_citations: int = 0) -> list[Paper]:
    papers = []
    for item in data.get("data", []):
        citations = item.get("citationCount") or 0
        if citations < min_citations:
            continue
        external_ids = item.get("externalIds") or {}
        papers.append(Paper(
            title=item.get("title", ""),
            authors=[author.get("name", "") for author in item.get("authors", [])],
            abstract=item.get("abstract") or "",
            year=item.get("year") or 0,
            citations=citations,
            venue=item.get("venue") or "",
            url=item.get("url") or "",
            arxiv_id=external_ids.get("ArXiv", ""),
            source="semantic_scholar",
        ))
    return papers


def _parse_arxiv_xml(xml_text: str) -> list[Paper]:
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    papers = []
    for entry in root.findall("atom:entry", namespace):
        title = entry.findtext("atom:title", default="", namespaces=namespace).strip().replace("\n", " ")
        abstract = entry.findtext("atom:summary", default="", namespaces=namespace).strip().replace("\n", " ")
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        year = int(published[:4]) if published[:4].isdigit() else 0
        url = entry.findtext("atom:id", default="", namespaces=namespace).strip()
        arxiv_id = url.split("/abs/")[-1] if "/abs/" in url else url
        authors = [author.findtext("atom:name", default="", namespaces=namespace)
                   for author in entry.findall("atom:author", namespace)]
        papers.append(Paper(title=title, authors=authors, abstract=abstract, year=year, url=url,
                            pdf_url=url.replace("/abs/", "/pdf/"), arxiv_id=arxiv_id))
    return papers
