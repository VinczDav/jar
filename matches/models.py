from django.conf import settings
from django.db import models


class SavedColor(models.Model):
    """Saved colors with names for reuse."""
    name = models.CharField(max_length=50, verbose_name='Név')
    color = models.CharField(max_length=7, verbose_name='Szín', help_text='Hex színkód')
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')

    class Meta:
        verbose_name = 'Mentett szín'
        verbose_name_plural = 'Mentett színek'
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.name} ({self.color})"


class Season(models.Model):
    """Season/year for organizing matches."""
    name = models.CharField(max_length=50, verbose_name='Név')
    start_date = models.DateField(verbose_name='Kezdete')
    end_date = models.DateField(verbose_name='Vége')
    is_active = models.BooleanField(default=True, verbose_name='Aktív')

    class Meta:
        verbose_name = 'Szezon'
        verbose_name_plural = 'Szezonok'
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    @classmethod
    def get_current(cls):
        return cls.objects.filter(is_active=True).first()


class Competition(models.Model):
    """Competition/league (e.g., OB1, OB2, etc.)"""
    name = models.CharField(max_length=100, verbose_name='Név')
    short_name = models.CharField(max_length=20, verbose_name='Rövid név')
    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name='competitions',
        verbose_name='Szezon'
    )
    color = models.CharField(
        max_length=7,
        default='#6366f1',
        verbose_name='Szín',
        help_text='Hex színkód (pl. #6366f1)'
    )
    match_duration = models.PositiveIntegerField(
        default=60,
        verbose_name='Meccs időtartam (perc)',
        help_text='Egy mérkőzés átlagos időtartama percben'
    )

    class Meta:
        verbose_name = 'Bajnokság'
        verbose_name_plural = 'Bajnokságok'
        ordering = ['name']

    def __str__(self):
        return f"{self.short_name}"


class CompetitionPhase(models.Model):
    """Phase within a competition (e.g., alapszakasz, rájátszás)"""

    class PaymentType(models.TextChoices):
        PER_PERSON = 'per_person', 'Fő / mérkőzés'
        TOTAL = 'total', 'Összesen / mérkőzés'

    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name='phases',
        verbose_name='Bajnokság'
    )
    name = models.CharField(max_length=100, verbose_name='Név')
    payment_amount = models.PositiveIntegerField(
        default=0,
        verbose_name='Díjazás (Ft)',
        help_text='Mérkőzésenkénti díjazás forintban'
    )
    payment_type = models.CharField(
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.PER_PERSON,
        verbose_name='Díjazás típusa'
    )
    # Referee composition
    referee_count = models.PositiveSmallIntegerField(
        default=2,
        verbose_name='Játékvezetők száma'
    )
    reserve_count = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Tartalékok száma'
    )
    inspector_count = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Ellenőrök száma'
    )
    requires_mfsz_declaration = models.BooleanField(
        default=True,
        verbose_name='MFSZ bejelentés szükséges',
        help_text='Ha be van jelölve, a könyvelő értesítést kap a mérkőzésekről'
    )

    class Meta:
        verbose_name = 'Szakasz'
        verbose_name_plural = 'Szakaszok'

    def __str__(self):
        return f"{self.competition.short_name} - {self.name}"

    def get_payment_display(self):
        """Return formatted payment info."""
        if self.payment_amount == 0:
            return "Nincs beállítva"
        amount = f"{self.payment_amount:,}".replace(',', ' ')
        if self.payment_type == self.PaymentType.PER_PERSON:
            return f"{amount} Ft / fő"
        else:
            return f"{amount} Ft összesen"

    def get_composition_display(self):
        """Return formatted composition info."""
        parts = []
        if self.referee_count:
            parts.append(f"{self.referee_count} JV")
        if self.reserve_count:
            parts.append(f"{self.reserve_count} T")
        if self.inspector_count:
            parts.append(f"{self.inspector_count} E")
        return " + ".join(parts) if parts else "Nincs beállítva"


class Venue(models.Model):
    """Match venue/location."""
    name = models.CharField(max_length=200, verbose_name='Név')
    city = models.CharField(max_length=100, verbose_name='Város')
    address = models.CharField(max_length=300, blank=True, verbose_name='Cím')
    is_active = models.BooleanField(default=True, verbose_name='Aktív')

    class Meta:
        verbose_name = 'Helyszín'
        verbose_name_plural = 'Helyszínek'
        ordering = ['city', 'name']

    def __str__(self):
        return f"{self.name} ({self.city})"


