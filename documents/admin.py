from django.contrib import admin
from .models import DocumentCategory, Document, DocumentVersion, Notification


@admin.register(DocumentCategory)
class DocumentCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')
    search_fields = ('name',)


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 1
    readonly_fields = ('uploaded_at',)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'is_active', 'is_public', 'requires_jb_access')
    list_filter = ('category', 'is_active', 'is_public', 'requires_jb_access')
    search_fields = ('title', 'description')
    inlines = [DocumentVersionInline]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ('document', 'version_number', 'uploaded_by', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('document__title',)
    raw_id_fields = ('uploaded_by',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('recipient__username', 'title', 'message')
    raw_id_fields = ('recipient',)
