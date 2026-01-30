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

    # Archive
    is_archived = models.BooleanField(default=False, verbose_name='Archivált')
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name='Archiválás időpontja')

    # Soft delete
    is_deleted = models.BooleanField(default=False, verbose_name='Törölve')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Törlés időpontja')

    class Meta:
        verbose_name = 'Szezon'
        verbose_name_plural = 'Szezonok'
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    @classmethod
    def get_current(cls):
        return cls.objects.filter(is_active=True).first()

    def archive(self, cascade=True):
        """Archive this season and optionally cascade to competitions/phases/matches."""
        from django.utils import timezone
        now = timezone.now()
        self.is_archived = True
        self.archived_at = now
        self.save(update_fields=['is_archived', 'archived_at'])

        if cascade:
            for competition in self.competitions.filter(is_archived=False, is_deleted=False):
                competition.archive(cascade=True)

    def soft_delete(self, cascade=True):
        """Soft delete this season and optionally cascade to competitions/phases/matches."""
        from django.utils import timezone
        now = timezone.now()
        self.is_deleted = True
        self.deleted_at = now
        self.save(update_fields=['is_deleted', 'deleted_at'])

        if cascade:
            for competition in self.competitions.filter(is_deleted=False):
                competition.soft_delete(cascade=True)

    def restore(self, cascade=False):
        """Restore this season from archive or trash. Optionally cascade."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at'])

        if cascade:
            for competition in self.competitions.filter(is_archived=True):
                competition.restore(cascade=True)
            for competition in self.competitions.filter(is_deleted=True):
                competition.restore(cascade=True)


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

    # Default application settings for phases
    referee_application_default = models.BooleanField(
        default=False,
        verbose_name='JV jelentkezés (alapértelmezett)',
        help_text='Új szakaszok automatikusan öröklik'
    )
    inspector_application_default = models.BooleanField(
        default=False,
        verbose_name='Ellenőr jelentkezés (alapértelmezett)',
        help_text='Új szakaszok automatikusan öröklik'
    )
    tournament_director_application_default = models.BooleanField(
        default=False,
        verbose_name='TIG jelentkezés (alapértelmezett)',
        help_text='Új szakaszok automatikusan öröklik'
    )

    # Ordering
    order = models.PositiveIntegerField(
        default=0,
        verbose_name='Sorrend',
        help_text='Megjelenítési sorrend (kisebb szám = előrébb)'
    )

    # Archive
    is_archived = models.BooleanField(default=False, verbose_name='Archivált')
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name='Archiválás időpontja')

    # Soft delete
    is_deleted = models.BooleanField(default=False, verbose_name='Törölve')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Törlés időpontja')

    class Meta:
        verbose_name = 'Bajnokság'
        verbose_name_plural = 'Bajnokságok'
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.short_name}"

    def archive(self, cascade=True):
        """Archive this competition and optionally cascade to phases/matches."""
        from django.utils import timezone
        now = timezone.now()
        self.is_archived = True
        self.archived_at = now
        self.save(update_fields=['is_archived', 'archived_at'])

        if cascade:
            for phase in self.phases.filter(is_archived=False, is_deleted=False):
                phase.archive(cascade=True)

    def soft_delete(self, cascade=True):
        """Soft delete this competition and optionally cascade to phases/matches."""
        from django.utils import timezone
        now = timezone.now()
        self.is_deleted = True
        self.deleted_at = now
        self.save(update_fields=['is_deleted', 'deleted_at'])

        if cascade:
            for phase in self.phases.filter(is_deleted=False):
                phase.soft_delete(cascade=True)

    def restore(self, cascade=False):
        """Restore this competition from archive or trash. Optionally cascade."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at'])

        if cascade:
            for phase in self.phases.filter(is_archived=True):
                phase.restore(cascade=True)
            for phase in self.phases.filter(is_deleted=True):
                phase.restore(cascade=True)


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
    # Legacy payment fields (kept for backward compatibility)
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
    # Position-specific payments
    referee_payment = models.PositiveIntegerField(
        default=0,
        verbose_name='Játékvezető díjazás (Ft)',
        help_text='Díjazás játékvezetőnként'
    )
    referee_payment_type = models.CharField(
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.PER_PERSON,
        verbose_name='JV díjazás típusa'
    )
    reserve_payment = models.PositiveIntegerField(
        default=0,
        verbose_name='Tartalék díjazás (Ft)',
        help_text='Díjazás tartalékonként'
    )
    reserve_payment_type = models.CharField(
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.PER_PERSON,
        verbose_name='Tartalék díjazás típusa'
    )
    inspector_payment = models.PositiveIntegerField(
        default=0,
        verbose_name='Ellenőr díjazás (Ft)',
        help_text='Díjazás ellenőrönként'
    )
    inspector_payment_type = models.CharField(
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.PER_PERSON,
        verbose_name='Ellenőr díjazás típusa'
    )
    tournament_director_payment = models.PositiveIntegerField(
        default=0,
        verbose_name='Tornaigazgató díjazás (Ft)',
        help_text='Díjazás tornaigazgatónként'
    )
    tournament_director_payment_type = models.CharField(
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.PER_PERSON,
        verbose_name='TIG díjazás típusa'
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
    tournament_director_count = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Tornaigazgatók száma'
    )

    # Application settings
    referee_application_enabled = models.BooleanField(
        default=False,
        verbose_name='Játékvezető jelentkezés',
        help_text='Játékvezetők jelentkezhetnek meccsekre ebben a szakaszban'
    )
    inspector_application_enabled = models.BooleanField(
        default=False,
        verbose_name='Ellenőr jelentkezés',
        help_text='Ellenőrök jelentkezhetnek meccsekre ebben a szakaszban'
    )
    tournament_director_application_enabled = models.BooleanField(
        default=False,
        verbose_name='Tornaigazgató jelentkezés',
        help_text='Tornaigazgatók jelentkezhetnek meccsekre ebben a szakaszban'
    )

    requires_mfsz_declaration = models.BooleanField(
        default=True,
        verbose_name='MFSZ bejelentés szükséges',
        help_text='Ha be van jelölve, a könyvelő értesítést kap a mérkőzésekről'
    )

    # Archive
    is_archived = models.BooleanField(default=False, verbose_name='Archivált')
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name='Archiválás időpontja')

    # Soft delete
    is_deleted = models.BooleanField(default=False, verbose_name='Törölve')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Törlés időpontja')

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

    def archive(self, cascade=True):
        """Archive this phase and optionally cascade to matches."""
        from django.utils import timezone
        now = timezone.now()
        self.is_archived = True
        self.archived_at = now
        self.save(update_fields=['is_archived', 'archived_at'])

        if cascade:
            for match in self.matches.filter(is_archived=False, is_deleted=False):
                match.archive()

    def soft_delete(self, cascade=True):
        """Soft delete this phase and optionally cascade to matches."""
        from django.utils import timezone
        now = timezone.now()
        self.is_deleted = True
        self.deleted_at = now
        self.save(update_fields=['is_deleted', 'deleted_at'])

        if cascade:
            for match in self.matches.filter(is_deleted=False):
                match.soft_delete()

    def restore(self, cascade=False):
        """Restore this phase from archive or trash. Optionally cascade."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at'])

        if cascade:
            for match in self.matches.filter(is_archived=True):
                match.restore()
            for match in self.matches.filter(is_deleted=True):
                match.restore()


class Venue(models.Model):
    """Match venue/location."""
    name = models.CharField(max_length=200, verbose_name='Név')
    city = models.CharField(max_length=100, verbose_name='Város')
    postal_code = models.CharField(max_length=10, blank=True, verbose_name='Irányítószám')
    address = models.CharField(max_length=300, blank=True, verbose_name='Cím')
    google_maps_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name='Google Maps link',
        help_text='A helyszín Google Maps linkje (pl. https://maps.google.com/...)'
    )
    is_active = models.BooleanField(default=True, verbose_name='Aktív')

    # Archive
    is_archived = models.BooleanField(default=False, verbose_name='Archivált')
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name='Archiválás időpontja')

    # Soft delete
    is_deleted = models.BooleanField(default=False, verbose_name='Törölve')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Törlés időpontja')

    class Meta:
        verbose_name = 'Helyszín'
        verbose_name_plural = 'Helyszínek'
        ordering = ['city', 'name']

    def __str__(self):
        return f"{self.name} ({self.city})"

    def archive(self):
        """Archive this venue."""
        from django.utils import timezone
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def soft_delete(self):
        """Soft delete this venue."""
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        """Restore this venue from archive or trash."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at'])


