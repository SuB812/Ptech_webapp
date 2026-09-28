"""Markdown parsing for knowledge documents (specs/05-rag-pipeline.md section 2.4).

Our own reference material ships as ``.md``. The chunker needs three things out
of it, so this module produces exactly those and nothing more:

1. the heading path of every block, because ``section_path`` is what lets the
   model tell ``4.1 발전 부문`` from ``4.2 산업 부문`` (TRAP-3);
2. tables as 2-D arrays, kept whole -- one table becomes one parent chunk;
3. narrative text per section, which is where the option side effects live
   ("IP66 적용 시 본체 무게가 약 1.4kg 증가", TRAP-2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from common.tables import normalize_cell

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
DOC_NO_RE = re.compile(r"^\s*문서\s*번호\s*[:：]\s*(\S+)", re.MULTILINE)
DATE_RE = re.compile(r"^\s*(?:개정일|기준일|작성일)\s*[:：]\s*(\d{4})-(\d{2})-(\d{2})", re.MULTILINE)
MODEL_RE = re.compile(r"LT-\d{3}")


@dataclass
class MdTable:
    index: int
    rows: list[list[str]]
    heading_path: list[str]

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []

    @property
    def body(self) -> list[list[str]]:
        return self.rows[1:] if len(self.rows) > 1 else []

    @property
    def section_path(self) -> str:
        return " > ".join(self.heading_path)


@dataclass
class MdSection:
    heading: str  # "" for the preamble before the first heading
    level: int
    heading_path: list[str]
    text: str = ""
    tables: list[MdTable] = field(default_factory=list)

    @property
    def section_path(self) -> str:
        return " > ".join(self.heading_path)

    @property
    def model_tags(self) -> list[str]:
        """Models named anywhere in this section's heading path.

        An empty list means the section is model-agnostic (common information)
        and must not be penalised by the retriever's model filter
        (specs/05-rag-pipeline.md section 3.5).
        """
        seen: list[str] = []
        for part in self.heading_path:
            for m in MODEL_RE.findall(part):
                if m not in seen:
                    seen.append(m)
        return seen


@dataclass
class MdDocument:
    title: str
    doc_no: str
    revision_date: date | None
    sections: list[MdSection]

    @property
    def tables(self) -> list[MdTable]:
        return [t for s in self.sections for t in s.tables]

    def section(self, heading_contains: str) -> MdSection | None:
        for s in self.sections:
            if heading_contains in s.heading:
                return s
        return None

    def tables_under(self, heading_contains: str) -> list[MdTable]:
        return [
            t
            for t in self.tables
            if any(heading_contains in part for part in t.heading_path)
        ]


def _parse_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [normalize_cell(c.replace("\\|", "|")) for c in stripped.split("|")]


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|") and line.count("|") >= 2


def parse_markdown(text: str) -> MdDocument:
    """Parse a knowledge Markdown document into sections and tables."""
    lines = text.splitlines()

    doc_no_match = DOC_NO_RE.search(text)
    doc_no = doc_no_match.group(1) if doc_no_match else ""

    date_match = DATE_RE.search(text)
    revision_date = (
        date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
        if date_match
        else None
    )

    title = ""
    for line in lines:
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) == 1:
            title = m.group(2).strip()
            break

    sections: list[MdSection] = []
    # heading_stack[level] = heading text, for levels 1..6
    heading_stack: dict[int, str] = {}
    table_counter = 0

    current = MdSection(heading="", level=0, heading_path=[title] if title else [])
    text_buf: list[str] = []

    def flush_text() -> None:
        current.text = "\n".join(text_buf).strip()
        text_buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        heading = HEADING_RE.match(line)
        if heading:
            flush_text()
            if current.heading or current.text or current.tables:
                sections.append(current)

            level = len(heading.group(1))
            name = heading.group(2).strip()
            heading_stack[level] = name
            for deeper in [k for k in heading_stack if k > level]:
                del heading_stack[deeper]

            # The level-1 heading is the document title; keep it at the front of
            # every path so section_path reads like the spec's example
            # "제품 카탈로그 > 2. LT-150 사양 > 2.2 구조".
            path = [heading_stack[k] for k in sorted(heading_stack) if k >= 1]
            current = MdSection(heading=name, level=level, heading_path=path)
            i += 1
            continue

        if HR_RE.match(line):
            i += 1
            continue

        if _is_table_line(line):
            header = _parse_table_row(line)
            if i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1]:
                rows = [header]
                i += 2
                while i < len(lines) and _is_table_line(lines[i]):
                    rows.append(_parse_table_row(lines[i]))
                    i += 1
                current.tables.append(
                    MdTable(index=table_counter, rows=rows, heading_path=list(current.heading_path))
                )
                table_counter += 1
                continue

        text_buf.append(line)
        i += 1

    flush_text()
    if current.heading or current.text or current.tables:
        sections.append(current)

    return MdDocument(
        title=title,
        doc_no=doc_no,
        revision_date=revision_date,
        sections=sections,
    )


def parse_markdown_file(path: str | Path) -> MdDocument:
    return parse_markdown(Path(path).read_text(encoding="utf-8"))
