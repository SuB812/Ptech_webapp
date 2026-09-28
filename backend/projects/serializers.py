"""Bid project serializers (FR-22).

Phase 2 scope: flat fields plus counts and a latest-run summary, enough for the
list/detail contract in specs/04-api-spec.md section 1. Nested documents,
requirements and submission items arrive in Phase 5 with their own serializers.
"""

from rest_framework import serializers

from analysis.models import AnalysisRun
from projects.models import BidProject, ParticipationRequirement, SubmissionItem


class RunSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisRun
        fields = ["id", "status", "finished_at", "summary", "accuracy"]


class ParticipationRequirementSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ParticipationRequirement
        fields = ["id", "seq", "text", "status", "status_label", "note"]


class SubmissionItemSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SubmissionItem
        fields = [
            "id", "seq", "name", "note",
            "status", "status_label", "evidence_text", "is_checked",
        ]


class BidProjectListSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(source="documents.count", read_only=True)
    requirement_count = serializers.IntegerField(
        source="requirements.count", read_only=True
    )
    latest_run = serializers.SerializerMethodField()

    class Meta:
        model = BidProject
        fields = [
            "id", "title", "bid_no", "org", "bid_due_at",
            "document_count", "requirement_count", "latest_run",
        ]

    def get_latest_run(self, obj) -> dict | None:
        run = obj.runs.order_by("-created_at").first()
        return RunSummarySerializer(run).data if run else None


class BidProjectSerializer(serializers.ModelSerializer):
    """Detail view. ``title`` is the only field required on create; the rest are
    filled by extraction (FR-05)."""

    participation_reqs = ParticipationRequirementSerializer(many=True, read_only=True)
    submission_items = SubmissionItemSerializer(many=True, read_only=True)
    runs = RunSummarySerializer(many=True, read_only=True)
    document_count = serializers.IntegerField(source="documents.count", read_only=True)
    requirement_count = serializers.IntegerField(
        source="requirements.count", read_only=True
    )

    class Meta:
        model = BidProject
        fields = [
            "id", "title", "bid_no", "org", "item_name", "quantity",
            "estimated_price", "delivery_place", "delivery_term",
            "announced_on", "inquiry_due_at", "bid_due_at", "opening_at",
            "spec_doc_no", "notes",
            "document_count", "requirement_count",
            "participation_reqs", "submission_items", "runs",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
