from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrator"
    PRODUCTION_MANAGER = "PRODUCTION_MANAGER", "Production manager"
    WAREHOUSE_MANAGER = "WAREHOUSE_MANAGER", "Warehouse manager"
    ACCOUNTANT = "ACCOUNTANT", "Accountant"
    SALES_MANAGER = "SALES_MANAGER", "Sales manager"


class User(AbstractUser):
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.ADMIN)

    def has_role(self, *roles: str) -> bool:
        return self.is_superuser or self.role in roles


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """Append-only log of every business operation."""

    actor = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name = "Audit record"
        verbose_name_plural = "Audit log"

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.object_type}#{self.object_id}"
