"""Markdown、文本、PDF、DOCX 与代码资料解析器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocChunk:
    content: str
    source: str = ""
    heading: str = ""
    chunk_type: str = "text"


def parse_file(path: str | Path) -> list[DocChunk]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".md":
        return _parse_markdown(file_path.read_text(encoding="utf-8", errors="ignore"), str(file_path))
    if suffix == ".pdf":
        return _parse_pdf(file_path)
    if suffix == ".docx":
        return _parse_docx(file_path)
    if suffix in {".py", ".java", ".js", ".cpp", ".h", ".hpp", ".c"}:
        return _parse_code(file_path.read_text(encoding="utf-8", errors="ignore"), str(file_path))
    try:
        return _parse_text(file_path.read_text(encoding="utf-8", errors="ignore"), str(file_path))
    except OSError:
        return []


def parse_directory(path: str | Path) -> list[DocChunk]:
    supported = {".md", ".txt", ".pdf", ".docx", ".py", ".java", ".js", ".cpp", ".h",
                 ".hpp", ".c", ".json", ".xml", ".html", ".csv", ".yaml", ".yml", ".rst"}
    chunks: list[DocChunk] = []
    for file_path in sorted(Path(path).rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in supported:
            chunks.extend(parse_file(file_path))
    return chunks


def _parse_markdown(text: str, source: str) -> list[DocChunk]:
    sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
    chunks: list[DocChunk] = []
    heading = ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        match = re.match(r"^#{1,3}\s+(.+)", section)
        if match:
            heading = match.group(1).strip()
        chunks.extend(DocChunk(content=item, source=source, heading=heading)
                      for item in _split_paragraphs(section))
    return chunks


def _parse_code(text: str, source: str) -> list[DocChunk]:
    blocks = re.split(r"(?=^(?:def |class |function |public\s|private\s))", text, flags=re.MULTILINE)
    chunks = []
    for block in blocks:
        if not block.strip():
            continue
        name = re.match(r"(?:def|class|function)\s+(\w+)", block.strip())
        chunks.append(DocChunk(content=block.strip(), source=source,
                               heading=name.group(1) if name else "", chunk_type="code"))
    return chunks or _parse_text(text, source)


def _parse_text(text: str, source: str) -> list[DocChunk]:
    return [DocChunk(content=item, source=source) for item in _split_paragraphs(text)]


def _parse_pdf(path: Path) -> list[DocChunk]:
    chunks: list[DocChunk] = []
    try:
        import fitz

        with fitz.open(str(path)) as document:
            for page_index, page in enumerate(document, 1):
                chunks.extend(DocChunk(content=item, source=str(path), heading=f"第 {page_index} 页")
                              for item in _split_paragraphs(page.get_text()))
        if chunks:
            return chunks
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(path) as document:
            for page_index, page in enumerate(document.pages, 1):
                chunks.extend(DocChunk(content=item, source=str(path), heading=f"第 {page_index} 页")
                              for item in _split_paragraphs(page.extract_text() or ""))
    except Exception:
        pass
    return chunks


def _parse_docx(path: Path) -> list[DocChunk]:
    try:
        from docx import Document

        chunks = []
        for paragraph in Document(path).paragraphs:
            text = paragraph.text.strip()
            if text:
                heading = paragraph.style.name if paragraph.style.name.startswith("Heading") else ""
                chunks.append(DocChunk(content=text, source=str(path), heading=heading))
        return chunks
    except Exception:
        return []


def _split_paragraphs(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
