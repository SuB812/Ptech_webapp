"""Knowledge base serializers (specs/04-api-spec.md section 4)."""

from rest_framework import serializers

from knowledge.models import KnowledgeChunk, KnowledgeDocument


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    doc_kind_label = serializers.CharField(source="get_doc_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = KnowledgeDocument
        fields = [
            "id", "title", "doc_no", "doc_kind", "doc_kind_label",
            "revision_date", "status", "status_label",
            "chunk_count", "embedding_model", "error_message",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "chunk_count", "embedding_model", "error_message",
            "created_at", "updated_at",
        ]


class KnowledgeDocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    doc_kind = serializers.ChoiceField(
        choices=KnowledgeDocument._meta.get_field("doc_kind").choices
    )
    title = serializers.CharField(required=False, allow_blank=True, max_length=300)
    doc_no = serializers.CharField(required=False, allow_blank=True, max_length=100)


class KnowledgeChunkSerializer(serializers.ModelSerializer):
    chunk_type_label = serializers.CharField(
        source="get_chunk_type_display", read_only=True
    )

    class Meta:
        model = KnowledgeChunk
        fields = [
            "id", "is_parent", "parent", "chunk_type", "chunk_type_label",
            "section_path", "heading", "page_no", "content",
            "keywords", "model_tags", "token_count",
        ]


class SearchRequestSerializer(serializers.Serializer):
    """FR-12 debug search. Every parameter is optional and falls back to .env."""

    query = serializers.CharField(max_length=2000)
    top_k = serializers.IntegerField(required=False, min_value=1, max_value=50)
    threshold = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)
    w_semantic = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)
    w_keyword = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)
    model_filter = serializers.CharField(required=False, allow_blank=True, max_length=30)
