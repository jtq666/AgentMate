"""
文档解析器
支持 Markdown / 纯文本 / 代码文件，按语义分块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DocChunk:
    content: str
    source: str = ""
    heading: str = ""
    chunk_type: str = "text"  # text / code


def parse_file(path: str | Path) -> list[DocChunk]:
    """解析单个文件"""
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".md":
        text = p.read_text(encoding="utf-8", errors="ignore")
        return _parse_markdown(text, str(p))
    elif suffix == ".pdf":
        return _parse_pdf(p)
    elif suffix == ".docx":
        return _parse_docx(p)
    elif suffix in (".py", ".java", ".js", ".cpp", ".h", ".hpp", ".c"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        return _parse_code(text, str(p), suffix)
    elif suffix in (".txt", ".json", ".xml", ".html", ".csv", ".yaml", ".yml"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        return _parse_text(text, str(p))
    else:
        # 尝试作为文本读取
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            return _parse_text(text, str(p))
        except Exception:
            return []


def parse_directory(path: str | Path) -> list[DocChunk]:
    """递归解析目录"""
    p = Path(path)
    supported = {".md", ".txt", ".pdf", ".docx", ".py", ".java", ".js",
                  ".cpp", ".h", ".hpp", ".c", ".json", ".xml", ".html",
                  ".csv", ".yaml", ".yml", ".rst"}
    chunks = []
    for f in sorted(p.rglob("*")):
        if f.is_file() and f.suffix.lower() in supported:
            chunks.extend(parse_file(f))
    return chunks


def _parse_markdown(text: str, source: str) -> list[DocChunk]:
    """按标题分节，每节内按段落分块"""
    sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
    chunks = []
    heading = ""
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        m = re.match(r"^#{1,3}\s+(.+)", sec)
        if m:
            heading = m.group(1).strip()
        for para in _split_paragraphs(sec):
            chunks.append(DocChunk(content=para, source=source, heading=heading))
    return chunks


def _parse_code(text: str, source: str, suffix: str) -> list[DocChunk]:
    """按函数/类分块"""
    pattern = r"(?=^(?:def |class |function |public\s|private\s))"
    blocks = re.split(pattern, text, flags=re.MULTILINE)
    chunks = []
    for block in blocks:
        block = block.strip()
        if block:
            name_m = re.match(r"(?:def|class|function)\s+(\w+)", block)
            heading = name_m.group(1) if name_m else ""
            chunks.append(DocChunk(content=block, source=source,
                                   heading=heading, chunk_type="code"))
    return chunks or _parse_text(text, source)


def _parse_text(text: str, source: str) -> list[DocChunk]:
    return [DocChunk(content=p, source=source) for p in _split_paragraphs(text) if p]


def _parse_pdf(path: Path) -> list[DocChunk]:
    """解析 PDF 文件（支持文本型PDF，扫描版返回空）"""
    chunks = []
    source = str(path)

    # 尝试 pymupdf（速度最快）
    try:
        import fitz
        doc = fitz.open(str(path))
        for i in range(len(doc)):
            text = doc[i].get_text()
            if text and text.strip():
                for para in _split_paragraphs(text):
                    chunks.append(DocChunk(content=para, source=source,
                        heading=f"第{i+1}页", chunk_type="text"))
        if chunks:
            return chunks
    except Exception:
        pass

    # 回退 pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text and text.strip():
                    for para in _split_paragraphs(text):
                        chunks.append(DocChunk(content=para, source=source,
                            heading=f"第{i+1}页", chunk_type="text"))
        if chunks:
            return chunks
    except Exception:
        pass

    return chunks  # 扫描版PDF无文字则返回空


def _parse_docx(path: Path) -> list[DocChunk]:
    """解析 Word 文档"""
    chunks = []
    source = str(path)
    try:
        from docx import Document
        doc = Document(path)
        for i, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if text:
                heading = para.style.name if para.style.name.startswith("Heading") else ""
                chunks.append(DocChunk(
                    content=text, source=source,
                    heading=heading, chunk_type="text",
                ))
    except Exception:
        pass
    return chunks


def _split_paragraphs(text: str) -> list[str]:
    """按空行分段"""
    paras = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paras if p.strip()]
