from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, SiteSettings, Coordinator


@admin.register(Coordinator)
class CoordinatorAdmin(admin.ModelAdmin):
    list_display = ('get_name', 'get_phone', 'is_active', 'order')
    list_filter = ('is_active',)
    list_editable = ('is_active', 'order')
    search_fields = ('user__first_name', 'user__last_name', 'user__phone')
    ordering = ['order', 'user__last_name', 'user__first_name']
    autocomplete_fields = ['user']

    @admin.display(description='Név')
    def get_name(self, obj):
        return obj.name

    @admin.display(description='Telefon')
    def get_phone(self, obj):
        return obj.phone


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'min_cancellation_hours')
    fieldsets = (
        ('Lemondási beállítások', {
            'fields': ('min_cancellation_hours',)
        }),
    )

    def has_add_permission(self, request):
        # Only allow one instance
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')

    fieldsets = BaseUserAdmin.fieldsets + (
        ('JAR beállítások', {
            'fields': (
                'role',
                'profile_picture',
                'phone',
            )
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('JAR beállítások', {
            'fields': ('role',)
        }),
    )
