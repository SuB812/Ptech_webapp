"""Load one of our own documents into the knowledge base.

Calls the same service code as the upload endpoint -- there is no second code
path (specs/11-dev-setup.md section 6).
"""

from __future__ import annotations

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from common.enums import KnowledgeKind
from knowledge.models import KnowledgeDocument
from knowledge.services.embedder import (
    detect_metadata,
    guess_doc_kind,
    index_document,
    looks_like_bid_document,
)


class Command(BaseCommand):
    help = "자사 자료를 RAG 지식베이스에 색인한다 (.md 또는 .pdf)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="문서 경로")
        parser.add_argument(
            "--kind",
            choices=[c[0] for c in KnowledgeKind.choices],
            help="문서 종류. 생략하면 파일명·내용으로 추정한다.",
        )
        parser.add_argument("--title", default="", help="제목. 생략하면 문서 첫 제목.")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="같은 문서번호의 기존 문서를 지우고 새로 색인한다.",
        )
        parser.add_argument(
            "--allow-bid-document",
            action="store_true",
            help="입찰 문서 판정을 무시한다 (오탐일 때만).",
        )

    def handle(self, *args, **options):
        path = Path(options["path"]).resolve()
        if not path.exists():
            raise CommandError(f"파일이 없습니다: {path}")
        if path.suffix.lower() not in {".md", ".pdf"}:
            raise CommandError(f".md 또는 .pdf 만 가능합니다: {path.suffix}")

        head = ""
        if path.suffix.lower() == ".md":
            head = path.read_text(encoding="utf-8")[:4000]

        if looks_like_bid_document(path.name, head) and not options["allow_bid_document"]:
            raise CommandError(
                "입찰공고문·기술사양서로 보입니다. 지식베이스에는 자사 자료만 넣습니다.\n"
                "공고·사양서를 색인하면 다음 입찰 분석의 근거가 오염됩니다.\n"
                "오탐이라면 --allow-bid-document 를 붙여 다시 실행하세요."
            )

        meta = detect_metadata(path)
        doc_no = meta.get("doc_no", "")
        title = options["title"] or meta.get("title") or path.stem
        kind = options["kind"] or guess_doc_kind(path, head)

        existing = KnowledgeDocument.objects.filter(doc_no=doc_no) if doc_no else None
        if existing and existing.exists():
            if not options["replace"]:
                raise CommandError(
                    f"문서번호 {doc_no} 가 이미 있습니다 (id={existing.first().pk}). "
                    f"--replace 를 쓰거나 재색인하세요."
                )
            self.stdout.write(f"기존 문서 {doc_no} 삭제")
            existing.delete()

        with path.open("rb") as handle:
            document = KnowledgeDocument.objects.create(
                title=title,
                doc_no=doc_no,
                doc_kind=kind,
                revision_date=meta.get("revision_date"),
                file=File(handle, name=path.name),
            )

        self.stdout.write(f"색인 시작: {title} ({doc_no or '문서번호 없음'}) [{kind}]")
        result = index_document(document)

        self.stdout.write(
            self.style.SUCCESS(
                f"완료: 부모 {result.parents}, 자식 {result.children}, "
                f"임베딩 {result.embedded} (id={document.pk})"
            )
        )
