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
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_super_admin', 'is_active')
    list_filter = ('role', 'is_super_admin', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')

    # Base fieldsets - will be modified dynamically in get_fieldsets
    base_jar_fieldsets = (
        ('JAR beállítások', {
            'fields': (
                'role',
                'profile_picture',
                'phone',
            )
        }),
        ('További jogosultságok', {
            'fields': (
                'is_referee_flag',
                'is_jt_admin_flag',
                'is_vb_flag',
                'is_inspector_flag',
                'is_accountant_flag',
                'is_admin_flag',
            ),
            'classes': ('collapse',),
        }),
        ('Adminisztratív beállítások', {
            'fields': (
                'has_content_module',
                'is_hidden_from_colleagues',
                'is_login_disabled',
            )
        }),
        ('Szuper Admin (CSAK ITT ÁLLÍTHATÓ!)', {
            'fields': (
                'is_super_admin',
            ),
            'classes': ('collapse',),
            'description': 'Védett admin: nem kitiltható, végleges törlés joga, teljes napló hozzáférés, admin jog adási jog.'
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('JAR beállítások', {
            'fields': ('role',)
        }),
    )

    def get_fieldsets(self, request, obj=None):
        """Dynamically adjust fieldsets based on the user being edited."""
        fieldsets = list(BaseUserAdmin.fieldsets)

        # Check if current user is super admin
        is_super_admin = getattr(request.user, 'is_super_admin', False)

        # Build JAR fieldsets dynamically
        jar_fieldsets = []
        for name, options in self.base_jar_fieldsets:
            new_options = dict(options)

            # Super Admin fieldset: only show to super admins
            if name == 'Szuper Admin (CSAK ITT ÁLLÍTHATÓ!)':
                if not is_super_admin:
                    continue  # Skip this fieldset for non-super admins

            # If editing an Admin user, remove is_login_disabled
            if obj and obj.role == User.Role.ADMIN and name == 'Adminisztratív beállítások':
                fields = list(new_options['fields'])
                if 'is_login_disabled' in fields:
                    fields.remove('is_login_disabled')
                new_options['fields'] = tuple(fields)

            # Non-super admins cannot see is_admin_flag in További jogosultságok
            if not is_super_admin and name == 'További jogosultságok':
                fields = list(new_options['fields'])
                if 'is_admin_flag' in fields:
                    fields.remove('is_admin_flag')
                new_options['fields'] = tuple(fields)

            jar_fieldsets.append((name, new_options))

        return fieldsets + jar_fieldsets

    def get_readonly_fields(self, request, obj=None):
        """Make the primary role's flag read-only. Also restrict admin fields for non-super admins."""
        readonly = list(super().get_readonly_fields(request, obj))

        # Check if current user is super admin
        is_super_admin = getattr(request.user, 'is_super_admin', False)

        # Non-super admins cannot modify admin-related fields
        if not is_super_admin:
            # Make role readonly if it's currently ADMIN (to prevent changing from ADMIN to other)
            if obj and obj.role == User.Role.ADMIN:
                if 'role' not in readonly:
                    readonly.append('role')
            # Note: is_admin_flag is hidden from fieldsets for non-super admins

        if obj:
            # Map role to flag field
            role_flag_map = {
                User.Role.REFEREE: 'is_referee_flag',
                User.Role.JT_ADMIN: 'is_jt_admin_flag',
                User.Role.VB: 'is_vb_flag',
                User.Role.INSPECTOR: 'is_inspector_flag',
                User.Role.ACCOUNTANT: 'is_accountant_flag',
                User.Role.ADMIN: 'is_admin_flag',
            }
            # Make the primary role's flag read-only
            if obj.role in role_flag_map:
                flag_field = role_flag_map[obj.role]
                if flag_field not in readonly:
                    readonly.append(flag_field)

        return readonly

    def save_model(self, request, obj, form, change):
        """Enforce super admin restrictions when saving."""
        is_super_admin = getattr(request.user, 'is_super_admin', False)

        if not is_super_admin and change:
            # Non-super admins cannot grant admin rights
            original = User.objects.get(pk=obj.pk)

            # Prevent changing role TO admin
            if obj.role == User.Role.ADMIN and original.role != User.Role.ADMIN:
                obj.role = original.role

            # Prevent granting is_admin_flag
            if obj.is_admin_flag and not original.is_admin_flag:
                obj.is_admin_flag = False

            # Prevent revoking is_admin_flag (only super admin can do this)
            if not obj.is_admin_flag and original.is_admin_flag:
                obj.is_admin_flag = True

            # Prevent modifying is_super_admin
            if obj.is_super_admin != original.is_super_admin:
                obj.is_super_admin = original.is_super_admin

        super().save_model(request, obj, form, change)
