from django.contrib import admin
from .models import FeeStructure, MatchFee, MonthlyStatement, StatementLine


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ('phase', 'role', 'amount', 'valid_from', 'valid_until')
    list_filter = ('phase__competition__season', 'role')
    search_fields = ('phase__name', 'phase__competition__name')


@admin.register(MatchFee)
class MatchFeeAdmin(admin.ModelAdmin):
    list_display = ('assignment', 'base_amount', 'split_ratio', 'final_amount')
    search_fields = ('assignment__referee__user__first_name', 'assignment__referee__user__last_name')
    raw_id_fields = ('assignment',)


class StatementLineInline(admin.TabularInline):
    model = StatementLine
    extra = 0
    raw_id_fields = ('match_fee',)


@admin.register(MonthlyStatement)
class MonthlyStatementAdmin(admin.ModelAdmin):
    list_display = ('referee', 'year', 'month', 'total_amount', 'match_count', 'status')
    list_filter = ('status', 'year', 'month')
    search_fields = ('referee__user__first_name', 'referee__user__last_name')
    raw_id_fields = ('referee', 'approved_by')
    inlines = [StatementLineInline]

    fieldsets = (
        ('Alapadatok', {
            'fields': (
                'referee',
                ('year', 'month'),
            )
        }),
        ('Összesítés', {
            'fields': (
                ('total_amount', 'match_count'),
                'status',
            )
        }),
        ('Jóváhagyás', {
            'fields': (
                ('approved_by', 'approved_at'),
                'notes',
            )
        }),
    )
