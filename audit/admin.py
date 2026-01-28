from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'category', 'action', 'object_repr', 'ip_address')
    list_filter = ('category', 'action', 'timestamp')
    search_fields = ('description', 'object_repr', 'user__email', 'user__first_name', 'user__last_name', 'ip_address')
    readonly_fields = (
        'timestamp', 'user', 'ip_address', 'user_agent',
        'category', 'action', 'object_type', 'object_id', 'object_repr',
        'description', 'changes', 'extra_data'
    )
    date_hierarchy = 'timestamp'
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