class Team(models.Model):
    """Team participating in matches."""
    name = models.CharField(max_length=200, verbose_name='Név')
    short_name = models.CharField(max_length=50, blank=True, verbose_name='Rövid név')
    city = models.CharField(max_length=100, blank=True, verbose_name='Város')
    logo = models.ImageField(
        upload_to='team_logos/',
        blank=True,
        null=True,
        verbose_name='Logó'
    )
    is_active = models.BooleanField(default=True, verbose_name='Aktív')
    is_tbd = models.BooleanField(
        default=False,
        verbose_name='TBD csapat',
        help_text='Ha be van jelölve, ez a csapat a "Még nem ismert" helyőrző'
    )

    class Meta:
        verbose_name = 'Csapat'
        verbose_name_plural = 'Csapatok'
        ordering = ['-is_tbd', 'name']  # TBD teams first, then alphabetically

    def __str__(self):
        return self.short_name or self.name

    def get_all_names(self):
        """Get all names including alternatives."""
        names = [self.name]
        if self.short_name:
            names.append(self.short_name)
        names.extend(self.alternative_names.values_list('name', flat=True))
        return names


class TeamAlternativeName(models.Model):
    """Alternative names for a team (used in different competitions)."""
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='alternative_names',
        verbose_name='Csapat'
    )
    name = models.CharField(max_length=200, verbose_name='Alternatív név')
    competition = models.ForeignKey(
        'Competition',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Bajnokság (opcionális)'
    )

    class Meta:
        verbose_name = 'Alternatív csapatnév'
        verbose_name_plural = 'Alternatív csapatnevek'

    def __str__(self):
        if self.competition:
            return f"{self.name} ({self.competition.short_name})"
        return self.name


