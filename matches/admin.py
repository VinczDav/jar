from django.contrib import admin
from .models import Season, Competition, CompetitionPhase, Venue, Team, Match, MatchAssignment


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_active')
    list_filter = ('is_active',)


class CompetitionPhaseInline(admin.TabularInline):
    model = CompetitionPhase
    extra = 1


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'season')
    list_filter = ('season',)
    search_fields = ('name', 'short_name')
    inlines = [CompetitionPhaseInline]


@admin.register(CompetitionPhase)
class CompetitionPhaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'competition')
    list_filter = ('competition__season',)


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'address')
    search_fields = ('name', 'city')
    list_filter = ('city',)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'city')
    search_fields = ('name', 'short_name', 'city')


class MatchAssignmentInline(admin.TabularInline):
    model = MatchAssignment
    extra = 1
    autocomplete_fields = ['user']


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('date', 'time', 'home_team', 'away_team', 'venue', 'phase', 'status')
    list_filter = ('status', 'phase__competition__season', 'phase__competition', 'date')
    search_fields = ('home_team__name', 'away_team__name', 'venue__name')
    date_hierarchy = 'date'
    raw_id_fields = ('home_team', 'away_team', 'venue')
    inlines = [MatchAssignmentInline]

    fieldsets = (
        ('Alapadatok', {
            'fields': (
                ('date', 'time'),
                ('venue', 'court'),
            )
        }),
        ('Csapatok', {
            'fields': (
                ('home_team', 'away_team'),
            )
        }),
        ('Bajnokság', {
            'fields': ('phase', 'status')
        }),
        ('Egyéb', {
            'fields': ('notes', 'created_by'),
            'classes': ('collapse',)
        }),
    )


@admin.register(MatchAssignment)
class MatchAssignmentAdmin(admin.ModelAdmin):
    list_display = ('match', 'get_user_name', 'role', 'response_status')
    list_filter = ('role', 'response_status', 'match__date')
    search_fields = ('user__first_name', 'user__last_name', 'user__email')
    raw_id_fields = ('match',)
    autocomplete_fields = ['user']

    @admin.display(description='Játékvezető')
    def get_user_name(self, obj):
        return obj.user.get_full_name()
