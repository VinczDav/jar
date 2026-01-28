from django.contrib import admin
from .models import Referee, Unavailability


class UnavailabilityInline(admin.TabularInline):
    model = Unavailability
    extra = 0


@admin.register(Referee)
class RefereeAdmin(admin.ModelAdmin):
    list_display = ('user', 'license_level', 'status', 'billing_type', 'city')
    list_filter = ('status', 'license_level', 'international_level', 'billing_type')
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'city')
    raw_id_fields = ('user',)
    inlines = [UnavailabilityInline]

    fieldsets = (
        ('Felhasználó', {
            'fields': ('user',)
        }),
        ('Személyes adatok', {
            'fields': ('phone',)
        }),
        ('Lakcím', {
            'fields': (
                ('postal_code', 'city'),
                ('street', 'street_type'),
                ('house_number', 'floor_door'),
            )
        }),
        ('Autó adatok', {
            'fields': (
                'has_travel_reimbursement',
                'drivers_license_number',
                ('car_brand', 'car_model'),
                'car_plate',
            ),
            'classes': ('collapse',)
        }),
        ('Szakmai adatok', {
            'fields': (
                ('license_level', 'international_level'),
                'medical_valid_until',
            )
        }),
        ('Adminisztráció', {
            'fields': (
                ('status', 'billing_type'),
                'jb_notes',
            )
        }),
    )


@admin.register(Unavailability)
class UnavailabilityAdmin(admin.ModelAdmin):
    list_display = ('referee', 'start_date', 'end_date', 'reason')
    list_filter = ('start_date',)
    search_fields = ('referee__user__first_name', 'referee__user__last_name')
    raw_id_fields = ('referee',)
