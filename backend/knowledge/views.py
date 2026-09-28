"""Knowledge base views (FR-08, FR-09, FR-12)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from common.llm import LLMUnavailable
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from knowledge.serializers import (
    KnowledgeChunkSerializer,
    KnowledgeDocumentSerializer,
    KnowledgeDocumentUploadSerializer,
    SearchRequestSerializer,
)
from knowledge.services import retriever
from knowledge.services.embedder import (
    detect_metadata,
    index_document,
    looks_like_bid_document,
)

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".md"}


def api_error(detail: str, code: str, http_status: int) -> Response:
    return Response({"detail": detail, "code": code}, status=http_status)


def _index_in_background(document_id: int) -> None:
    def run() -> None:
        try:
            document = KnowledgeDocument.objects.get(pk=document_id)
            index_document(document)
        except Exception:  # noqa: BLE001 - status/error already persisted
            logger.exception("indexing failed for knowledge document %s", document_id)

    threading.Thread(target=run, daemon=True).start()


class KnowledgeDocumentViewSet(viewsets.ModelViewSet):
    queryset = KnowledgeDocument.objects.all()
    serializer_class = KnowledgeDocumentSerializer

    def create(self, request, *args, **kwargs):
        form = KnowledgeDocumentUploadSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        upload = form.validated_data["file"]

        suffix = Path(upload.name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            return api_error(
                ".pdf 또는 .md 파일만 업로드할 수 있습니다.", "invalid_file_type",
                status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > settings.UPLOAD_MAX_BYTES:
            return api_error(
                f"파일이 너무 큽니다. 최대 {settings.UPLOAD_MAX_BYTES // (1024 * 1024)}MB 입니다.",
                "file_too_large", status.HTTP_400_BAD_REQUEST,
            )

        # Principle 1: input documents must never be indexed.
        head = ""
        try:
            head = upload.read(4000).decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            head = ""
        finally:
            upload.seek(0)

        if looks_like_bid_document(upload.name, head):
            return api_error(
                "입찰공고문·기술사양서는 지식베이스에 올릴 수 없습니다. "
                "이 문서들은 입찰 건 화면에서 업로드하세요. "
                "자사 자료가 맞다면 파일명을 바꿔 다시 올려주세요.",
                "knowledge_doc_type_forbidden", status.HTTP_400_BAD_REQUEST,
            )

        document = KnowledgeDocument.objects.create(
            title=form.validated_data.get("title") or Path(upload.name).stem,
            doc_no=form.validated_data.get("doc_no", ""),
            doc_kind=form.validated_data["doc_kind"],
            file=upload,
        )

        # Fill title/doc_no/revision_date from the file when not supplied.
        meta = detect_metadata(Path(document.file.path))
        changed = []
        if meta.get("title") and not form.validated_data.get("title"):
            document.title = meta["title"]
            changed.append("title")
        if meta.get("doc_no") and not document.doc_no:
            document.doc_no = meta["doc_no"]
            changed.append("doc_no")
        if meta.get("revision_date"):
            document.revision_date = meta["revision_date"]
            changed.append("revision_date")
        if changed:
            document.save(update_fields=changed + ["updated_at"])

        _index_in_background(document.pk)
        document.refresh_from_db()
        return Response(
            KnowledgeDocumentSerializer(document).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def reindex(self, request, pk=None):
        document = self.get_object()
        _index_in_background(document.pk)
        document.refresh_from_db()
        return Response(
            KnowledgeDocumentSerializer(document).data, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=True, methods=["get"])
    def chunks(self, request, pk=None):
        document = self.get_object()
        queryset = document.chunks.all().order_by("id")

        is_parent = request.query_params.get("is_parent")
        if is_parent is not None:
            queryset = queryset.filter(is_parent=is_parent.lower() in {"1", "true", "yes"})

        return Response(KnowledgeChunkSerializer(queryset, many=True).data)


@api_view(["POST"])
def knowledge_search(request):
    """FR-12 search test. Shows combined / semantic / keyword scores side by side.

    Seeing the three numbers together is the point: semantics cannot separate
    IP65 from IP66, and the keyword column is what does.
    """
    form = SearchRequestSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data

    params = {
        "top_k": data.get("top_k", settings.RAG_TOP_K),
        "threshold": data.get("threshold", settings.RAG_SCORE_THRESHOLD),
        "w_semantic": data.get("w_semantic", settings.RAG_SEMANTIC_WEIGHT),
        "w_keyword": data.get("w_keyword", settings.RAG_KEYWORD_WEIGHT),
        "model_filter": data.get("model_filter") or None,
    }

    try:
        hits = retriever.search(data["query"], **params)
    except LLMUnavailable as exc:
        return api_error(str(exc), "llm_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response(
        {
            "query": data["query"],
            "params": params,
            "results": [
                {
                    "chunk_id": hit.chunk.id,
                    "rank": hit.rank,
                    "score": hit.score,
                    "semantic_score": hit.semantic_score,
                    "keyword_score": hit.keyword_score,
                    "doc_title": hit.doc_title,
                    "doc_no": hit.doc_no,
                    "location": hit.location,
                    "page_no": hit.chunk.page_no,
                    "content": hit.chunk.content,
                    "parent_content": hit.parent_content,
                    "model_tags": hit.model_tags,
                    "keywords": hit.chunk.keywords,
                }
                for hit in hits
            ],
        }
    )
