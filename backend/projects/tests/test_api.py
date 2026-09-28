"""Phase 2: the /api/projects/ contract (FR-22, specs/04-api-spec.md section 1)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from analysis.models import AnalysisRun
from common.enums import RunStatus
from projects.models import BidProject

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


def test_api_root_reports_configuration(client):
    """LLM 이 가짜인지, 키가 있는지 화면에서 확인할 수 있어야 한다."""
    res = client.get("/api/")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "ptech-bid-analysis"
    assert body["llm_fake"] is True, "테스트에서는 pytest.ini 가 LLM_FAKE=True 로 강제한다"
    assert body["rag_defaults"] == {
        "top_k": 5, "threshold": 0.4, "w_semantic": 0.6, "w_keyword": 0.4,
    }


def test_empty_project_list(client):
    """Phase 2 완료 조건."""
    res = client.get("/api/projects/")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 0
    assert body["results"] == []


def test_create_project_with_title_only(client):
    res = client.post("/api/projects/", {"title": "○○화력발전소 구내 LED 투광등 교체"}, format="json")
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "○○화력발전소 구내 LED 투광등 교체"
    assert body["bid_no"] == ""
    assert body["document_count"] == 0
    assert body["requirement_count"] == 0
    assert body["participation_reqs"] == []
    assert body["submission_items"] == []


def test_create_requires_title(client):
    res = client.post("/api/projects/", {}, format="json")
    assert res.status_code == 400
    assert "title" in res.json()


def test_list_shows_latest_run_summary(client):
    project = BidProject.objects.create(
        title="테스트 건", bid_no="KPG-2025-EQ-0417", org="한국발전기술공사 자재구매처"
    )
    AnalysisRun.objects.create(project=project, status=RunStatus.FAILED)
    latest = AnalysisRun.objects.create(
        project=project,
        status=RunStatus.DONE,
        summary={"MEET": 7, "GAP": 4, "CHECK": 2, "total": 13},
        accuracy={"score": 11, "total": 13},
    )

    res = client.get("/api/projects/")
    row = res.json()["results"][0]
    assert row["bid_no"] == "KPG-2025-EQ-0417"
    assert row["latest_run"]["id"] == latest.id
    assert row["latest_run"]["summary"]["MEET"] == 7
    assert row["latest_run"]["accuracy"] == {"score": 11, "total": 13}


def test_detail_and_delete(client):
    project = BidProject.objects.create(title="삭제될 건")
    res = client.get(f"/api/projects/{project.id}/")
    assert res.status_code == 200
    assert res.json()["id"] == project.id

    res = client.delete(f"/api/projects/{project.id}/")
    assert res.status_code == 204
    assert BidProject.objects.count() == 0


def test_patch_header_fields(client):
    """FR-05 기본정보는 화면에서 인라인 수정한다."""
    project = BidProject.objects.create(title="수정될 건")
    res = client.patch(
        f"/api/projects/{project.id}/",
        {"bid_no": "KPG-2025-EQ-0417", "quantity": "200대"},
        format="json",
    )
    assert res.status_code == 200
    project.refresh_from_db()
    assert project.bid_no == "KPG-2025-EQ-0417"
    assert project.quantity == "200대"


def test_no_authentication_required(client):
    """PoC 는 단일 사용자다 (00-overview.md 3절). 401/403 이 나와서는 안 된다."""
    assert client.get("/api/projects/").status_code == 200
    assert client.post("/api/projects/", {"title": "x"}, format="json").status_code == 201
