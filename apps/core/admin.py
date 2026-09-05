from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, User

admin.site.register(User, UserAdmin)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "object_type", "object_id", "actor")
    list_filter = ("action", "object_type")
    search_fields = ("object_id", "action")
