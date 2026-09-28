"""Root URL config.

App routes are mounted under /api as each app gains views. The apps are
created empty in Phase 0 and wired in later phases (specs/12-dev-plan.md).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def api_root(_request):
    """Smoke endpoint: confirms the service is up and how the LLM is configured."""
    return JsonResponse(
        {
            "service": "ptech-bid-analysis",
            "llm_fake": settings.LLM_FAKE,
            "llm_key_configured": bool(settings.OPENAI_API_KEY),
            "rag_defaults": {
                "top_k": settings.RAG_TOP_K,
                "threshold": settings.RAG_SCORE_THRESHOLD,
                "w_semantic": settings.RAG_SEMANTIC_WEIGHT,
                "w_keyword": settings.RAG_KEYWORD_WEIGHT,
            },
        }
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api_root),
    path("api/", include("projects.urls")),
    path("api/", include("knowledge.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
