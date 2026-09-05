from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import models

from .models import AuditLog


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, models.Model):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


def log_action(action: str, obj=None, actor=None, **payload) -> AuditLog:
    """The single entry point for recording operation history."""
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(getattr(obj, "pk", "") or ""),
        payload=_json_safe(payload),
    )