class Match(models.Model):
    """Match with all details and referee assignments."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Piszkozat'
        CREATED = 'created', 'Létrehozott'
        SCHEDULED = 'scheduled', 'Kiírt'
        CONFIRMED = 'confirmed', 'Megerősített'
        POSTPONED = 'postponed', 'Halasztott'
        CANCELLED = 'cancelled', 'Elmarad'

    # Basic info
    date = models.DateField(verbose_name='Dátum', null=True, blank=True)
    time = models.TimeField(verbose_name='Időpont', null=True, blank=True)
    venue = models.ForeignKey(
        Venue,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='matches',
        verbose_name='Helyszín'
    )
    court = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Pálya'
    )

    # Teams
    home_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        related_name='home_matches',
        verbose_name='Hazai csapat'
    )
    away_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        related_name='away_matches',
        verbose_name='Vendég csapat'
    )

    # Competition
    phase = models.ForeignKey(
        CompetitionPhase,
        on_delete=models.SET_NULL,
        null=True,
        related_name='matches',
        verbose_name='Szakasz'
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name='Státusz'
    )

    # Notes
    notes = models.TextField(blank=True, verbose_name='Megjegyzés')

    # Tournament settings
    is_tournament = models.BooleanField(
        default=False,
        verbose_name='Torna',
        help_text='Ha be van jelölve, ez egy torna (több meccs, 1 rendező csapat)'
    )
    tournament_match_count = models.PositiveIntegerField(
        default=1,
        verbose_name='Meccsek száma',
        help_text='Tornánál: hány meccs van összesen'
    )
    tournament_court_count = models.PositiveIntegerField(
        default=1,
        verbose_name='Pályák száma',
        help_text='Tornánál: hány pályán játszanak egyszerre (= játékvezetők száma)'
    )

    # Visibility settings
    is_hidden = models.BooleanField(
        default=False,
        verbose_name='Rejtett',
        help_text='Ha be van jelölve, a mérkőzés csak a kiírások oldalon látható'
    )
    is_assignment_published = models.BooleanField(
        default=False,
        verbose_name='Kiírás publikálva',
        help_text='Ha nincs bejelölve, a kiírás nem jelenik meg (Még nincs kiírás)'
    )

    # MFSZ declaration override
    mfsz_declaration_override = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name='MFSZ bejelentés felülírás',
        help_text='None: szakasz beállítás, True: kötelező bejelentés, False: nem kell bejelentés'
    )

    # Soft delete
    is_deleted = models.BooleanField(
        default=False,
        verbose_name='Törölve',
        help_text='Ha be van jelölve, a mérkőzés nem jelenik meg sehol (soft delete)'
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Törlés időpontja'
    )

    # Created by
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_matches',
        verbose_name='Létrehozta'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Mérkőzés'
        verbose_name_plural = 'Mérkőzések'
        ordering = ['-date', '-time']

    def __str__(self):
        if self.is_tournament:
            organizer = self.home_team.short_name if self.home_team else '?'
            return f"Torna: {organizer} ({self.tournament_match_count} meccs) ({self.date})"
        home = self.home_team.short_name if self.home_team else '?'
        away = self.away_team.short_name if self.away_team else '?'
        return f"{home} vs {away} ({self.date})"

    @property
    def is_all_confirmed(self):
        """Check if all referee assignments are ACCEPTED (not pending, not declined).

        Assignments with placeholder_type='nincs' (not needed) are automatically considered confirmed.
        """
        # Get all referee assignments (with users)
        user_assignments = self.assignments.filter(role=MatchAssignment.Role.REFEREE, user__isnull=False)

        # Get "nincs" placeholder assignments (these are auto-accepted)
        nincs_assignments = self.assignments.filter(role=MatchAssignment.Role.REFEREE, placeholder_type='nincs')

        # If there are no assignments at all, not confirmed
        if not user_assignments.exists() and not nincs_assignments.exists():
            return False

        # All user assignments must be ACCEPTED
        if user_assignments.exclude(response_status=MatchAssignment.ResponseStatus.ACCEPTED).exists():
            return False

        # "nincs" placeholders are automatically confirmed, no need to check them
        return True

    @property
    def has_declined(self):
        """Check if any visible referee assignment is declined (with placeholder_type='hianyzik')."""
        return self.assignments.filter(
            role=MatchAssignment.Role.REFEREE,
            response_status=MatchAssignment.ResponseStatus.DECLINED,
            placeholder_type='hianyzik'
        ).exists()

    @property
    def confirmed_count(self):
        """Count of confirmed referee assignments (accepted users + 'nincs' placeholders)."""
        accepted_users = self.assignments.filter(
            role=MatchAssignment.Role.REFEREE,
            user__isnull=False,
            response_status=MatchAssignment.ResponseStatus.ACCEPTED
        ).count()
        nincs_placeholders = self.assignments.filter(
            role=MatchAssignment.Role.REFEREE,
            placeholder_type='nincs'
        ).count()
        return accepted_users + nincs_placeholders

    @property
    def referee_count(self):
        """Count of all referee assignments (with actual users, not placeholders)."""
        return self.assignments.filter(
            role=MatchAssignment.Role.REFEREE,
            user__isnull=False
        ).count()

    @property
    def actual_referee_count(self):
        """Count of actual filled referee positions (users + 'nincs' placeholders)."""
        users = self.assignments.filter(
            role=MatchAssignment.Role.REFEREE,
            user__isnull=False
        ).count()
        nincs_placeholders = self.assignments.filter(
            role=MatchAssignment.Role.REFEREE,
            placeholder_type='nincs'
        ).count()
        return users + nincs_placeholders

    @property
    def required_referee_count(self):
        """Required referee count from phase settings."""
        return self.phase.referee_count if self.phase else 2

    @property
    def requires_mfsz_declaration(self):
        """Check if MFSZ declaration is required for this match.

        Priority: match override > phase setting
        """
        if self.mfsz_declaration_override is not None:
            return self.mfsz_declaration_override
        if self.phase:
            return self.phase.requires_mfsz_declaration
        return True  # Default: required

    def get_payment_per_referee(self):
        """Calculate payment per referee, handling tournament type."""
        if not self.phase or not self.phase.payment_amount:
            return 0

        if self.is_tournament:
            # Tournament: total = payment * match_count, then divide by court count (= referee count)
            total_payment = self.phase.payment_amount * self.tournament_match_count
            referee_count = self.tournament_court_count or 1  # Court count = referee count
            return total_payment // referee_count
        else:
            # Normal match: use phase payment type
            if self.phase.payment_type == 'per_person':
                return self.phase.payment_amount
            else:
                # Total payment divided by referees
                referee_count = self.referee_count or 1
                return self.phase.payment_amount // referee_count

    def get_total_tournament_payment(self):
        """Get total payment for tournament (payment * match_count)."""
        if not self.is_tournament or not self.phase:
            return 0
        return self.phase.payment_amount * self.tournament_match_count

    def get_referees(self):
        """Get visible referee assignments (excludes declined without placeholder_type='hianyzik')."""
        from django.db.models import Q
        return self.assignments.filter(role=MatchAssignment.Role.REFEREE).exclude(
            Q(response_status=MatchAssignment.ResponseStatus.DECLINED) & ~Q(placeholder_type='hianyzik')
        )

    def get_reserves(self):
        """Get visible reserve assignments (excludes declined without placeholder_type='hianyzik')."""
        from django.db.models import Q
        return self.assignments.filter(role=MatchAssignment.Role.RESERVE).exclude(
            Q(response_status=MatchAssignment.ResponseStatus.DECLINED) & ~Q(placeholder_type='hianyzik')
        )

    def get_inspectors(self):
        """Get visible inspector assignments (excludes declined without placeholder_type='hianyzik')."""
        from django.db.models import Q
        return self.assignments.filter(role=MatchAssignment.Role.INSPECTOR).exclude(
            Q(response_status=MatchAssignment.ResponseStatus.DECLINED) & ~Q(placeholder_type='hianyzik')
        )

    def get_tournament_directors(self):
        """Get visible tournament director assignments (excludes declined without placeholder_type='hianyzik')."""
        from django.db.models import Q
        return self.assignments.filter(role=MatchAssignment.Role.TOURNAMENT_DIRECTOR).exclude(
            Q(response_status=MatchAssignment.ResponseStatus.DECLINED) & ~Q(placeholder_type='hianyzik')
        )

    @property
    def has_time(self):
        """Check if match has a valid time (not None and not 00:00)."""
        from datetime import time
        return self.time is not None and self.time != time(0, 0)

    @property
    def missing_data(self):
        """Return list of missing required data fields."""
        missing = []
        if not self.date:
            missing.append('date')
        if not self.has_time:
            missing.append('time')
        if not self.venue:
            missing.append('venue')

        if self.is_tournament:
            # Tournament: needs organizer (home_team), court count
            if not self.home_team or (hasattr(self.home_team, 'is_tbd') and self.home_team.is_tbd):
                missing.append('home_team')
            if not self.tournament_court_count or self.tournament_court_count < 1:
                missing.append('court_count')
        else:
            # Regular match: needs both teams
            if not self.home_team or (hasattr(self.home_team, 'is_tbd') and self.home_team.is_tbd):
                missing.append('home_team')
            if not self.away_team or (hasattr(self.away_team, 'is_tbd') and self.away_team.is_tbd):
                missing.append('away_team')
        return missing

    @property
    def is_incomplete(self):
        """Check if match has any missing data."""
        return len(self.missing_data) > 0

    @property
    def has_started(self):
        """Check if match has started (date + time + 1 minute has passed)."""
        from datetime import datetime, timedelta
        from django.utils import timezone

        if not self.date or not self.time:
            return False

        # Combine date and time
        match_datetime = datetime.combine(self.date, self.time)
        # Make it timezone aware
        if timezone.is_naive(match_datetime):
            match_datetime = timezone.make_aware(match_datetime)

        # Add 1 minute grace period
        start_threshold = match_datetime + timedelta(minutes=1)

        return timezone.now() >= start_threshold

    @property
    def calculated_duration_minutes(self):
        """
        Calculate match/tournament duration in minutes.
        For tournaments: (match_count / court_count) * match_duration
        For regular matches: match_duration from competition
        """
        if not self.phase or not self.phase.competition:
            return None

        match_duration = self.phase.competition.match_duration
        if not match_duration:
            return None

        if self.is_tournament:
            court_count = self.tournament_court_count or 1
            match_count = self.tournament_match_count or 1
            # Effective matches = total matches / courts (parallel play)
            effective_matches = match_count / court_count
            return int(effective_matches * match_duration)
        else:
            return match_duration

    @property
    def calculated_end_time(self):
        """
        Calculate the end time based on start time and duration.
        Returns a time object or None if cannot calculate.
        """
        from datetime import datetime, timedelta

        if not self.time:
            return None

        duration = self.calculated_duration_minutes
        if not duration:
            return None

        # Combine with a dummy date to do time arithmetic
        start_dt = datetime.combine(datetime.today(), self.time)
        end_dt = start_dt + timedelta(minutes=duration)
        return end_dt.time()


class MatchAssignment(models.Model):
    """
    Referee assignment to a match.
    Links directly to User model, or can be a placeholder slot.
    """

    class Role(models.TextChoices):
        REFEREE = 'referee', 'Játékvezető'
        RESERVE = 'reserve', 'Tartalék'
        INSPECTOR = 'inspector', 'Ellenőr'
        TOURNAMENT_DIRECTOR = 'tournament_director', 'Tornaigazgató'

    class ResponseStatus(models.TextChoices):
        PENDING = 'pending', 'Függőben'
        ACCEPTED = 'accepted', 'Elfogadva'
        DECLINED = 'declined', 'Elutasítva'

    class PlaceholderType(models.TextChoices):
        NONE = '', '-'
        MISSING = 'hianyzik', 'Hiányzik!'
        NEEDED = 'szukseges', 'Szükséges'
        NOT_NEEDED = 'nincs', 'Nincs'

    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='assignments',
        verbose_name='Mérkőzés'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='match_assignments',
        verbose_name='Játékvezető',
        null=True,
        blank=True
    )
    placeholder_type = models.CharField(
        max_length=20,
        choices=PlaceholderType.choices,
        default='',
        blank=True,
        verbose_name='Helykitöltő típus'
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.REFEREE,
        verbose_name='Szerep'
    )
    response_status = models.CharField(
        max_length=20,
        choices=ResponseStatus.choices,
        default=ResponseStatus.PENDING,
        verbose_name='Válasz'
    )
    response_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Válasz dátuma'
    )
    decline_reason = models.CharField(
        max_length=300,
        blank=True,
        verbose_name='Elutasítás indoka'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Kijelölés'
        verbose_name_plural = 'Kijelölések'
        ordering = ['role', 'user__last_name']

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.match}"
