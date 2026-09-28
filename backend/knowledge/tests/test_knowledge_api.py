"""Phase 4: knowledge base API (FR-08, FR-12).

The load-bearing test here is that an announcement or spec sheet is refused.
Indexing an input document poisons the next bid's evidence, so the guard exists
on the server and not only in the UI (principle 1).
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from common.enums import DocStatus, KnowledgeKind
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from knowledge.services.embedder import index_document, looks_like_bid_document

pytestmark = pytest.mark.django_db

CATALOG = settings.SAMPLES_DIR / "03_자사_제품카탈로그.md"
QA = settings.SAMPLES_DIR / "04_자사_인증_시험_실적.md"
ANNOUNCEMENT = settings.SAMPLES_DIR / "01_입찰공고문.pdf"


@pytest.fixture
def client():
    return APIClient()


def upload_file(path, name=None):
    return SimpleUploadedFile(
        name or path.name, path.read_bytes(), content_type="application/octet-stream"
    )


# ---------------------------------------------------------------------------
# Principle 1 guard — 09 §7.1 test_knowledge_rejects_bid_doc
# ---------------------------------------------------------------------------


def test_announcement_upload_is_rejected(client):
    res = client.post(
        "/api/knowledge/documents/",
        {"file": upload_file(ANNOUNCEMENT), "doc_kind": KnowledgeKind.OTHER},
        format="multipart",
    )
    assert res.status_code == 400
    assert res.json()["code"] == "knowledge_doc_type_forbidden"
    assert "입찰 건 화면" in res.json()["detail"]
    assert KnowledgeDocument.objects.count() == 0
    assert KnowledgeChunk.objects.count() == 0


def test_spec_sheet_name_is_rejected(client):
    res = client.post(
        "/api/knowledge/documents/",
        {
            "file": SimpleUploadedFile("02_기술사양서.md", b"# spec", content_type="text/markdown"),
            "doc_kind": KnowledgeKind.OTHER,
        },
        format="multipart",
    )
    assert res.status_code == 400
    assert res.json()["code"] == "knowledge_doc_type_forbidden"


def test_bid_detection_rules():
    assert looks_like_bid_document("01_입찰공고문.pdf")
    assert looks_like_bid_document("02_기술사양서.pdf")
    assert looks_like_bid_document("purchase_RFP.pdf")
    assert looks_like_bid_document("anything.md", "공고번호 KPG-2025-EQ-0417")
    # Our own material must pass.
    assert not looks_like_bid_document("03_자사_제품카탈로그.md", "# 한빛조명(주) 제품 카탈로그")
    assert not looks_like_bid_document("04_자사_인증_시험_실적.md", "문서번호: HB-QA-2025-07")


def test_false_positive_message_tells_the_user_what_to_do(client):
    res = client.post(
        "/api/knowledge/documents/",
        {
            "file": SimpleUploadedFile("자사_규격서.md", b"# ours", content_type="text/markdown"),
            "doc_kind": KnowledgeKind.CATALOG,
        },
        format="multipart",
    )
    assert res.status_code == 400
    assert "파일명을 바꿔" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Upload and indexing
# ---------------------------------------------------------------------------


def test_invalid_extension(client):
    res = client.post(
        "/api/knowledge/documents/",
        {
            "file": SimpleUploadedFile("spec.txt", b"x", content_type="text/plain"),
            "doc_kind": KnowledgeKind.CATALOG,
        },
        format="multipart",
    )
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_file_type"


def test_catalog_indexes_to_the_expected_shape():
    """서비스 코드로 직접 색인 — 업로드 엔드포인트와 같은 경로다."""
    document = KnowledgeDocument.objects.create(
        title="", doc_kind=KnowledgeKind.CATALOG, file=upload_file(CATALOG)
    )
    result = index_document(document)
    document.refresh_from_db()

    assert document.status == DocStatus.INDEXED
    assert document.title == "한빛조명(주) 제품 카탈로그", "제목을 문서에서 채워야 한다"
    assert document.doc_no == "HB-CAT-2025-02"
    assert str(document.revision_date) == "2025-05-10"
    assert document.embedding_model == settings.EMBEDDING_MODEL

    assert result.parents == 11
    assert result.children == 32
    assert result.embedded == 32
    assert document.chunk_count == 43


def test_only_children_are_embedded():
    document = KnowledgeDocument.objects.create(
        title="", doc_kind=KnowledgeKind.CATALOG, file=upload_file(CATALOG)
    )
    index_document(document)

    assert document.chunks.filter(is_parent=True, embedding__isnull=False).count() == 0
    assert document.chunks.filter(is_parent=False, embedding__isnull=True).count() == 0


def test_qa_document_keeps_the_equipment_rows():
    """TRAP-4 전제가 DB 까지 살아 있는지."""
    document = KnowledgeDocument.objects.create(
        title="", doc_kind=KnowledgeKind.QA, file=upload_file(QA)
    )
    index_document(document)

    salt = document.chunks.filter(
        is_parent=False, content__contains="염수분무 시험기"
    )
    assert salt.count() == 1
    assert "미보유" in salt.first().content

    power = document.chunks.filter(
        is_parent=False, section_path__contains="발전 부문"
    )
    assert power.count() == 2


def test_reindex_is_idempotent():
    document = KnowledgeDocument.objects.create(
        title="", doc_kind=KnowledgeKind.CATALOG, file=upload_file(CATALOG)
    )
    first = index_document(document)
    second = index_document(document)

    assert (first.parents, first.children) == (second.parents, second.children)
    assert document.chunks.count() == second.parents + second.children


def test_deleting_document_removes_chunks():
    document = KnowledgeDocument.objects.create(
        title="", doc_kind=KnowledgeKind.CATALOG, file=upload_file(CATALOG)
    )
    index_document(document)
    assert KnowledgeChunk.objects.count() > 0
    document.delete()
    assert KnowledgeChunk.objects.count() == 0


# ---------------------------------------------------------------------------
# Chunk listing and search endpoints
# ---------------------------------------------------------------------------


def test_chunks_endpoint(client):
    document = KnowledgeDocument.objects.create(
        title="", doc_kind=KnowledgeKind.QA, file=upload_file(QA)
    )
    index_document(document)

    res = client.get(f"/api/knowledge/documents/{document.id}/chunks/?is_parent=false")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 35
    assert all(row["is_parent"] is False for row in rows)

    salt = [r for r in rows if "염수분무 시험기" in r["content"]]
    assert len(salt) == 1
    assert salt[0]["chunk_type"] == "table_row"
    assert "시험 설비" in salt[0]["section_path"]


def test_search_endpoint_returns_three_scores(client):
    document = KnowledgeDocument.objects.create(
        title="", doc_kind=KnowledgeKind.QA, file=upload_file(QA)
    )
    index_document(document)

    res = client.post(
        "/api/knowledge/search/",
        {"query": "염수분무 시험", "threshold": 0.0, "top_k": 3},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["query"] == "염수분무 시험"
    assert body["params"]["w_semantic"] == 0.6
    assert body["params"]["w_keyword"] == 0.4

    assert body["results"], "검색 결과가 없다"
    top = body["results"][0]
    for field in ("score", "semantic_score", "keyword_score", "parent_content", "model_tags"):
        assert field in top
    assert "염수분무 시험기" in top["content"]
    assert top["parent_content"], "부모 전문이 함께 와야 한다 (근거 모달용)"


def test_search_requires_a_query(client):
    res = client.post("/api/knowledge/search/", {}, format="json")
    assert res.status_code == 400


def test_document_list(client):
    KnowledgeDocument.objects.create(
        title="카탈로그", doc_kind=KnowledgeKind.CATALOG, file=upload_file(CATALOG)
    )
    res = client.get("/api/knowledge/documents/")
    assert res.status_code == 200
    rows = res.json()["results"]
    assert rows[0]["doc_kind_label"] == "제품카탈로그"