class Club(models.Model):
    """Club that can have multiple teams."""
    name = models.CharField(max_length=200, verbose_name='Klub neve')
    short_name = models.CharField(max_length=50, blank=True, verbose_name='Rövid név')
    logo = models.ImageField(
        upload_to='club_logos/',
        blank=True,
        null=True,
        verbose_name='Logó'
    )
    is_active = models.BooleanField(default=True, verbose_name='Aktív')

    # Address
    country = models.CharField(max_length=100, blank=True, default='Magyarország', verbose_name='Ország')
    city = models.CharField(max_length=100, blank=True, verbose_name='Város')
    postal_code = models.CharField(max_length=20, blank=True, verbose_name='Irányítószám')
    address = models.CharField(max_length=255, blank=True, verbose_name='Cím')

    # Representative (Képviselő)
    representative_name = models.CharField(max_length=200, blank=True, verbose_name='Képviselő neve')
    representative_phone = models.CharField(max_length=50, blank=True, verbose_name='Képviselő telefonszáma')
    representative_email = models.EmailField(blank=True, verbose_name='Képviselő email')

    # Primary contact
    email = models.EmailField(blank=True, verbose_name='Email')
    phone = models.CharField(max_length=50, blank=True, verbose_name='Telefon')
    website = models.URLField(blank=True, verbose_name='Weboldal')
    facebook = models.URLField(blank=True, verbose_name='Facebook')

    # Archive
    is_archived = models.BooleanField(default=False, verbose_name='Archivált')
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name='Archiválás időpontja')

    # Soft delete
    is_deleted = models.BooleanField(default=False, verbose_name='Törölve')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Törlés időpontja')

    class Meta:
        verbose_name = 'Klub'
        verbose_name_plural = 'Klubbok'
        ordering = ['name']

    def __str__(self):
        return self.short_name or self.name

    @property
    def full_address(self):
        """Full formatted address."""
        parts = []
        if self.postal_code:
            parts.append(self.postal_code)
        if self.city:
            parts.append(self.city)
        if self.address:
            parts.append(self.address)
        return ', '.join(parts) if parts else ''

    @property
    def teams_count(self):
        """Number of teams in this club."""
        return self.teams.count()

    @property
    def active_teams_count(self):
        """Number of active teams in this club."""
        return self.teams.filter(is_active=True).count()

    def archive(self, cascade=True):
        """Archive this club and optionally cascade to teams."""
        from django.utils import timezone
        now = timezone.now()
        self.is_archived = True
        self.archived_at = now
        self.save(update_fields=['is_archived', 'archived_at'])

        if cascade:
            for team in self.teams.filter(is_archived=False, is_deleted=False):
                team.archive()

    def soft_delete(self, cascade=True):
        """Soft delete this club and optionally cascade to teams."""
        from django.utils import timezone
        now = timezone.now()
        self.is_deleted = True
        self.deleted_at = now
        self.save(update_fields=['is_deleted', 'deleted_at'])

        if cascade:
            for team in self.teams.filter(is_deleted=False):
                team.soft_delete()

    def restore(self, cascade=False):
        """Restore this club from archive or trash. Optionally cascade."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at'])

        if cascade:
            for team in self.teams.filter(is_archived=True):
                team.restore()
            for team in self.teams.filter(is_deleted=True):
                team.restore()


class ClubContact(models.Model):
    """Additional contacts for a club (email, phone, social media, etc.)."""

    class ContactType(models.TextChoices):
        EMAIL = 'email', 'Email'
        PHONE = 'phone', 'Telefon'
        WEBSITE = 'website', 'Weboldal'
        FACEBOOK = 'facebook', 'Facebook'
        INSTAGRAM = 'instagram', 'Instagram'
        TWITTER = 'twitter', 'Twitter/X'
        OTHER = 'other', 'Egyéb'

    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name='contacts',
        verbose_name='Klub'
    )
    contact_type = models.CharField(
        max_length=20,
        choices=ContactType.choices,
        default=ContactType.EMAIL,
        verbose_name='Típus'
    )
    label = models.CharField(max_length=100, blank=True, verbose_name='Címke', help_text='pl. "Titkárság", "Elnök"')
    value = models.CharField(max_length=255, verbose_name='Érték')

    class Meta:
        verbose_name = 'Klub elérhetőség'
        verbose_name_plural = 'Klub elérhetőségek'
        ordering = ['contact_type', 'label']

    def __str__(self):
        if self.label:
            return f"{self.get_contact_type_display()} ({self.label}): {self.value}"
        return f"{self.get_contact_type_display()}: {self.value}"


class Team(models.Model):
    """Team participating in matches, belongs to a Club."""
    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name='teams',
        verbose_name='Klub',
        null=True,  # Temporarily nullable for migration
        blank=True
    )
    # Suffix for team name (e.g., "U18", "Női") - appended to club name
    suffix = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Csapat megnevezés',
        help_text='Pl. "U18", "Női" - a klub nevéhez adódik'
    )
    # OR fully custom name - if set, this is used instead of club name + suffix
    custom_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Egyedi teljes név',
        help_text='Ha meg van adva, ez jelenik meg a klub neve helyett'
    )
    short_name = models.CharField(max_length=50, blank=True, verbose_name='Rövid név')
    logo = models.ImageField(
        upload_to='team_logos/',
        blank=True,
        null=True,
        verbose_name='Saját logó',
        help_text='Ha nincs megadva, a klub logója jelenik meg'
    )
    is_active = models.BooleanField(default=True, verbose_name='Aktív')
    is_tbd = models.BooleanField(
        default=False,
        verbose_name='TBD csapat',
        help_text='Ha be van jelölve, ez a csapat a "Még nem ismert" helyőrző'
    )

    # Team manager (Csapatvezető)
    manager_name = models.CharField(max_length=200, blank=True, verbose_name='Csapatvezető neve')
    manager_phone = models.CharField(max_length=50, blank=True, verbose_name='Csapatvezető telefonszáma')
    manager_email = models.EmailField(blank=True, verbose_name='Csapatvezető email')

    # Legacy field - kept for migration, will be removed later
    name = models.CharField(max_length=200, verbose_name='Név', blank=True, default='')
    city = models.CharField(max_length=100, blank=True, verbose_name='Város')

    # Competition enrollments
    competitions = models.ManyToManyField(
        'Competition',
        blank=True,
        related_name='teams',
        verbose_name='Bajnokságok',
        help_text='A csapat melyik bajnokságokban vesz részt'
    )

    # Archive
    is_archived = models.BooleanField(default=False, verbose_name='Archivált')
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name='Archiválás időpontja')

    # Soft delete
    is_deleted = models.BooleanField(default=False, verbose_name='Törölve')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Törlés időpontja')

    class Meta:
        verbose_name = 'Csapat'
        verbose_name_plural = 'Csapatok'
        ordering = ['-is_tbd', 'club__name', 'suffix']

    @property
    def display_name(self):
        """Full display name for the team."""
        if self.custom_name:
            return self.custom_name
        if self.club:
            if self.suffix:
                return f"{self.club.name} {self.suffix}"
            return self.club.name
        # Fallback for legacy data
        return self.name or 'Ismeretlen csapat'

    @property
    def effective_logo(self):
        """Team's logo, or club's logo if team has none."""
        if self.logo:
            return self.logo
        if self.club and self.club.logo:
            return self.club.logo
        return None

    def __str__(self):
        if self.short_name:
            return self.short_name
        if self.custom_name:
            return self.custom_name
        if self.club:
            if self.suffix:
                club_short = self.club.short_name or self.club.name
                return f"{club_short} {self.suffix}"
            return self.club.short_name or self.club.name
        # Fallback for legacy data
        return self.name or 'Ismeretlen csapat'

    def get_all_names(self):
        """Get all names including alternatives."""
        names = [self.display_name]
        if self.short_name:
            names.append(self.short_name)
        if self.custom_name and self.custom_name != self.display_name:
            names.append(self.custom_name)
        names.extend(self.alternative_names.values_list('name', flat=True))
        return names

    def archive(self):
        """Archive this team."""
        from django.utils import timezone
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def soft_delete(self):
        """Soft delete this team."""
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        """Restore this team from archive or trash."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at'])


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

    # Archive
    is_archived = models.BooleanField(
        default=False,
        verbose_name='Archivált',
        help_text='Ha be van jelölve, a mérkőzés az archívumba kerül'
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Archiválás időpontja'
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
    def has_open_referee_position(self):
        """Check if match has an open referee position with application enabled."""
        return self.assignments.filter(
            role=MatchAssignment.Role.REFEREE,
            placeholder_type='szukseges',
            application_enabled=True,
            user__isnull=True
        ).exists()

    @property
    def has_open_inspector_position(self):
        """Check if match has an open inspector position with application enabled."""
        return self.assignments.filter(
            role=MatchAssignment.Role.INSPECTOR,
            placeholder_type='szukseges',
            application_enabled=True,
            user__isnull=True
        ).exists()

    @property
    def has_open_td_position(self):
        """Check if match has an open tournament director position with application enabled."""
        return self.assignments.filter(
            role=MatchAssignment.Role.TOURNAMENT_DIRECTOR,
            placeholder_type='szukseges',
            application_enabled=True,
            user__isnull=True
        ).exists()

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

    def archive(self):
        """Archive this match."""
        from django.utils import timezone
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def soft_delete(self):
        """Soft delete this match."""
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        """Restore this match from archive or trash."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at'])


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

    # Per-position application toggle (only relevant when placeholder_type='szukseges')
    application_enabled = models.BooleanField(
        default=False,
        verbose_name='Jelentkezés engedélyezve',
        help_text='Ha be van kapcsolva és a pozíció "Szükséges", akkor lehet rá jelentkezni'
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


class MatchApplication(models.Model):
    """
    Match application - users can apply for matches before being assigned.
    """

    class Role(models.TextChoices):
        REFEREE = 'referee', 'Játékvezető'
        INSPECTOR = 'inspector', 'Ellenőr'
        TOURNAMENT_DIRECTOR = 'tournament_director', 'Tornaigazgató'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Várakozó'
        ACCEPTED = 'accepted', 'Elfogadva'
        WITHDRAWN = 'withdrawn', 'Visszavonva'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='match_applications',
        verbose_name='Felhasználó'
    )
    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='applications',
        verbose_name='Mérkőzés'
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        verbose_name='Szerepkör'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Státusz'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Mérkőzés jelentkezés'
        verbose_name_plural = 'Mérkőzés jelentkezések'
        ordering = ['-created_at']
        unique_together = ['user', 'match', 'role']

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.match} ({self.get_role_display()})"


class MatchFeedback(models.Model):
    """Feedback submitted by referee after a match."""

    class FeedbackType(models.TextChoices):
        OK = 'ok', 'Minden rendben'
        RED_CARD = 'red_card', 'Végleges kiállítás'
        ISSUE = 'issue', 'Egyéb probléma'

    assignment = models.OneToOneField(
        'MatchAssignment',
        on_delete=models.CASCADE,
        related_name='feedback',
        verbose_name='Kiírás'
    )
    feedback_type = models.CharField(
        max_length=20,
        choices=FeedbackType.choices,
        verbose_name='Visszajelzés típusa'
    )
    notes = models.TextField(
        blank=True,
        verbose_name='Megjegyzés'
    )
    submitted_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Beküldés időpontja'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Módosítás időpontja'
    )

    # Track reminder emails sent
    reminder_1_sent = models.BooleanField(default=False)
    reminder_3_sent = models.BooleanField(default=False)
    reminder_5_sent = models.BooleanField(default=False)
    reminder_7_sent = models.BooleanField(default=False)
    reminder_10_sent = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Mérkőzés visszajelzés'
        verbose_name_plural = 'Mérkőzés visszajelzések'
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.assignment.user.get_full_name()} - {self.assignment.match} ({self.get_feedback_type_display()})"

    @property
    def has_red_cards(self):
        return self.red_cards.exists()


class RedCardReport(models.Model):
    """Red card (végleges kiállítás) report within a match feedback."""

    class ViolationCode(models.TextChoices):
        CODE_10 = '10', '10) Játékos vagy csapatvezetés tagja elhagyja a csereterületet/büntetőpadot civakodásban való részvételhez'
        CODE_11 = '11', '11) Játékos vagy csapatvezetés tagja verekedésben vesz részt'
        CODE_12 = '12', '12) Játékos vagy csapatvezetés tagja brutális szabálytalanságot követ el, vagy kísérel meg elkövetni'
        CODE_13 = '13', '13) Játékos vagy csapatvezetés tagja súlyos sportszerűtlen magatartást tanúsít'
        CODE_14 = '14', '14) Játékos vagy csapatvezetés tagja fenyegető magatartást tanúsít'

    class OffenderFunction(models.TextChoices):
        PLAYER = 'player', 'Játékos'
        OFFICIAL = 'official', 'Hivatalos személy (Edző, csapatvezető, ...)'
        OTHER = 'other', 'Egyéb'

    feedback = models.ForeignKey(
        MatchFeedback,
        on_delete=models.CASCADE,
        related_name='red_cards',
        verbose_name='Visszajelzés'
    )
    incident_time = models.CharField(
        max_length=5,
        verbose_name='Jegyzőkönyvi idő',
        help_text='Formátum: MM:SS (pl. 15:30)'
    )
    violation_code = models.CharField(
        max_length=10,
        choices=ViolationCode.choices,
        verbose_name='Végleges kiállítás kódja (614/)'
    )
    offender_name = models.CharField(
        max_length=100,
        verbose_name='Elkövető neve'
    )
    offender_jersey_number = models.CharField(
        max_length=10,
        blank=True,
        verbose_name='Mezszám'
    )
    offender_function = models.CharField(
        max_length=20,
        choices=OffenderFunction.choices,
        verbose_name='Elkövető funkciója'
    )
    offender_function_other = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Egyéb funkció'
    )
    incident_description = models.TextField(
        verbose_name='Incidens leírása'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Létrehozás időpontja'
    )

    class Meta:
        verbose_name = 'Piros lap jelentés'
        verbose_name_plural = 'Piros lap jelentések'
        ordering = ['incident_time']

    def __str__(self):
        return f"{self.offender_name} - {self.incident_time} - {self.get_violation_code_display()[:50]}..."


class RedCardWitness(models.Model):
    """Witness for a red card report."""
    red_card_report = models.ForeignKey(
        RedCardReport,
        on_delete=models.CASCADE,
        related_name='witnesses',
        verbose_name='Piros lap jelentés'
    )
    name = models.CharField(max_length=100, verbose_name='Név')
    phone = models.CharField(max_length=20, verbose_name='Telefonszám')

    class Meta:
        verbose_name = 'Tanú'
        verbose_name_plural = 'Tanúk'

    def __str__(self):
        return f"{self.name} ({self.phone})"
