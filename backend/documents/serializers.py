"""Input document and requirement serializers (specs/04-api-spec.md sections 2-3)."""

from rest_framework import serializers

from documents.models import DocumentPage, Requirement, SourceDocument


class SourceDocumentSerializer(serializers.ModelSerializer):
    doc_type_label = serializers.CharField(source="get_doc_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    table_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = SourceDocument
        fields = [
            "id", "doc_type", "doc_type_label", "original_name", "doc_no",
            "page_count", "table_count", "status", "status_label", "error_message",
            "created_at",
        ]


class DocumentPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentPage
        fields = ["page_no", "text", "tables"]


class RequirementSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = Requirement
        fields = [
            "id", "clause_no", "chapter", "category", "category_label",
            "item", "requirement_text", "context_text", "source_page", "order",
            "is_active", "is_graded", "is_edited",
            "ai_item", "ai_requirement_text", "ai_category",
        ]
        read_only_fields = ["is_edited", "ai_item", "ai_requirement_text", "ai_category"]

    def update(self, instance, validated_data):
        """Any human edit flags the row; the ai_* columns stay frozen (FR-07)."""
        content_fields = {"clause_no", "item", "requirement_text", "category", "context_text"}
        if content_fields & set(validated_data):
            validated_data["is_edited"] = True
        return super().update(instance, validated_data)
