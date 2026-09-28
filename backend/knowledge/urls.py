"""Knowledge base routes. Mounted at /api/ by config.urls."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from knowledge.views import KnowledgeDocumentViewSet, knowledge_search

router = DefaultRouter()
router.register(r"knowledge/documents", KnowledgeDocumentViewSet, basename="knowledge-document")

urlpatterns = [
    path("knowledge/search/", knowledge_search, name="knowledge-search"),
    *router.urls,
]
