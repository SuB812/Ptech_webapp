from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register


class KnowledgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "knowledge"
    verbose_name = "지식베이스"

    def ready(self) -> None:
        register(check_embedding_dimension, "database")


def check_embedding_dimension(app_configs, databases=None, **kwargs):
    """Fail loudly when EMBEDDING_DIM no longer matches the stored column.

    Changing the embedding model can change the dimension. If old and new
    vectors mix silently, search results become meaningless while still looking
    plausible -- so this is an error, not a warning
    (specs/05-rag-pipeline.md section 4).
    """
    if not databases:
        return []

    from django.db import connections

    expected = settings.EMBEDDING_DIM
    errors = []

    for alias in databases:
        connection = connections[alias]
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT a.atttypmod
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    WHERE c.relname = 'knowledge_knowledgechunk'
                      AND a.attname = 'embedding'
                      AND a.attnum > 0
                    """
                )
                row = cursor.fetchone()
        except Exception:
            # Table not created yet, or the database is unreachable. Neither is
            # this check's business to report.
            continue

        if not row or row[0] in (None, -1):
            continue

        actual = row[0]
        if actual != expected:
            errors.append(
                Error(
                    f"임베딩 차원 불일치: DB 컬럼은 {actual} 차원인데 "
                    f"EMBEDDING_DIM 은 {expected} 입니다.",
                    hint=(
                        "EMBEDDING_DIM 을 되돌리거나, 지식 문서를 전부 재색인하고 "
                        "마이그레이션을 다시 만드세요. 차원이 섞이면 검색 결과가 "
                        "그럴듯해 보이면서 무의미해집니다."
                    ),
                    id="knowledge.E001",
                )
            )

    return errors
