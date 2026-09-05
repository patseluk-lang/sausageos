from django.contrib import admin

from .models import Recipe, RecipeLine, RecipeVersion


class RecipeLineInline(admin.TabularInline):
    model = RecipeLine
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("product",)


@admin.register(RecipeVersion)
class RecipeVersionAdmin(admin.ModelAdmin):
    list_display = ("recipe", "version", "valid_from", "status", "yield_min", "yield_max")
    list_filter = ("status",)
    inlines = [RecipeLineInline]
