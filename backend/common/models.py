"""Shared abstract models.

Abstract models do not need an app_label, so this module stays outside
INSTALLED_APPS alongside the other shared helpers.
"""

from django.db import models


class TimeStampedModel(models.Model):
    """Every model in this project carries created_at / updated_at.

    specs/03-data-model.md preamble.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
