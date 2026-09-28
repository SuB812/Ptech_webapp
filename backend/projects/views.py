"""Bid project views (FR-22)."""

from rest_framework import viewsets

from projects.models import BidProject
from projects.serializers import BidProjectListSerializer, BidProjectSerializer


class BidProjectViewSet(viewsets.ModelViewSet):
    """List / create / retrieve / update / delete a bid project.

    Deleting cascades to documents, requirements and runs. Uploaded files go
    with them via the FileField cleanup in Phase 5.
    """

    queryset = BidProject.objects.all().prefetch_related(
        "documents", "requirements", "runs", "participation_reqs", "submission_items"
    )

    def get_serializer_class(self):
        if self.action == "list":
            return BidProjectListSerializer
        return BidProjectSerializer
