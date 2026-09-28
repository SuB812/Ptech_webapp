"""Turn extracted 2-D tables into Markdown.

Prompts get Markdown tables, never raw nested lists: the model reads a Markdown
table far more reliably (specs/06-analysis-pipeline.md section 2.1).
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def normalize_cell(value: object) -> str:
    """Collapse a raw pdfplumber cell to a single clean line.

    Cells arrive as ``None`` or with embedded newlines from wrapped text. We
    never alter the characters themselves -- unit notation must survive
    verbatim (``20,000 lm`` stays ``20,000 lm``).
    """
    if value is None:
        return ""
    return _WS.sub(" ", str(value).replace("\n", " ")).strip()


def normalize_rows(rows: list[list[object]]) -> list[list[str]]:
    return [[normalize_cell(c) for c in row] for row in rows]


def to_markdown(rows: list[list[str]], *, has_header: bool = True) -> str:
    """Render one table. Empty rows are dropped; ragged rows are padded."""
    cleaned = [r for r in rows if any(c.strip() for c in r)]
    if not cleaned:
        return ""

    width = max(len(r) for r in cleaned)
    padded = [list(r) + [""] * (width - len(r)) for r in cleaned]
    escaped = [[c.replace("|", "\\|") or " " for c in r] for r in padded]

    if has_header:
        header, body = escaped[0], escaped[1:]
    else:
        header, body = [f"열{i + 1}" for i in range(width)], escaped

    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * width) + "|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def pages_to_markdown(pages: list) -> str:
    """Serialize every table of an extraction result, labelled by page.

    ``pages`` items need ``page_no`` and ``tables`` (each with ``index``/``rows``).
    """
    blocks: list[str] = []
    for page in pages:
        for table in page.tables:
            md = to_markdown(table.rows)
            if md:
                blocks.append(f"[p.{page.page_no} 표 {table.index + 1}]\n{md}")
    return "\n\n".join(blocks)
